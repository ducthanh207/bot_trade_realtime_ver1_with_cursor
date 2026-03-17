# -*- coding: utf-8 -*-
"""
Vòng lặp paper trade: dùng giá thật từ Binance (klines), logic giống live_loop
nhưng chỉ cập nhật paper_balance / paper_open_trade / paper_trades, không gọi đặt lệnh thật.
Chỉ chạy khi paper_status == "running"; khi "paused" vẫn xử lý thoát lệnh, không mở mới.
Khi bắt đầu: warm-up lấy đủ nến cũ để tính indicator và ra quyết định ngay từ vòng lặp đầu.
"""

import time
import pandas as pd
from datetime import datetime, timezone
from config import settings as _settings
_tz_app = getattr(_settings, "GMT7", timezone.utc)

from config import settings
from exchange.binance_client import BinanceClient
from strategy import (
    add_indicators,
    long_entry,
    short_entry,
    long_exit,
    short_exit,
    long_exit_early,
    short_exit_early,
    size_and_margin,
    check_atr_trailing,
    max_loss_from_capital,
    limit_pnl_and_exit_price,
)
import bot.state as state


# Số nến tối thiểu để add_indicators không drop hết (RSI 14, WMA 45, ATR 14, EMA 20)
MIN_KLINES_4H = 80
MIN_KLINES_1M = 80
WARMUP_RETRIES = 5
WARMUP_SLEEP_SEC = 2

# Khung 4H GMT+7: nến đóng tại 03:00, 07:00, 11:00, 15:00, 19:00, 23:00. Chỉ vào/ra theo tín hiệu 4H trong cửa sổ đầu mỗi khung.
FOUR_H_BOUNDARY_HOURS = (3, 7, 11, 15, 19, 23)
FOUR_H_BOUNDARY_WINDOW_MINUTES = 5  # phút đầu sau đóng nến (0–4) được phép vào/ra theo 4H


