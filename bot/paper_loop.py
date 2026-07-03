# -*- coding: utf-8 -*-
"""
Vòng lặp paper trade: ba slot song song — Paper 1/2/3.
Dùng giá thật từ Binance (klines); chỉ cập nhật state, không gọi sàn.
Slot stopped: bỏ qua; paused: vẫn thoát lệnh, không mở mới.
"""

import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from config import settings as _settings

_tz_app = getattr(_settings, "GMT7", timezone.utc)

from config import settings
from bot.paper_fees import linear_taker_fee_usdt
from exchange.binance_client import BinanceClient
from strategy import (
    add_indicators,
    long_entry,
    short_entry,
    size_and_margin,
    atr_1h_at_entry,
    compute_exit_candidates,
    pick_best_exit,
)
from strategy.strategies.paper_slots import method_for_paper_slot
from strategy.strategies.registry import uses_pct_change_bands, METHOD_3, METHOD_4
from strategy.indicators import add_indicators_m3
from strategy.risk import m3_adx_zone, m3_streak_multiplier, m3_atr_multiplier, m4_adx_zone
from strategy.signals import m4_entry_1h_confirm, m4_entry_rsi_extreme_block
from strategy.pct_change_avg import build_pct_change_avg_bands_series
import bot.state as state


MIN_KLINES_4H = 80
MIN_KLINES_1M = 80
WARMUP_RETRIES = 5
WARMUP_SLEEP_SEC = 2

FOUR_H_BOUNDARY_HOURS = (3, 7, 11, 15, 19, 23)
FOUR_H_BOUNDARY_WINDOW_MINUTES = 5


def _pct_lookback_trades_for_slot(slot_id: int) -> int:
    """
    Lookback cho %change = số lệnh đã đóng trong cửa sổ (không phải số nến).
    Paper 2: dùng tùy chỉnh hoặc config; Paper 1: luôn config (PP1 không dùng pct trong loop).
    """
    if int(slot_id) == 2:
        v = state.get_paper2_lookback_trades()
        if v is not None:
            return min(max(int(v), 1), 200)
    return min(max(int(getattr(settings, "LOOKBACK_TRADES", 15)), 1), 200)


def _is_4h_boundary_window() -> bool:
    now = datetime.now(_tz_app)
    return now.hour in FOUR_H_BOUNDARY_HOURS and now.minute < FOUR_H_BOUNDARY_WINDOW_MINUTES


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def _paper_slot_configs():
    """
    Mỗi slot → state + method lấy từ paper_slots.method_for_paper_slot (mở rộng sau tại đó).
    """
    apis = [
        (
            1,
            {
                "get_status": state.get_paper_status,
                "get_balance": state.get_paper_balance,
                "set_balance": state.set_paper_balance,
                "get_open": state.get_paper_open_trade,
                "set_open": state.set_paper_open_trade,
                "append_trade": state.append_paper_trade,
                "set_last": state.set_paper_last_trade,
                "get_lev": state.get_paper_leverage,
                "get_wct": state.get_paper_wallet_pct,
            },
        ),
        (
            2,
            {
                "get_status": state.get_paper2_status,
                "get_balance": state.get_paper2_balance,
                "set_balance": state.set_paper2_balance,
                "get_open": state.get_paper2_open_trade,
                "set_open": state.set_paper2_open_trade,
                "append_trade": state.append_paper2_trade,
                "set_last": state.set_paper2_last_trade,
                "get_lev": state.get_paper2_leverage,
                "get_wct": state.get_paper2_wallet_pct,
            },
        ),
        (
            3,
            {
                "get_status": state.get_paper3_status,
                "get_balance": state.get_paper3_balance,
                "set_balance": state.set_paper3_balance,
                "get_open": state.get_paper3_open_trade,
                "set_open": state.set_paper3_open_trade,
                "append_trade": state.append_paper3_trade,
                "set_last": state.set_paper3_last_trade,
                "get_lev": state.get_paper3_leverage,
                "get_wct": state.get_paper3_wallet_pct,
            },
        ),
        (
            4,
            {
                "get_status": state.get_paper4_status,
                "get_balance": state.get_paper4_balance,
                "set_balance": state.set_paper4_balance,
                "get_open": state.get_paper4_open_trade,
                "set_open": state.set_paper4_open_trade,
                "append_trade": state.append_paper4_trade,
                "set_last": state.set_paper4_last_trade,
                "get_lev": state.get_paper4_leverage,
                "get_wct": state.get_paper4_wallet_pct,
            },
        ),
    ]
    return [(sid, method_for_paper_slot(sid), api) for sid, api in apis]


