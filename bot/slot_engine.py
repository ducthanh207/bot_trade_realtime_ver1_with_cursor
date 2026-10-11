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
from strategy.strategies.registry import uses_pct_change_bands, METHOD_3, METHOD_4
from strategy.indicators import add_indicators_m3
from strategy.risk import m3_adx_zone, m3_streak_multiplier, m3_atr_multiplier, m4_adx_zone
from strategy.signals import m4_entry_1h_confirm, m4_entry_rsi_extreme_block
from strategy.pct_change_avg import build_pct_change_avg_bands_series

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

    def __init__(self, df_4h_raw, df_1m, df_1h, in_4h_window: bool):
        self.df_4h_raw = df_4h_raw
        self.df_1m = df_1m
        self.df_1h = df_1h
        self.df_4h = add_indicators(df_4h_raw)
        self.in_4h_window = in_4h_window
        self._row_m3 = None
        self._row_m3_done = False

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
            except Exception:
                self._row_m3 = None
        return self._row_m3


def step_slot(slot_id, method: str, api: dict, mkt: MarketContext):
    """
    Chạy một bước cho slot: xét thoát lệnh đang mở, rồi (nếu không có lệnh) xét vào lệnh.
    Trả "closed" / "opened" / None.
    """
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
            if cb and method in (METHOD_3, METHOD_4):
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

    # Method 3/4: check circuit breaker before any entry
    if method in (METHOD_3, METHOD_4):
        cbd = cb or {}
        now_utc = datetime.now(timezone.utc)
        heavy_until = cbd.get("get_heavy", lambda: None)()
        light_until = cbd.get("get_light", lambda: None)()
        if heavy_until and now_utc < heavy_until:
            return None
        if light_until and now_utc < light_until:
            return None

    # For Method 3/4, use extended indicators with ADX/EMA_TREND/swing
    row_m3 = mkt.row_m3() if method in (METHOD_3, METHOD_4) else None

    sig_long = long_entry(prev_row_closed, row_closed)
    sig_short = short_entry(prev_row_closed, row_closed)
    if not (sig_long or sig_short):
        return None
    side = "LONG" if sig_long else "SHORT"

    # Method 4 entry filters: chặn RSI extreme + cần xác nhận hướng RSI 1H
    if method == METHOD_4:
        if m4_entry_rsi_extreme_block(side, row_closed.get("RSI")):
            return None
        if getattr(settings, "M4_REQUIRE_1H_CONFIRM", True) and not m4_entry_1h_confirm(side, df_1h):
            return None

    # Method 3/4 entry filters
    m3_size_mult = 1.0
    if method in (METHOD_3, METHOD_4) and row_m3 is not None:
        # ADX zone filter (M4 thêm exhaustion: ADX quá cao → giảm size)
        adx_val = float(row_m3.get("ADX", 25.0) or 25.0)
        if method == METHOD_4:
            allow, adx_size_mult = m4_adx_zone(adx_val)
        else:
            allow, adx_size_mult = m3_adx_zone(adx_val)
        if not allow:
            return None
        m3_size_mult = adx_size_mult

        # EMA trend filter (only when ADX > M3_EMA_TREND_ADX_ABOVE)
        ema_trend_adx_thresh = getattr(settings, "M3_EMA_TREND_ADX_ABOVE", 30.0)
        if adx_val > ema_trend_adx_thresh:
            ema_trend_val = float(row_m3.get("EMA_TREND", 0.0) or 0.0)
            close_val = float(row_m3.get("close", 0.0) or 0.0)
            if ema_trend_val > 0 and close_val > 0:
                if side == "LONG" and close_val < ema_trend_val:
                    return None
                if side == "SHORT" and close_val > ema_trend_val:
                    return None

        # Swing structure size adjustment
        disagree_size = getattr(settings, "M3_SWING_DISAGREE_SIZE", 0.6)
        higher_low = bool(row_m3.get("higher_low", False))
        lower_high = bool(row_m3.get("lower_high", False))
        if side == "LONG" and lower_high and not higher_low:
            m3_size_mult = min(m3_size_mult, disagree_size)
        elif side == "SHORT" and higher_low and not lower_high:
            m3_size_mult = min(m3_size_mult, disagree_size)

        # Streak multiplier
        streak_mult = m3_streak_multiplier((cb or {}).get("get_losses", lambda: 0)())
        m3_size_mult = m3_size_mult * streak_mult

    entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row_closed["close"])
    lev = api["get_lev"]()
    wct = api["get_wct"]()
    size, margin, notional = size_and_margin(balance, entry_px, leverage=lev, wallet_pct=wct)
    if method in (METHOD_3, METHOD_4) and m3_size_mult < 1.0:
        size = size * m3_size_mult
        margin = margin * m3_size_mult
        notional = notional * m3_size_mult
    if size <= 0 or margin > balance:
        return None

    # ATR multiplier (Method 3/4 dùng grace lúc mở; M4 tự siết sau M4_ATR_GRACE_HOURS trong check_atr_trailing)
    atr_now = atr_1h_at_entry(df_1h, float(row_closed["ATR"]))
    entry_time_now = datetime.now(_tz_app)
    if method == METHOD_3:
        atr_mult_now = m3_atr_multiplier(entry_time_now)
    elif method == METHOD_4:
        atr_mult_now = settings.M4_ATR_MULTIPLIER_GRACE
    else:
        atr_mult_now = settings.ATR_MULTIPLIER
    trail_dist = atr_now * atr_mult_now
    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist

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
    if method == METHOD_3:
        open_payload["atr_multiplier_override"] = atr_mult_now
    elif method == METHOD_4:
        open_payload["atr_multiplier_override"] = atr_mult_now
        open_payload["max_stop_capital_pct"] = settings.M4_MAX_STOP_CAPITAL_PCT
    # Chỉ phương pháp dùng %change (PP2) mới snapshot dải — PP1/PP3 không đụng pct_change
    if uses_pct_change_bands(method):
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
