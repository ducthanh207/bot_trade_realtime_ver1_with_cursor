# -*- coding: utf-8 -*-
"""
Vòng lặp paper trade: hai slot song song — Paper (phương pháp 1) và Paper 2 (phương pháp 2).
Dùng giá thật từ Binance (klines); chỉ cập nhật state, không gọi sàn.
Slot stopped: bỏ qua; paused: vẫn thoát lệnh, không mở mới.
"""

import time
import pandas as pd
from datetime import datetime, timezone
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
from strategy.strategies.registry import uses_pct_change_bands
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
    ]
    return [(sid, method_for_paper_slot(sid), api) for sid, api in apis]


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
            if state.get_paper_status() == "stopped" and state.get_paper2_status() == "stopped":
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
                                tag = "[PAPER]" if slot_id == 1 else "[PAPER2]"
                                notify_func(f"{tag} 🔴 Đóng lệnh {side} | PnL: {best_pnl:.2f} USDT | Lý do: {reason}")
                        continue

                open_trade = api["get_open"]()
                if not open_trade and st == "running" and in_4h_window:
                    sig_long = long_entry(prev_row_closed, row_closed)
                    sig_short = short_entry(prev_row_closed, row_closed)
                    if sig_long or sig_short:
                        side = "LONG" if sig_long else "SHORT"
                        entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row_closed["close"])
                        lev = api["get_lev"]()
                        wct = api["get_wct"]()
                        size, margin, notional = size_and_margin(balance, entry_px, leverage=lev, wallet_pct=wct)
                        if size <= 0 or margin > balance:
                            continue
                        fee_in = linear_taker_fee_usdt(size, entry_px, float(settings.TAKER_FEE))
                        balance_after_fee = balance - fee_in
                        atr_now = atr_1h_at_entry(df_1h, float(row_closed["ATR"]))
                        trail_dist = atr_now * settings.ATR_MULTIPLIER
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
                            "entry_time": datetime.now(_tz_app),
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
                        # Chỉ phương pháp dùng %change (PP2) mới snapshot dải — PP1 không đụng pct_change
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
                                tag = "[PAPER]" if slot_id == 1 else "[PAPER2]"
                                notify_func(f"{tag} 🟢 Mở lệnh {side} @ {entry_px:.2f} | Size: {round(size, 3)} BTC")

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