def _as_aware_utc(v):
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


# Circuit breaker state accessors theo slot (slot 3 = Method 3, slot 4 = Method 4; ngưỡng dùng chung M3_*)
_CB_SLOT_API = {
    3: {
        "get_losses": lambda: state.get_paper3_consecutive_losses(),
        "set_losses": lambda v: state.set_paper3_consecutive_losses(v),
        "get_light": lambda: state.get_paper3_cb_light_until(),
        "set_light": lambda dt: state.set_paper3_cb_light_until(dt),
        "get_heavy": lambda: state.get_paper3_cb_heavy_until(),
        "set_heavy": lambda dt: state.set_paper3_cb_heavy_until(dt),
        "get_trades": lambda: state.get_paper3_trades(),
    },
    4: {
        "get_losses": lambda: state.get_paper4_consecutive_losses(),
        "set_losses": lambda v: state.set_paper4_consecutive_losses(v),
        "get_light": lambda: state.get_paper4_cb_light_until(),
        "set_light": lambda dt: state.set_paper4_cb_light_until(dt),
        "get_heavy": lambda: state.get_paper4_cb_heavy_until(),
        "set_heavy": lambda dt: state.set_paper4_cb_heavy_until(dt),
        "get_trades": lambda: state.get_paper4_trades(),
    },
}


def _update_slot_circuit_breaker(slot_id: int, pnl: float, balance: float, closed_trade: dict):
    """Cap nhat circuit breaker (Method 3/4) sau khi dong lenh."""
    cb = _CB_SLOT_API.get(int(slot_id))
    if cb is None:
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
            et = _as_aware_utc(t.get("entry_time"))
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


def warm_up_klines(client: BinanceClient, symbol: str, notify_func=None) -> bool:
    for attempt in range(1, WARMUP_RETRIES + 1):
        try:
            if not client.is_connected():
                try:
                    from telegram.notifier import notify_error
                    notify_error("Warm-up: không kết nối Binance.", context="binance")
                except Exception:
                    pass
                if notify_func:
                    notify_func("[PAPER] Warm-up: không kết nối Binance.")
                time.sleep(WARMUP_SLEEP_SEC)
                continue
            df_4h_raw = client.get_klines_4h(symbol, limit=150)
            df_1m_raw = client.get_klines_1m(symbol, limit=150)
            if df_4h_raw.empty or len(df_4h_raw) < MIN_KLINES_4H:
                if notify_func:
                    notify_func(f"[PAPER] Warm-up: chưa đủ nến 4h (cần >= {MIN_KLINES_4H}), thử lần {attempt}/{WARMUP_RETRIES}.")
                time.sleep(WARMUP_SLEEP_SEC)
                continue
            df_4h = add_indicators(df_4h_raw)
            if df_4h.empty or len(df_4h) < 2:
                if notify_func:
                    notify_func(f"[PAPER] Warm-up: sau khi tính indicator không đủ dữ liệu, thử lần {attempt}/{WARMUP_RETRIES}.")
                time.sleep(WARMUP_SLEEP_SEC)
                continue
            if notify_func:
                notify_func("[PAPER] Warm-up OK: đã có đủ nến 4h/1m để tính indicator, bắt đầu vòng lặp.")
            return True
        except Exception as e:
            if notify_func:
                notify_func(f"[PAPER] Warm-up lỗi (lần {attempt}/{WARMUP_RETRIES}): {e}")
            time.sleep(WARMUP_SLEEP_SEC)
    return False


