# -*- coding: utf-8 -*-
"""
Backtest "phát lại live": chạy lại đúng vòng lặp bot/paper_loop.py trên dữ liệu lịch sử,
cho mọi phương pháp (PP1–PP4) và nhiều cặp coin cùng lúc.

Dùng lại trực tiếp code chiến lược của bot (strategy/*, bot/paper_fees.py, config/settings.py),
chỉ thay đồng hồ thật bằng đồng hồ mô phỏng:

- Mỗi phút mô phỏng một "tick" đầu nến 1m: nến 1m trước đó đã đóng (đủ high/low) và nến đang chạy
  mới có giá mở. Tầng 1 (thanh lý, hard stop PP4, ATR trailing) quét như exit_engine:
  nến vừa đóng rồi nến đang chạy — ATR lấy từ nến 1H đã đóng gần nhất (refresh_atr_from_1h).
- Đầu mỗi nến 4H (cửa sổ 03/07/11/15/19/23h giờ VN): tầng thoát 4H gọi thẳng
  strategy.exit_engine.compute_exit_candidates, rồi xét vào lệnh như paper_loop
  (giá vào/ra = giá mở nến 1m đầu tiên của nến 4H mới).
- Circuit breaker PP3/PP4 dùng thời gian mô phỏng thay cho datetime.now().

Chạy:  python backtest/live_replay.py --symbols BTCUSDT --start 2025-10-01 --end 2026-10-01
Xem:   python backtest/live_replay.py --help
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from config import settings
from bot.paper_fees import linear_taker_fee_usdt
from strategy.indicators import add_indicators, add_indicators_m3
from strategy.signals import long_entry, short_entry, m4_entry_1h_confirm, m4_entry_rsi_extreme_block
from strategy.risk import (
    size_and_margin,
    atr_1h_at_entry,
    check_atr_trailing,
    limit_pnl_and_exit_price,
    max_loss_from_capital,
    m3_adx_zone,
    m4_adx_zone,
    m3_streak_multiplier,
)
from strategy.exit_engine import compute_exit_candidates, pick_best_exit
from strategy.strategies.registry import METHOD_1, METHOD_2, METHOD_3, METHOD_4

H1 = pd.Timedelta(hours=1)
H4 = pd.Timedelta(hours=4)
ALL_METHODS = (METHOD_1, METHOD_2, METHOD_3, METHOD_4)


class _Bar(dict):
    """Nến 1m nhẹ cho check_atr_trailing (cần row["high"], row["low"], row.name)."""

    __slots__ = ("name",)

    def __init__(self, name, high, low):
        super().__init__(high=high, low=low)
        self.name = name


def _f(v):
    try:
        x = float(v)
        return x if pd.notna(x) else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Dữ liệu đã chuẩn bị cho một cặp coin
# ---------------------------------------------------------------------------
class MarketData:
    """
    strict=True (mặc định): tại mỗi thời điểm t chỉ đưa cho code chiến lược các nến ĐÃ ĐÓNG trước t
    (cửa sổ 200 nến như BinanceClient live), tính lại chỉ báo trên đúng cửa sổ đó → không thể nhìn trước.
    strict=False (--fast): tính chỉ báo một lần trên toàn chuỗi rồi chỉ đọc giá trị của nến đã đóng.
    Chỉ báo của bot đều là nhân quả (RSI/ATR/EMA/WMA/ADX/rolling chỉ dùng nến cũ hơn), nên hai chế độ
    cho cùng giá trị — tests/test_live_replay.py kiểm tra điều này bằng cách cắt dữ liệu tại t.
    """

    WINDOW = 200  # số nến live lấy về: get_klines_4h(limit=200), get_klines_1h(limit=200)

    def __init__(self, symbol: str, df_1m: pd.DataFrame, strict: bool = True):
        self.symbol = symbol
        self.strict = strict
        self.df_1m = df_1m
        self.idx = df_1m.index
        self.o = df_1m["open"].to_numpy(float)
        self.h = df_1m["high"].to_numpy(float)
        self.l = df_1m["low"].to_numpy(float)
        self.c = df_1m["close"].to_numpy(float)

        from backtest.binance_data import resample_ohlcv

        # Nến 4H/1H mở lúc T chỉ gộp các nến 1m trong [T, T+4h) → chỉ được đọc khi t >= T+4h (đã đóng).
        self.df4_raw = resample_ohlcv(df_1m, "4h")
        self.df1h_raw = resample_ohlcv(df_1m, "1h")
        self._atr_cache = {}
        if not strict:
            self.ind4 = add_indicators(self.df4_raw)
            self.ind4_m3 = self._m3(self.df4_raw)
            self.ind1h = add_indicators(self.df1h_raw)
            closed_1h = self.idx.floor("h") - H1
            self._atr_fast = self.ind1h["ATR"].reindex(closed_1h).to_numpy(float)

        # Phút đầu tiên của mỗi nến 4H = tick trong cửa sổ vào lệnh của paper_loop
        utc = self.idx.tz_convert("UTC")
        self.is_boundary = np.asarray((utc.hour % 4 == 0) & (utc.minute == 0))

    @staticmethod
    def _m3(df):
        return add_indicators_m3(
            df,
            ema_trend_len=getattr(settings, "M3_EMA_TREND_LEN", 50),
            swing_lookback=getattr(settings, "M3_SWING_LOOKBACK", 6),
        )

    @staticmethod
    def _with_forming(closed: pd.DataFrame, t, open_px):
        """Thêm nến đang chạy (mới có giá mở) như dữ liệu live tại tick đầu tiên."""
        forming = pd.DataFrame(
            {"open": [open_px], "high": [open_px], "low": [open_px], "close": [open_px], "volume": [0.0]},
            index=pd.DatetimeIndex([t], name=closed.index.name),
        )
        return pd.concat([closed, forming])

    def _past(self, df_raw, last_closed_open):
        """Các nến đã đóng, nến cuối mở lúc last_closed_open (tối đa WINDOW-1 nến, chừa chỗ nến đang chạy)."""
        return df_raw.loc[:last_closed_open].tail(self.WINDOW - 1)

    def atr_at(self, i: int) -> float:
        """ATR nến 1H đã đóng gần nhất tại phút i (refresh_atr_from_1h dùng df_1h.iloc[-2])."""
        if not self.strict:
            return self._atr_fast[i]
        h = self.idx[i].floor("h") - H1
        v = self._atr_cache.get(h)
        if v is None:
            ind = add_indicators(self._past(self.df1h_raw, h))
            v = float(ind["ATR"].iloc[-1]) if len(ind) and ind.index[-1] == h else float("nan")
            self._atr_cache[h] = v
        return v

    def context_at(self, i: int):
        """Dữ liệu paper_loop thấy ở tick đầu nến 4H mở lúc t = idx[i]; None nếu chưa đủ dữ liệu."""
        t, open_px = self.idx[i], float(self.o[i])
        t_closed, t_prev = t - H4, t - 2 * H4
        if self.strict:
            raw4 = self._past(self.df4_raw, t_closed)
            ind4 = add_indicators(raw4)
            if len(ind4) < 2 or ind4.index[-1] != t_closed or ind4.index[-2] != t_prev:
                return None
            m3 = self._m3(raw4)
            row_m3 = m3.iloc[-1] if len(m3) and m3.index[-1] == t_closed else None
            raw1 = self._past(self.df1h_raw, t - H1)
            ind1 = add_indicators(raw1)
            if len(ind1) >= 2 and ind1.index[-1] == t - H1:
                last = ind1.iloc[[-1]].copy()
                last.index = pd.DatetimeIndex([t], name=ind1.index.name)
                df_1h = pd.concat([ind1.tail(2), last])  # nến đang chạy: giá trị không được đọc
            else:
                df_1h = pd.DataFrame()
            return {
                "row_closed": ind4.iloc[-1], "prev_row_closed": ind4.iloc[-2], "row_m3": row_m3,
                "df_1h": df_1h, "df_4h_raw": self._with_forming(raw4, t, open_px),
            }
        if t_closed not in self.ind4.index or t_prev not in self.ind4.index:
            return None
        closed1 = self.ind1h.loc[: t - H1].tail(2)
        if len(closed1) == 2 and closed1.index[-1] == t - H1:
            last = closed1.iloc[[-1]].copy()
            last.index = pd.DatetimeIndex([t], name=closed1.index.name)
            df_1h = pd.concat([closed1, last])
        else:
            df_1h = pd.DataFrame()
        return {
            "row_closed": self.ind4.loc[t_closed], "prev_row_closed": self.ind4.loc[t_prev],
            "row_m3": self.ind4_m3.loc[t_closed] if t_closed in self.ind4_m3.index else None,
            "df_1h": df_1h,
            "df_4h_raw": self._with_forming(self._past(self.df4_raw, t_closed), t, open_px),
        }


# ---------------------------------------------------------------------------
# Một slot paper (một phương pháp) trên một cặp coin
# ---------------------------------------------------------------------------
class SlotSim:
    def __init__(self, method: str, capital: float, leverage: float, wallet_pct: float, lookback_trades: int):
        self.method = method
        self.balance = float(capital)
        self.leverage = leverage
        self.wallet_pct = wallet_pct
        self.lookback_trades = lookback_trades
        self.open_trade = None
        self._risk = None  # hằng số tầng 1 của lệnh đang mở
        self.trades = []
        self.losses = 0
        self.cb_light_until = None
        self.cb_heavy_until = None

    # ----- Tầng 1: thanh lý / hard stop / ATR trailing (giống exit_engine.compute_exit_candidates) -----
    def _prepare_risk(self):
        ot = self.open_trade
        entry, size, side = float(ot["entry_price"]), float(ot["size"]), ot["side"]
        max_loss = max_loss_from_capital(ot)
        maint = settings.MAINT_MARGIN_RATE * ot["notional"]
        margin = ot["margin"]
        hard_stop_px = None
        if self.method == METHOD_4 and size > 0:
            hard_stop_px = entry - max_loss / size if side == "LONG" else entry + max_loss / size
        liq_px = entry + (maint - margin) / size if side == "LONG" else entry - (maint - margin) / size
        if hard_stop_px is None:
            hs_closer = False
        elif side == "LONG":
            hs_closer = hard_stop_px >= liq_px
        else:
            hs_closer = hard_stop_px <= liq_px
        self._risk = (entry, size, side, max_loss, margin, hard_stop_px, liq_px, hs_closer)

    def layer1(self, t, high, low):
        entry, size, side, max_loss, margin, hs_px, liq_px, hs_closer = self._risk
        if side == "LONG":
            hit_liq = low <= liq_px
            hit_hs = hs_px is not None and low <= hs_px
        else:
            hit_liq = high >= liq_px
            hit_hs = hs_px is not None and high >= hs_px
        if hit_hs and (not hit_liq or hs_closer):
            fee_out = linear_taker_fee_usdt(size, hs_px, float(settings.TAKER_FEE))
            return (t, -max_loss - fee_out, hs_px, "HARD_STOP")
        if hit_liq:
            return (t, -margin, liq_px, "LIQUIDATION")
        pnl_raw, exit_px = check_atr_trailing(self.open_trade, _Bar(t, high, low))
        if pnl_raw is not None:
            pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
            if px_lim is not None:
                exit_px = px_lim
            fee_out = linear_taker_fee_usdt(size, exit_px, float(settings.TAKER_FEE))
            return (t, pnl_lim - fee_out, exit_px, "ATR_TRAIL")
        return None

    def step_layer1(self, md: "MarketData", i: int) -> list:
        """Tick đầu phút i: refresh ATR 1H, quét nến 1m vừa đóng (i-1) rồi nến đang chạy (i, mới có giá mở)."""
        ot = self.open_trade
        atr = md.atr_at(i)
        if not np.isnan(atr) and atr > 0:
            ot["atr"] = float(atr)  # refresh_atr_from_1h
        t, prev_t = md.idx[i], md.idx[i - 1]
        c = None
        if prev_t >= ot["last_sl_check"]:
            c = self.layer1(prev_t, md.h[i - 1], md.l[i - 1])
        if c is None:
            c = self.layer1(t, md.o[i], md.o[i])
        ot["last_sl_check"] = t
        return [c] if c else []

    # ----- Đóng lệnh + circuit breaker (giống paper_loop._update_slot_circuit_breaker) -----
    def close(self, best, row_closed, now):
        best_time, best_pnl, best_px, reason = best
        ot = self.open_trade
        capital_after = self.balance + best_pnl
        self.trades.append({
            "method": self.method,
            "side": ot["side"],
            "entry_time": ot["entry_time"],
            "exit_time": best_time,
            "entry_price": ot["entry_price"],
            "exit_price": best_px,
            "size": ot["size"],
            "margin": ot["margin"],
            "fee_in": ot["_fee_in"],
            "profit": best_pnl,
            "capital_before": self.balance,
            "capital_after": capital_after,
            "exit_reason": reason,
            "entry_rsi": ot.get("entry_rsi"),
            "exit_rsi": _f(row_closed.get("RSI")) if row_closed is not None else None,
        })
        self.balance = capital_after
        self.open_trade = None
        self._risk = None
        if self.method in (METHOD_3, METHOD_4):
            self._update_cb(best_pnl, capital_after, now)

    def _update_cb(self, pnl, balance, now):
        self.losses = self.losses + 1 if pnl < 0 else 0
        if self.losses >= settings.M3_CB_HEAVY_STREAK:
            self.cb_heavy_until = now + timedelta(hours=settings.M3_CB_HEAVY_BARS * 4)
            self.cb_light_until = None
        elif self.losses >= settings.M3_CB_LIGHT_STREAK:
            self.cb_light_until = now + timedelta(hours=settings.M3_CB_LIGHT_BARS * 4)
        cutoff = now - timedelta(days=settings.M3_CB_HEAVY_DD_DAYS)
        recent = [t for t in self.trades if t["entry_time"] >= cutoff]
        if recent:
            peak = max(float(t["capital_after"] or 0) for t in recent)
            if peak > 0 and balance > 0 and (peak - balance) / peak * 100 >= settings.M3_CB_HEAVY_DD_PCT:
                self.cb_heavy_until = now + timedelta(hours=settings.M3_CB_HEAVY_BARS * 4)

    # ----- Vào lệnh (giống paper_loop, nhánh "not open_trade and running and in_4h_window") -----
    def try_enter(self, md: MarketData, t, entry_px, prev_row_closed, row_closed, row_m3, df_1h):
        method = self.method
        if method in (METHOD_3, METHOD_4):
            if self.cb_heavy_until and t < self.cb_heavy_until:
                return
            if self.cb_light_until and t < self.cb_light_until:
                return

        sig_long = long_entry(prev_row_closed, row_closed)
        sig_short = short_entry(prev_row_closed, row_closed)
        if not (sig_long or sig_short):
            return
        side = "LONG" if sig_long else "SHORT"

        if method == METHOD_4:
            if m4_entry_rsi_extreme_block(side, row_closed.get("RSI")):
                return
            if getattr(settings, "M4_REQUIRE_1H_CONFIRM", True) and not m4_entry_1h_confirm(side, df_1h):
                return

        size_mult = 1.0
        if method in (METHOD_3, METHOD_4) and row_m3 is not None:
            adx_val = float(row_m3.get("ADX", 25.0) or 25.0)
            allow, adx_size_mult = m4_adx_zone(adx_val) if method == METHOD_4 else m3_adx_zone(adx_val)
            if not allow:
                return
            size_mult = adx_size_mult
            if adx_val > getattr(settings, "M3_EMA_TREND_ADX_ABOVE", 30.0):
                ema_trend_val = float(row_m3.get("EMA_TREND", 0.0) or 0.0)
                close_val = float(row_m3.get("close", 0.0) or 0.0)
                if ema_trend_val > 0 and close_val > 0:
                    if side == "LONG" and close_val < ema_trend_val:
                        return
                    if side == "SHORT" and close_val > ema_trend_val:
                        return
            disagree_size = getattr(settings, "M3_SWING_DISAGREE_SIZE", 0.6)
            higher_low = bool(row_m3.get("higher_low", False))
            lower_high = bool(row_m3.get("lower_high", False))
            if side == "LONG" and lower_high and not higher_low:
                size_mult = min(size_mult, disagree_size)
            elif side == "SHORT" and higher_low and not lower_high:
                size_mult = min(size_mult, disagree_size)
            size_mult *= m3_streak_multiplier(self.losses)

        size, margin, notional = size_and_margin(self.balance, entry_px, leverage=self.leverage, wallet_pct=self.wallet_pct)
        if method in (METHOD_3, METHOD_4) and size_mult < 1.0:
            size, margin, notional = size * size_mult, margin * size_mult, notional * size_mult
        if size <= 0 or margin > self.balance:
            return
        fee_in = linear_taker_fee_usdt(size, entry_px, float(settings.TAKER_FEE))

        atr_now = atr_1h_at_entry(df_1h, float(row_closed["ATR"]))
        if method == METHOD_3:
            # Live gọi m3_atr_multiplier(datetime.now()) ngay lúc mở → luôn ra hệ số grace
            atr_mult_now = settings.M3_ATR_MULTIPLIER_GRACE
        elif method == METHOD_4:
            atr_mult_now = settings.M4_ATR_MULTIPLIER_GRACE
        else:
            atr_mult_now = settings.ATR_MULTIPLIER
        trail_dist = atr_now * atr_mult_now
        init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist

        ot = {
            "side": side,
            "entry_time": t,
            "entry_price": entry_px,
            "size": size,
            "margin": margin,
            "capital_before": self.balance,
            "atr": atr_now,
            "notional": notional,
            "trail_stop": init_stop,
            "last_sl_check": t,
            "entry_rsi": _f(row_closed.get("RSI")),
            "entry_ema_rsi": _f(row_closed.get("EMA_RSI")),
            "entry_wma_rsi": _f(row_closed.get("WMA_RSI")),
            "entry_4h_ts": t - H4,
            "trading_method": method,
            "_fee_in": fee_in,
        }
        if method in (METHOD_3, METHOD_4):
            ot["atr_multiplier_override"] = atr_mult_now
        if method == METHOD_4:
            ot["max_stop_capital_pct"] = settings.M4_MAX_STOP_CAPITAL_PCT
        self.open_trade = ot
        self.balance -= fee_in
        self._prepare_risk()


# ---------------------------------------------------------------------------
# Vòng lặp mô phỏng
# ---------------------------------------------------------------------------
def run_symbol(md: MarketData, start, methods, capital, leverage, wallet_pct, lookback_trades):
    slots = [SlotSim(m, capital, leverage, wallet_pct, lookback_trades) for m in methods]
    n = len(md.idx)
    i0 = int(md.idx.searchsorted(pd.Timestamp(start)))
    boundary_pos = np.flatnonzero(md.is_boundary)
    o = md.o

    i = max(i0, 1)
    while i < n:
        t = md.idx[i]
        is_b = bool(md.is_boundary[i])
        open_slots = [s for s in slots if s.open_trade is not None]

        ctx = md.context_at(i) if is_b else None

        # ---- Lệnh đang mở: tầng 1 mỗi phút, tầng 4H ở đầu nến 4H ----
        for s in open_slots:
            ot = s.open_trade
            cands = s.step_layer1(md, i)

            if ctx is not None:
                entry_4h_ts = ot.get("entry_4h_ts")
                allow_early = entry_4h_ts is None or (t - H4) != entry_4h_ts
                df_1m_now = pd.DataFrame({"open": [o[i]], "high": [o[i]], "low": [o[i]], "close": [o[i]]}, index=pd.DatetimeIndex([t]))
                saved = ot["last_sl_check"]
                ot["last_sl_check"] = None  # tầng 1 đã chạy ở trên
                try:
                    cands += compute_exit_candidates(
                        ot, df_1m_now, ctx["df_1h"], ctx["df_4h_raw"],
                        ctx["prev_row_closed"], ctx["row_closed"], float(o[i]), t,
                        paper_use_4h_window=True, in_4h_window=True, method=s.method,
                        lookback_trades=s.lookback_trades, allow_early_exit=allow_early,
                    )
                finally:
                    ot["last_sl_check"] = saved

            best = pick_best_exit(cands)
            if best is not None:
                s.close(best, ctx["row_closed"] if ctx else None, t)

        # ---- Vào lệnh trong cửa sổ 4H ----
        if ctx is not None:
            for s in slots:
                if s.open_trade is None:
                    s.try_enter(md, t, float(o[i]), ctx["prev_row_closed"], ctx["row_closed"], ctx["row_m3"], ctx["df_1h"])

        if any(s.open_trade is not None for s in slots):
            i += 1
        else:
            k = int(np.searchsorted(boundary_pos, i + 1))
            if k >= len(boundary_pos):
                break
            i = int(boundary_pos[k])

    # Lệnh còn mở cuối dữ liệu: đóng theo giá cuối để tính kết quả
    last_t, last_px = md.idx[-1], float(md.c[-1])
    for s in slots:
        ot = s.open_trade
        if ot is None:
            continue
        size, entry = float(ot["size"]), float(ot["entry_price"])
        pnl_raw = (last_px - entry) * size if ot["side"] == "LONG" else (entry - last_px) * size
        fee_out = linear_taker_fee_usdt(size, last_px, float(settings.TAKER_FEE))
        s.close((last_t, pnl_raw - fee_out, last_px, "END_OF_DATA"), None, last_t)
    return slots


# ---------------------------------------------------------------------------
# Thống kê
# ---------------------------------------------------------------------------
def summarize(symbol, slot: SlotSim, capital, start, end):
    tr = slot.trades
    profits = np.array([t["profit"] - t["fee_in"] for t in tr], float)
    equity = np.concatenate([[capital], [t["capital_after"] for t in tr]]) if tr else np.array([capital])
    peak = np.maximum.accumulate(equity)
    dd = ((peak - equity) / np.where(peak > 0, peak, 1)).max() * 100 if len(equity) else 0.0
    gains, losses = profits[profits > 0].sum(), -profits[profits < 0].sum()
    reasons = pd.Series([t["exit_reason"] for t in tr]).value_counts().to_dict() if tr else {}
    return {
        "symbol": symbol,
        "method": f"PP{slot.method}",
        "start": str(pd.Timestamp(start).date()),
        "end": str(pd.Timestamp(end).date()),
        "trades": len(tr),
        "win_rate_pct": round(float((profits > 0).mean() * 100), 1) if tr else 0.0,
        "final_capital": round(slot.balance, 2),
        "return_pct": round((slot.balance / capital - 1) * 100, 2),
        "max_drawdown_pct": round(float(dd), 2),
        "profit_factor": round(float(gains / losses), 2) if losses > 0 else None,
        "liquidations": int(reasons.get("LIQUIDATION", 0)),
        "exit_reasons": "; ".join(f"{k}={v}" for k, v in sorted(reasons.items())),
    }


def monthly_returns(symbol, slot: SlotSim, capital):
    """% lời/lỗ từng tháng (theo vốn đầu tháng, tính lệnh đóng trong tháng)."""
    rows = []
    bal = capital
    by_month = {}
    for t in slot.trades:
        m = pd.Timestamp(t["exit_time"]).strftime("%Y-%m")
        by_month.setdefault(m, []).append(t)
    for m in sorted(by_month):
        start_bal = bal
        for t in by_month[m]:
            bal = t["capital_after"]
        rows.append({
            "symbol": symbol, "method": f"PP{slot.method}", "month": m,
            "trades": len(by_month[m]),
            "return_pct": round((bal / start_bal - 1) * 100, 2) if start_bal > 0 else None,
        })
    return rows


def _apply_overrides(pairs, quiet=False):
    for kv in pairs or []:
        key, _, val = kv.partition("=")
        key = key.strip().upper()
        if not hasattr(settings, key):
            raise SystemExit(f"--set: không có tham số {key} trong config/settings.py")
        cur = getattr(settings, key)
        if isinstance(cur, bool):
            new = val.strip().lower() in ("1", "true", "yes")
        else:
            new = type(cur)(val)
        setattr(settings, key, new)
        if not quiet:
            print(f"  override {key} = {new}")


def _backtest_one(job):
    """Chạy 1 cặp (trong process riêng). Chỉ đọc cache đã tải, không gửi request nào."""
    from backtest.binance_data import load_1m

    sym, start, end, a = job["symbol"], job["start"], job["end"], job["args"]
    _apply_overrides(a["set"], quiet=True)  # process con import lại settings → áp lại --set
    df_1m = load_1m(sym, start - timedelta(days=a["warmup_days"]), end, offline=True)
    if df_1m.empty:
        return sym, None
    md = MarketData(sym, df_1m, strict=not a["fast"])
    slots = run_symbol(md, start, a["methods"], a["capital"], a["leverage"], a["wallet_pct"], a["lookback_trades"])
    res = {"summaries": [], "months": [], "trades": []}
    for s in slots:
        res["summaries"].append(summarize(sym, s, a["capital"], start, end))
        res["months"] += monthly_returns(sym, s, a["capital"])
        res["trades"] += [{"symbol": sym, **t} for t in s.trades]
    return sym, res


def main(argv=None):
    p = argparse.ArgumentParser(description="Backtest phát lại vòng lặp live (PP1–PP4) trên nhiều cặp coin.")
    p.add_argument("--symbols", nargs="+", default=[settings.SYMBOL], help="Ví dụ: BTCUSDT ETHUSDT SOLUSDT (mặc định: SYMBOL trong .env)")
    p.add_argument("--start", default=None, help="YYYY-MM-DD (mặc định: 365 ngày trước)")
    p.add_argument("--end", default=None, help="YYYY-MM-DD, không gồm ngày này (mặc định: hôm nay)")
    p.add_argument("--methods", nargs="+", default=list(ALL_METHODS), choices=list(ALL_METHODS))
    p.add_argument("--capital", type=float, default=settings.CAPITAL_START)
    p.add_argument("--leverage", type=float, default=settings.LEVERAGE)
    p.add_argument("--wallet-pct", type=float, default=settings.WALLET_PCT)
    p.add_argument("--lookback-trades", type=int, default=getattr(settings, "LOOKBACK_TRADES", 15))
    p.add_argument("--set", nargs="*", metavar="KEY=VALUE", help="Ghi đè tham số settings, vd M4_MAX_STOP_CAPITAL_PCT=0.08")
    p.add_argument("--warmup-days", type=int, default=60, help="Số ngày dữ liệu tải thêm trước --start để làm nóng chỉ báo")
    p.add_argument("--source", choices=["api", "vision"], default="api",
                   help="api = API Futures công khai fapi.binance.com (mặc định); vision = file zip data.binance.vision (nhanh hơn)")
    p.add_argument("--workers", type=int, default=None, help="Số cặp backtest song song (mặc định: số nhân CPU - 1)")
    p.add_argument("--download-workers", type=int, default=3, help="Số luồng tải dữ liệu (dùng chung giới hạn weight)")
    p.add_argument("--max-weight", type=int, default=1200, help="Weight API tối đa mỗi phút (Binance cho 2400/IP)")
    p.add_argument("--fast", action="store_true", help="Tính chỉ báo 1 lần trên toàn chuỗi (nhanh ~4 lần, kết quả như strict)")
    p.add_argument("--out", default=None, help="Thư mục kết quả (mặc định backtest/results/<thời điểm chạy>)")
    a = p.parse_args(argv)

    import os
    from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
    from backtest import binance_data

    _apply_overrides(a.set)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else today
    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc) if a.start else end - timedelta(days=365)
    symbols = list(dict.fromkeys(s.upper() for s in a.symbols))
    out = Path(a.out) if a.out else ROOT / "backtest" / "results" / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    # 1) Tải dữ liệu: nhiều luồng nhưng chung một bộ giới hạn weight → không bị 429/418
    binance_data.LIMITER.max_weight = a.max_weight
    print(f"Tải dữ liệu 1m {start.date()} → {end.date()} (+{a.warmup_days} ngày warm-up) cho {len(symbols)} cặp...")
    with ThreadPoolExecutor(max_workers=max(1, a.download_workers)) as ex:
        futs = {ex.submit(binance_data.download, sym, start - timedelta(days=a.warmup_days), end, print, a.source): sym
                for sym in symbols}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:
                print(f"  {futs[f]}: lỗi tải dữ liệu ({e}), bỏ qua cặp này")

    # 2) Backtest song song theo cặp, mỗi cặp đi tuần tự từng phút theo thời gian
    workers = a.workers or max(1, (os.cpu_count() or 2) - 1)
    mode = "nhanh (--fast)" if a.fast else "strict: chỉ dùng nến đã đóng tại từng thời điểm"
    print(f"Backtest {', '.join('PP' + m for m in a.methods)} | {workers} process | chế độ {mode}")
    args = {k: getattr(a, k) for k in ("set", "warmup_days", "fast", "methods", "capital", "leverage", "wallet_pct", "lookback_trades")}
    jobs = [{"symbol": s, "start": start, "end": end, "args": args} for s in symbols]
    summaries, all_trades, months = [], [], []
    with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as ex:
        for f in as_completed([ex.submit(_backtest_one, j) for j in jobs]):
            sym, res = f.result()
            if res is None:
                print(f"  {sym}: không có dữ liệu, bỏ qua.")
                continue
            print(f"  {sym}: xong ({sum(x['trades'] for x in res['summaries'])} lệnh)")
            summaries += res["summaries"]
            months += res["months"]
            all_trades += res["trades"]

    if not summaries:
        print("Không có kết quả.")
        return 1
    df_sum = pd.DataFrame(summaries).sort_values("return_pct", ascending=False)
    df_sum.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    df_tr = pd.DataFrame(all_trades)
    num = df_tr.select_dtypes("number").columns
    df_tr[num] = df_tr[num].round(6)
    df_tr.to_csv(out / "trades.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(months).to_csv(out / "monthly.csv", index=False, encoding="utf-8-sig")

    print("\n" + df_sum.drop(columns=["exit_reasons"]).to_string(index=False))
    print(f"\nKết quả: {out}  (summary.csv, trades.csv, monthly.csv)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