def _is_4h_boundary_window() -> bool:
    """True nếu thời điểm hiện tại (GMT+7) nằm trong phút đầu sau khi nến 4H đóng (03, 07, 11, 15, 19, 23)."""
    now = datetime.now(_tz_app)
    return now.hour in FOUR_H_BOUNDARY_HOURS and now.minute < FOUR_H_BOUNDARY_WINDOW_MINUTES


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def warm_up_klines(client: BinanceClient, symbol: str, notify_func=None) -> bool:
    """
    Lấy đủ nến cũ 4h + 1m để tính indicator ngay từ vòng lặp đầu.
    Trả về True nếu có đủ dữ liệu (sau add_indicators còn >= 2 hàng 4h).
    """
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
    """
    Vòng lặp vô hạn: warm-up dữ liệu, rồi lấy 4h/1m từ Binance, chạy logic entry/exit,
    cập nhật paper state; không gọi place_market_order/close_position.
    """
    state.set_bot_started_at()
    symbol = settings.SYMBOL
    warm_up_klines(client, symbol, notify_func)

    last_status_min = None
    while True:
        try:
            status = state.get_paper_status()
            if status == "stopped":
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            # Lấy dữ liệu từ Binance (chỉ đọc, không lệnh)
            if not client.is_connected():
                df_4h_raw = pd.DataFrame()
                df_1m = pd.DataFrame()
            else:
                df_4h_raw = client.get_klines_4h(symbol, limit=200)
                df_1m = client.get_klines_1m(symbol, limit=500)

            if df_4h_raw.empty or len(df_4h_raw) < 20:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            df_4h = add_indicators(df_4h_raw)
            if df_4h.empty or len(df_4h) < 3:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            # Nến đang form (iloc[-1]); nến đã đóng (iloc[-2], iloc[-3]) dùng cho tín hiệu vào/ra theo khung 4H
            row = _ensure_series(df_4h.iloc[-1])
            prev_row = _ensure_series(df_4h.iloc[-2])
            row_closed = _ensure_series(df_4h.iloc[-2])
            prev_row_closed = _ensure_series(df_4h.iloc[-3])
            ts_4h = df_4h.index[-1]
            in_4h_window = _is_4h_boundary_window()
            balance = state.get_paper_balance()
            open_trade = state.get_paper_open_trade()

            # ---------- EXIT: có position ảo ----------
            if open_trade:
                entry = open_trade["entry_price"]
                size = open_trade["size"]
                side = open_trade["side"]
                max_loss = max_loss_from_capital(open_trade)
                candidates = []

                last_check = open_trade.get("last_sl_check")
                if last_check is not None and not df_1m.empty:
                    df_slice = df_1m.loc[df_1m.index >= last_check]
                    margin = open_trade["margin"]
                    notional = open_trade["notional"]
                    maint = settings.MAINT_MARGIN_RATE * notional

                    for t_1m, m1 in df_slice.iterrows():
                        if side == "LONG":
                            liq_px = entry + (maint - margin) / size
                            if m1["low"] <= liq_px:
                                candidates.append((t_1m, -margin, liq_px, "LIQUIDATION"))
                                break
                        else:
                            liq_px = entry - (maint - margin) / size
                            if m1["high"] >= liq_px:
                                candidates.append((t_1m, -margin, liq_px, "LIQUIDATION"))
                                break

                        pnl_raw, exit_px = check_atr_trailing(open_trade, m1)
                        if pnl_raw is not None:
                            pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                            if px_lim is not None:
                                exit_px = px_lim
                            fee_out = size * exit_px * settings.TAKER_FEE
                            candidates.append((t_1m, pnl_lim - fee_out, exit_px, "ATR_TRAIL"))
                            break

                open_trade["last_sl_check"] = df_1m.index[-1] if not df_1m.empty else ts_4h

                exit_px_ref = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])

                # Thoát theo tín hiệu 4H chỉ xét trong cửa sổ đầu khung (03, 07, 11, 15, 19, 23) và dùng nến đã đóng
                if in_4h_window:
                    if long_exit(prev_row_closed, row_closed) if side == "LONG" else short_exit(prev_row_closed, row_closed):
                        pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                        pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                        exit_px = px_lim if px_lim is not None else exit_px_ref
                        fee_out = size * exit_px * settings.TAKER_FEE
                        candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EXIT"))

                    # Early exit chỉ áp dụng khi đã có nến 4h mới đóng sau lúc vào (tránh loop: cùng nến vừa vào vừa thoát)
                    row_closed_ts = df_4h.index[-2]
                    entry_4h_ts_val = open_trade.get("entry_4h_ts")
                    if entry_4h_ts_val is not None:
                        try:
                            entry_4h_ts_val = pd.Timestamp(entry_4h_ts_val)
                        except Exception:
                            entry_4h_ts_val = None
                    allow_early_exit = entry_4h_ts_val is None or row_closed_ts != entry_4h_ts_val
                    if allow_early_exit and (long_exit_early(prev_row_closed, row_closed) if side == "LONG" else short_exit_early(prev_row_closed, row_closed)):
                        pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                        pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                        exit_px = px_lim if px_lim is not None else exit_px_ref
                        fee_out = size * exit_px * settings.TAKER_FEE
                        candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EARLY_EXIT"))

                if candidates:
                    best_time, best_pnl, best_px, reason = min(candidates, key=lambda x: (x[0], -x[1]))
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
                    }
                    state.set_paper_open_trade(None)
                    state.set_paper_last_trade(closed)
                    state.append_paper_trade(closed)
                    state.set_paper_balance(capital_after)
                    try:
                        from bot.paper_persistence import save_paper_state
                        save_paper_state()
                    except Exception:
                        pass
                    try:
                        from telegram.notifier import notify_trade_closed
                        notify_trade_closed(closed, source="loop")
                    except Exception:
                        if notify_func:
                            notify_func(f"[PAPER] 🔴 Đóng lệnh {side} | PnL: {best_pnl:.2f} USDT | Lý do: {reason}")
                    continue

            # ---------- ENTRY: không position, chỉ khi running; chỉ vào lệnh trong cửa sổ đầu khung 4H (03, 07, 11, 15, 19, 23) theo nến đã đóng
            if not open_trade and status == "running" and in_4h_window:
                sig_long = long_entry(prev_row_closed, row_closed)
                sig_short = short_entry(prev_row_closed, row_closed)
                if sig_long or sig_short:
                    side = "LONG" if sig_long else "SHORT"
                    entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row_closed["close"])
                    lev = state.get_paper_leverage()
                    wct = state.get_paper_wallet_pct()
                    size, margin, notional = size_and_margin(balance, entry_px, leverage=lev, wallet_pct=wct)
                    if size <= 0 or margin > balance:
                        time.sleep(settings.LOOP_INTERVAL_SEC)
                        continue
                    fee_in = size * entry_px * settings.TAKER_FEE
                    balance_after_fee = balance - fee_in
                    atr_now = row_closed["ATR"]
                    trail_dist = atr_now * settings.ATR_MULTIPLIER
                    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist
                    # Lưu 3 đường lúc vào (chỉ dùng khi xuất CSV, không hiển thị trên UI)
                    def _f(v):
                        try:
                            x = float(v)
                            return x if pd.notna(x) else None
                        except (TypeError, ValueError):
                            return None
                    # Lưu entry_4h_ts để tránh early exit ngay trên cùng nến vừa vào (gây loop)
                    entry_4h_ts = df_4h.index[-2]
                    state.set_paper_open_trade({
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
                    })
                    state.set_paper_balance(balance_after_fee)
                    try:
                        from bot.paper_persistence import save_paper_state
                        save_paper_state()
                    except Exception:
                        pass
                    ot = state.get_paper_open_trade()
                    try:
                        from telegram.notifier import notify_trade_opened
                        if ot:
                            notify_trade_opened(ot, source="loop")
                    except Exception:
                        if notify_func:
                            notify_func(f"[PAPER] 🟢 Mở lệnh {side} @ {entry_px:.2f} | Size: {round(size, 3)} BTC")

            # Status định kỳ (paper)
            now = datetime.now(_tz_app)
            if status_func and last_status_min is not None:
                delta_min = (now - last_status_min).total_seconds() / 60
                if delta_min >= settings.STATUS_INTERVAL_MIN:
                    status_func()
                    last_status_min = now
            elif last_status_min is None:
                last_status_min = now

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
