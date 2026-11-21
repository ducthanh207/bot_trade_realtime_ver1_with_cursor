# -*- coding: utf-8 -*-
"""
Một bước chiến lược cho MỘT slot (một phương pháp trên một cặp coin) — dùng chung cho
paper trade (bot/paper_loop.py) và trade thật (live/engine.py).

Tách nguyên văn từ thân vòng `for slot_id, method, api in ...` của paper_loop, để paper và
live chạy cùng một logic vào/ra lệnh. Khác biệt duy nhất nằm ở các hook trong `api`:

- execute_open(payload)  -> {"payload": dict, "fee_in": float} hoặc None (bỏ qua lệnh).
  Paper: không có hook, phí vào tính theo TAKER_FEE.  Live: đặt lệnh thật, trả giá khớp thật.
- execute_close(open_trade, best) -> {"exit_price", "profit", "exit_time"?, "exit_reason"?, "extra"?}
  hoặc None (đóng thất bại, giữ lệnh, thử lại vòng sau).
- on_opened(open_trade), on_closed(closed): lưu file + thông báo Telegram.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pandas as pd

from config import settings
from bot.paper_fees import linear_taker_fee_usdt
from strategy import (
    add_indicators,
    long_entry,
    short_entry,
    size_and_margin,
    atr_1h_at_entry,
    compute_exit_candidates,
    pick_best_exit,
)
from strategy.indicators import add_indicators_m3
from strategy.risk import m3_atr_multiplier
from strategy.pct_change_avg import build_pct_change_avg_bands_series
from strategy.regime import classify_regime
from strategy.daily_cycle import daily_cycle_info
from strategy.cvd import has_taker, last_ratio, resample_4h
# [2026-11-21] Mỗi phương pháp là một "đĩa" (strategy/disks.py): khung pp1..pp4 + các khối bật thêm.
# Quyết định vào lệnh dùng chung với backtest: strategy/entry_engine.py.
from strategy.disks import get_disk
from strategy.entry_engine import plan_entry, apply_entry_extras

_tz_app = getattr(settings, "GMT7", timezone.utc)

FOUR_H_BOUNDARY_HOURS = (3, 7, 11, 15, 19, 23)
FOUR_H_BOUNDARY_WINDOW_MINUTES = 5


def is_4h_boundary_window(now=None) -> bool:
    now = now or datetime.now(_tz_app)
    return now.hour in FOUR_H_BOUNDARY_HOURS and now.minute < FOUR_H_BOUNDARY_WINDOW_MINUTES


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def _f(v):
    try:
        x = float(v)
        return x if pd.notna(x) else None
    except (TypeError, ValueError):
        return None


def as_aware_utc(v):
    """Chuyển entry_time (datetime hoặc ISO string) về datetime có tzinfo; None nếu không parse được."""
    if v is None:
        return None
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not hasattr(v, "tzinfo"):
        return None
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v


def update_circuit_breaker(cb: dict, pnl: float, balance: float):
    """Cập nhật circuit breaker (Method 3/4) sau khi đóng lệnh. Ngưỡng dùng chung M3_*."""
    if not cb:
        return
    now = datetime.now(timezone.utc)
    if pnl < 0:
        losses = cb["get_losses"]() + 1
    else:
        losses = 0
    cb["set_losses"](losses)

    # Circuit breaker theo chuỗi thua
    if losses >= settings.M3_CB_HEAVY_STREAK:
        cb["set_heavy"](now + timedelta(hours=settings.M3_CB_HEAVY_BARS * 4))
        cb["set_light"](None)
    elif losses >= settings.M3_CB_LIGHT_STREAK:
        cb["set_light"](now + timedelta(hours=settings.M3_CB_LIGHT_BARS * 4))

    # Heavy: drawdown check over M3_CB_HEAVY_DD_DAYS days
    try:
        cutoff = now - timedelta(days=settings.M3_CB_HEAVY_DD_DAYS)
        recent = []
        for t in cb["get_trades"]():
            et = as_aware_utc(t.get("entry_time"))
            if et is not None and et >= cutoff:
                recent.append(t)
        if recent:
            peak = max(float(t.get("capital_after", 0) or 0) for t in recent)
            if peak > 0 and balance > 0:
                dd_pct = (peak - balance) / peak * 100
                if dd_pct >= settings.M3_CB_HEAVY_DD_PCT:
                    cb["set_heavy"](now + timedelta(hours=settings.M3_CB_HEAVY_BARS * 4))
    except Exception:
        pass


class MarketContext:
    """Dữ liệu một cặp coin tại một vòng lặp (nến 4H/1H/1m đã tải + indicator)."""

    def __init__(self, df_4h_raw, df_1m, df_1h, in_4h_window: bool, df_1d=None):
        self.df_4h_raw = df_4h_raw
        # [2026-11-07] nến 1D cho PP5 (có thể gồm nến ngày đang chạy — daily_info() tự bỏ). None → PP5 không vào lệnh.
        self.df_1d = df_1d
        self.df_1m = df_1m
        self.df_1h = df_1h
        self.df_4h = add_indicators(df_4h_raw)
        self.in_4h_window = in_4h_window
        self._row_m3 = None
        self._row_m3_done = False
        self._df_4h_m3_closed = None  # [2026-11-01] nến 4H đã đóng + indicator M3, dùng cho classify_regime
        self._regime = {}
        self._cvd = {}
        self._daily = {}

    @property
    def ok(self) -> bool:
        return not self.df_4h.empty and len(self.df_4h) >= 3

    @property
    def row(self):
        return _ensure_series(self.df_4h.iloc[-1])

    @property
    def row_closed(self):
        return _ensure_series(self.df_4h.iloc[-2])

    @property
    def prev_row_closed(self):
        return _ensure_series(self.df_4h.iloc[-3])

    @property
    def ts_4h(self):
        return self.df_4h.index[-1]

    def last_price(self) -> float:
        if not self.df_1m.empty:
            return float(self.df_1m["close"].iloc[-1])
        return float(self.row["close"])

    def row_m3(self):
        """Indicator mở rộng (ADX/EMA_TREND/swing) cho PP3/PP4 — tính một lần mỗi vòng."""
        if not self._row_m3_done:
            self._row_m3_done = True
            try:
                df_4h_m3 = add_indicators_m3(
                    self.df_4h_raw,
                    ema_trend_len=getattr(settings, "M3_EMA_TREND_LEN", 50),
                    swing_lookback=getattr(settings, "M3_SWING_LOOKBACK", 6),
                )
                self._row_m3 = _ensure_series(df_4h_m3.iloc[-2]) if len(df_4h_m3) >= 2 else None
                self._df_4h_m3_closed = df_4h_m3.iloc[:-1]  # bỏ nến 4H đang chạy
            except Exception:
                self._row_m3 = None
        return self._row_m3

    def daily_info(self) -> dict:
        """[2026-11-07] Chu kỳ nến ngày cho PP5 — chỉ dùng nến 1D đã đóng, tính một lần mỗi vòng."""
        key = settings.override_signature()  # tham số riêng của đĩa (nếu có) → bộ nhớ đệm riêng
        if key not in self._daily:
            df = self.df_1d
            if df is not None and not df.empty:
                now = self.df_1m.index[-1] if self.df_1m is not None and not self.df_1m.empty else self.ts_4h
                df = df[df.index + pd.Timedelta(days=1) <= pd.Timestamp(now)]
            self._daily[key] = daily_cycle_info(df)
        return self._daily[key]

    def cvd_info(self) -> dict:
        """[2026-11-14] Độ dốc CVD (PP6/PP6.1) trên nến 4H/1H đã đóng; cần cột taker_buy, thiếu → giá trị None."""
        key = settings.override_signature()
        if key not in self._cvd:
            r4 = r1 = rs = None
            closed_4h = self.df_4h_raw.iloc[:-1] if has_taker(self.df_4h_raw) else None
            if closed_4h is None and has_taker(self.df_1h):
                closed_4h = resample_4h(self.df_1h.iloc[:-1])
            if closed_4h is not None:
                r4 = last_ratio(closed_4h, settings.M6_4H_BARS)
                rs = last_ratio(closed_4h, settings.M61_SIDE_CVD_BARS)
            if has_taker(self.df_1h):
                r1 = last_ratio(self.df_1h.iloc[:-1], settings.M6_1H_BARS)
            self._cvd[key] = {"r4": r4, "r1": r1, "r_side": rs}
        return self._cvd[key]

    def regime_info(self) -> dict:
        """[2026-11-01] Giai đoạn thị trường (UP/DOWN/RANGE) trên nến 4H đã đóng — tính một lần mỗi vòng."""
        key = settings.override_signature()
        if key not in self._regime:
            self.row_m3()
            self._regime[key] = classify_regime(self._df_4h_m3_closed)
        return self._regime[key]

    def ema_ref(self):
        """[2026-11-21] PP7: EMA50 của M7_TREND_SLOPE_BARS nến 4H trước nến vừa đóng (None nếu tắt / thiếu)."""
        n = int(getattr(settings, "M7_TREND_SLOPE_BARS", 0) or 0)
        self.row_m3()
        m3 = self._df_4h_m3_closed
        if n <= 0 or m3 is None or "EMA_TREND" not in m3 or len(m3) <= n:
            return None
        return _f(m3["EMA_TREND"].iloc[-1 - n])


def step_slot(slot_id, method: str, api: dict, mkt: MarketContext):
    """
    Chạy một bước cho slot: xét thoát lệnh đang mở, rồi (nếu không có lệnh) xét vào lệnh.
    Trả "closed" / "opened" / None. Tham số riêng của đĩa (nếu có) chỉ có hiệu lực trong bước này.
    """
    disk = get_disk(method)
    with disk.applied():
        return _step_slot(slot_id, method, disk, api, mkt)


def _step_slot(slot_id, method: str, disk, api: dict, mkt: MarketContext):
    st = api["get_status"]()
    if st == "stopped":
        return None

    df_4h = mkt.df_4h
    df_4h_raw = mkt.df_4h_raw
    df_1m = mkt.df_1m
    df_1h = mkt.df_1h
    row = mkt.row
    row_closed = mkt.row_closed
    prev_row_closed = mkt.prev_row_closed
    ts_4h = mkt.ts_4h
    in_4h_window = mkt.in_4h_window
    cb = api.get("cb")

    lb_trades = api["lookback"]()
    balance = api["get_balance"]()
    open_trade = api["get_open"]()

    if open_trade:
        entry = float(open_trade["entry_price"])
        side = open_trade["side"]

        exit_px_ref = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])
        exit_time_ts = df_1m.index[-1] if not df_1m.empty else ts_4h

        row_closed_ts = df_4h.index[-2]
        entry_4h_ts_val = open_trade.get("entry_4h_ts")
        if entry_4h_ts_val is not None:
            try:
                entry_4h_ts_val = pd.Timestamp(entry_4h_ts_val)
            except Exception:
                entry_4h_ts_val = None
        allow_early_exit = entry_4h_ts_val is None or row_closed_ts != entry_4h_ts_val

        candidates = compute_exit_candidates(
            open_trade,
            df_1m,
            df_1h,
            df_4h_raw,
            prev_row_closed,
            row_closed,
            exit_px_ref,
            exit_time_ts,
            paper_use_4h_window=True,
            in_4h_window=in_4h_window,
            method=method,
            lookback_trades=lb_trades,
            allow_early_exit=allow_early_exit,
        )
        open_trade["last_sl_check"] = df_1m.index[-1] if not df_1m.empty else ts_4h

        best = pick_best_exit(candidates)
        if best is not None:
            best_time, best_pnl, best_px, reason = best
            extra = {}
            exec_close = api.get("execute_close")
            if exec_close is not None:
                fill = exec_close(open_trade, best)
                if fill is None:
                    return None  # đóng thất bại: giữ lệnh, vòng sau thử lại
                best_time = fill.get("exit_time", best_time)
                best_pnl = float(fill["profit"])
                best_px = float(fill["exit_price"])
                reason = fill.get("exit_reason", reason)
                extra = fill.get("extra") or {}
            capital_after = balance + best_pnl

            margin = open_trade.get("margin")
            closed = {
                "entry_time": open_trade.get("entry_time"),
                "exit_time": best_time,
                "entry_price": entry,
                "exit_price": best_px,
                "side": side,
                "size": open_trade.get("size"),
                "margin": margin,
                "profit": best_pnl,
                "capital_before": balance,
                "capital_after": capital_after,
                "exit_reason": reason,
                "entry_rsi": open_trade.get("entry_rsi"),
                "entry_ema_rsi": open_trade.get("entry_ema_rsi"),
                "entry_wma_rsi": open_trade.get("entry_wma_rsi"),
                "exit_rsi": _f(row_closed.get("RSI")),
                "exit_ema_rsi": _f(row_closed.get("EMA_RSI")),
                "exit_wma_rsi": _f(row_closed.get("WMA_RSI")),
                "paper_slot": slot_id,
            }
            closed.update(extra)
            api["set_open"](None)
            api["set_last"](closed)
            api["append_trade"](closed)
            api["set_balance"](capital_after)
            if cb and disk.m3:
                try:
                    update_circuit_breaker(cb, best_pnl, capital_after)
                except Exception:
                    pass
            on_closed = api.get("on_closed")
            if on_closed is not None:
                on_closed(closed)
            return "closed"

    open_trade = api["get_open"]()
    if open_trade or st != "running" or not in_4h_window:
        return None

    # Khung PP3/PP4: circuit breaker trước mọi lệnh
    if disk.m3:
        cbd = cb or {}
        now_utc = datetime.now(timezone.utc)
        heavy_until = cbd.get("get_heavy", lambda: None)()
        light_until = cbd.get("get_light", lambda: None)()
        if heavy_until and now_utc < heavy_until:
            return None
        if light_until and now_utc < light_until:
            return None

    entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row_closed["close"])
    entry_time_now = datetime.now(_tz_app)
    plan = plan_entry(
        disk, prev_row_closed=prev_row_closed, row_closed=row_closed, get_row_m3=mkt.row_m3, df_1h=df_1h,
        get_regime=mkt.regime_info, get_daily=mkt.daily_info, get_cvd=mkt.cvd_info, get_ema_ref=mkt.ema_ref,
        losses=(cb or {}).get("get_losses", lambda: 0)(), balance=balance, entry_px=entry_px,
        leverage=api["get_lev"](), wallet_pct=api["get_wct"](),
        m3_grace_mult=m3_atr_multiplier(entry_time_now) if disk.pp3_only else 0.0,
    )
    if plan is None:
        return None
    side, size = plan["side"], plan["size"]
    margin, notional, atr_now, init_stop = plan["margin"], plan["notional"], plan["atr"], plan["init_stop"]

    entry_4h_ts = df_4h.index[-2]
    open_payload = {
        "side": side,
        "entry_time": entry_time_now,
        "entry_price": entry_px,
        "size": size,
        "margin": margin,
        "capital_before": balance,
        "atr": atr_now,
        "notional": notional,
        "trail_stop": init_stop,
        "last_sl_check": df_1m.index[-1] if not df_1m.empty else ts_4h,
        "entry_rsi": _f(row_closed.get("RSI")),
        "entry_ema_rsi": _f(row_closed.get("EMA_RSI")),
        "entry_wma_rsi": _f(row_closed.get("WMA_RSI")),
        "entry_4h_ts": entry_4h_ts,
        "trading_method": method,
        "paper_slot": slot_id,
    }
    apply_entry_extras(disk, open_payload, plan, row_closed)
    # Chỉ phương pháp dùng %change (PP2) mới snapshot dải — PP1/PP3 không đụng pct_change
    if disk.pp2:
        bands_at_entry = build_pct_change_avg_bands_series(df_4h_raw, lookback_trades=lb_trades)
        open_payload["pct_half_width_pct"] = bands_at_entry.get("band_half_width_pct")
        open_payload["pct_upper_at_entry"] = bands_at_entry.get("upper")
        open_payload["pct_lower_at_entry"] = bands_at_entry.get("lower")

    exec_open = api.get("execute_open")
    if exec_open is not None:
        res = exec_open(open_payload)
        if res is None:
            return None
        open_payload = res["payload"]
        fee_in = float(res["fee_in"])
    else:
        fee_in = linear_taker_fee_usdt(size, entry_px, float(settings.TAKER_FEE))
    balance_after_fee = balance - fee_in

    api["set_open"](open_payload)
    api["set_balance"](balance_after_fee)
    on_opened = api.get("on_opened")
    if on_opened is not None:
        on_opened(api["get_open"]())
    return "opened"
