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
            if df_4h.empty or len(df_4h) < 2:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            row = _ensure_series(df_4h.iloc[-1])
            prev_row = _ensure_series(df_4h.iloc[-2])
            ts_4h = df_4h.index[-1]
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

                if long_exit(prev_row, row) if side == "LONG" else short_exit(prev_row, row):
                    pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                    pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                    exit_px = px_lim if px_lim is not None else exit_px_ref
                    fee_out = size * exit_px * settings.TAKER_FEE
                    candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EXIT"))

                if long_exit_early(prev_row, row) if side == "LONG" else short_exit_early(prev_row, row):
                    pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                    pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                    exit_px = px_lim if px_lim is not None else exit_px_ref
                    fee_out = size * exit_px * settings.TAKER_FEE
                    candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EARLY_EXIT"))

                if candidates:
                    best_time, best_pnl, best_px, reason = min(candidates, key=lambda x: (x[0], -x[1]))
                    capital_after = balance + best_pnl
                    closed = {
                        "entry_time": open_trade.get("entry_time"),
                        "exit_time": best_time,
                        "entry_price": entry,
                        "exit_price": best_px,
                        "side": side,
                        "profit": best_pnl,
                        "capital_before": balance,
                        "capital_after": capital_after,
                        "exit_reason": reason,
                    }
                    state.set_paper_open_trade(None)
                    state.set_paper_last_trade(closed)
                    state.append_paper_trade(closed)
                    state.set_paper_balance(capital_after)
                    if notify_func:
                        notify_func(
                            f"[PAPER] 🔴 Đóng lệnh {side} | PnL: {best_pnl:.2f} USDT | Lý do: {reason}"
                        )
                    continue

            # ---------- ENTRY: không position, chỉ khi running ----------
            if not open_trade and status == "running":
                sig_long = long_entry(prev_row, row)
                sig_short = short_entry(prev_row, row)
                if sig_long or sig_short:
                    side = "LONG" if sig_long else "SHORT"
                    entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])
                    size, margin, notional = size_and_margin(balance, entry_px)
                    if size <= 0 or margin > balance:
                        time.sleep(settings.LOOP_INTERVAL_SEC)
                        continue
                    fee_in = size * entry_px * settings.TAKER_FEE
                    balance_after_fee = balance - fee_in
                    atr_now = row["ATR"]
                    trail_dist = atr_now * settings.ATR_MULTIPLIER
                    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist
                    state.set_paper_open_trade({
                        "side": side,
                        "entry_time": datetime.now(timezone.utc),
                        "entry_price": entry_px,
                        "size": size,
                        "margin": margin,
                        "capital_before": balance,
                        "atr": atr_now,
                        "notional": notional,
                        "trail_stop": init_stop,
                        "last_sl_check": df_1m.index[-1] if not df_1m.empty else ts_4h,
                    })
                    state.set_paper_balance(balance_after_fee)
                    if notify_func:
                        notify_func(
                            f"[PAPER] 🟢 Mở lệnh {side} @ {entry_px:.2f} | Size: {round(size, 3)} BTC"
                        )

            # Status định kỳ (paper)
            now = datetime.now(timezone.utc)
            if status_func and last_status_min is not None:
                delta_min = (now - last_status_min).total_seconds() / 60
                if delta_min >= settings.STATUS_INTERVAL_MIN:
                    status_func()
                    last_status_min = now
            elif last_status_min is None:
                last_status_min = now

        except Exception as e:
            if notify_func:
                notify_func(f"[PAPER] ❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(settings.LOOP_INTERVAL_SEC)