def run_paper_loop(client: BinanceClient, notify_func=None, status_func=None):
    state.set_bot_started_at()
    symbol = settings.SYMBOL
    warm_up_klines(client, symbol, notify_func)

    last_status_min = None
    last_hourly_status = None
    while True:
        try:
            if (state.get_paper_status() == "stopped" and state.get_paper2_status() == "stopped"
                    and state.get_paper3_status() == "stopped" and state.get_paper4_status() == "stopped"):
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            if not client.is_connected():
                df_4h_raw = pd.DataFrame()
                df_1m = pd.DataFrame()
            else:
                df_4h_raw = client.get_klines_4h(symbol, limit=200)
                df_1m = client.get_klines_1m(symbol, limit=500)

            df_1h = pd.DataFrame()
            if client.is_connected():
                try:
                    df_1h_raw = client.get_klines_1h(symbol, limit=200)
                    if not df_1h_raw.empty:
                        df_1h = add_indicators(df_1h_raw)
                except Exception:
                    df_1h = pd.DataFrame()

            if df_4h_raw.empty or len(df_4h_raw) < 20:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            df_4h = add_indicators(df_4h_raw)
            if df_4h.empty or len(df_4h) < 3:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            row = _ensure_series(df_4h.iloc[-1])
            prev_row = _ensure_series(df_4h.iloc[-2])
            row_closed = _ensure_series(df_4h.iloc[-2])
            prev_row_closed = _ensure_series(df_4h.iloc[-3])
            ts_4h = df_4h.index[-1]
            in_4h_window = _is_4h_boundary_window()

            for slot_id, method, api in _paper_slot_configs():
                st = api["get_status"]()
                if st == "stopped":
                    continue

                lb_trades = _pct_lookback_trades_for_slot(slot_id)
                balance = api["get_balance"]()
                open_trade = api["get_open"]()

                if open_trade:
                    entry = float(open_trade["entry_price"])
                    size = float(open_trade["size"])
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
                        capital_after = balance + best_pnl

                        def _f(v):
                            try:
                                x = float(v)
                                return x if pd.notna(x) else None
                            except (TypeError, ValueError):
                                return None

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
                        api["set_open"](None)
                        api["set_last"](closed)
                        api["append_trade"](closed)
                        api["set_balance"](capital_after)
                        if slot_id in (3, 4):
                            try:
                                _update_slot_circuit_breaker(slot_id, best_pnl, capital_after, closed)
                            except Exception:
                                pass
                        try:
                            from bot.paper_persistence import save_paper_state
                            save_paper_state()
                        except Exception:
                            pass
                        try:
                            from telegram.notifier import notify_trade_closed
                            notify_trade_closed(closed, source="loop", paper_slot=slot_id)
                        except Exception:
                            if notify_func:
                                tag = "[PAPER]" if slot_id == 1 else f"[PAPER{slot_id}]"
                                notify_func(f"{tag} Dong lenh {side} | PnL: {best_pnl:.2f} USDT | Ly do: {reason}")
                        continue

                open_trade = api["get_open"]()
                if not open_trade and st == "running" and in_4h_window:
                    # Method 3/4: check circuit breaker before any entry
                    if method in (METHOD_3, METHOD_4):
                        cb = _CB_SLOT_API.get(slot_id, {})
                        now_utc = datetime.now(timezone.utc)
                        heavy_until = cb.get("get_heavy", lambda: None)()
                        light_until = cb.get("get_light", lambda: None)()
                        if heavy_until and now_utc < heavy_until:
                            continue
                        if light_until and now_utc < light_until:
                            continue

                    # For Method 3/4, use extended indicators with ADX/EMA_TREND/swing
                    if method in (METHOD_3, METHOD_4):
                        try:
                            df_4h_m3 = add_indicators_m3(
                                df_4h_raw,
                                ema_trend_len=getattr(settings, "M3_EMA_TREND_LEN", 50),
                                swing_lookback=getattr(settings, "M3_SWING_LOOKBACK", 6),
                            )
                            row_m3 = _ensure_series(df_4h_m3.iloc[-2]) if len(df_4h_m3) >= 2 else None
                        except Exception:
                            row_m3 = None
                    else:
                        row_m3 = None

                    sig_long = long_entry(prev_row_closed, row_closed)
                    sig_short = short_entry(prev_row_closed, row_closed)
                    if sig_long or sig_short:
                        side = "LONG" if sig_long else "SHORT"

                        # Method 4 entry filters: chặn RSI extreme + cần xác nhận hướng RSI 1H
                        if method == METHOD_4:
                            if m4_entry_rsi_extreme_block(side, row_closed.get("RSI")):
                                continue
                            if getattr(settings, "M4_REQUIRE_1H_CONFIRM", True) and not m4_entry_1h_confirm(side, df_1h):
                                continue

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
                                continue
                            m3_size_mult = adx_size_mult

                            # EMA trend filter (only when ADX > M3_EMA_TREND_ADX_ABOVE)
                            ema_trend_adx_thresh = getattr(settings, "M3_EMA_TREND_ADX_ABOVE", 30.0)
                            if adx_val > ema_trend_adx_thresh:
                                ema_trend_val = float(row_m3.get("EMA_TREND", 0.0) or 0.0)
                                close_val = float(row_m3.get("close", 0.0) or 0.0)
                                if ema_trend_val > 0 and close_val > 0:
                                    if side == "LONG" and close_val < ema_trend_val:
                                        continue
                                    if side == "SHORT" and close_val > ema_trend_val:
                                        continue

                            # Swing structure size adjustment
                            disagree_size = getattr(settings, "M3_SWING_DISAGREE_SIZE", 0.6)
                            higher_low = bool(row_m3.get("higher_low", False))
                            lower_high = bool(row_m3.get("lower_high", False))
                            if side == "LONG" and lower_high and not higher_low:
                                m3_size_mult = min(m3_size_mult, disagree_size)
                            elif side == "SHORT" and higher_low and not lower_high:
                                m3_size_mult = min(m3_size_mult, disagree_size)

                            # Streak multiplier
                            cb = _CB_SLOT_API.get(slot_id, {})
                            streak_mult = m3_streak_multiplier(cb.get("get_losses", lambda: 0)())
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
                            continue
                        fee_in = linear_taker_fee_usdt(size, entry_px, float(settings.TAKER_FEE))
                        balance_after_fee = balance - fee_in

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

                        def _f(v):
                            try:
                                x = float(v)
                                return x if pd.notna(x) else None
                            except (TypeError, ValueError):
                                return None

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
                            bands_at_entry = build_pct_change_avg_bands_series(
                                df_4h_raw, lookback_trades=lb_trades
                            )
                            open_payload["pct_half_width_pct"] = bands_at_entry.get("band_half_width_pct")
                            open_payload["pct_upper_at_entry"] = bands_at_entry.get("upper")
                            open_payload["pct_lower_at_entry"] = bands_at_entry.get("lower")
                        api["set_open"](open_payload)
                        api["set_balance"](balance_after_fee)
                        try:
                            from bot.paper_persistence import save_paper_state
                            save_paper_state()
                        except Exception:
                            pass
                        ot = api["get_open"]()
                        try:
                            from telegram.notifier import notify_trade_opened
                            if ot:
                                notify_trade_opened(ot, source="loop", paper_slot=slot_id)
                        except Exception:
                            if notify_func:
                                tag = "[PAPER]" if slot_id == 1 else f"[PAPER{slot_id}]"
                                notify_func(f"{tag} Mo lenh {side} @ {entry_px:.2f} | Size: {round(size, 3)} BTC")

            now = datetime.now(_tz_app)
            if status_func and last_status_min is not None:
                delta_min = (now - last_status_min).total_seconds() / 60
                if delta_min >= settings.STATUS_INTERVAL_MIN:
                    status_func()
                    last_status_min = now
            elif last_status_min is None:
                last_status_min = now

            if last_hourly_status is not None:
                dh = (now - last_hourly_status).total_seconds() / 60
                if dh >= getattr(settings, "STATUS_HOURLY_INTERVAL_MIN", 60):
                    try:
                        from telegram.notifier import send_status_hourly
                        send_status_hourly()
                    except Exception:
                        pass
                    last_hourly_status = now
            else:
                last_hourly_status = now

        except Exception as e:
            try:
                from telegram.notifier import notify_error
                notify_error(f"Paper loop: {e}", context="app")
            except Exception:
                pass
            if notify_func:
                notify_func(f"[PAPER] ❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(settings.LOOP_INTERVAL_SEC)
