# -*- coding: utf-8 -*-
"""
Vòng lặp chính live: mỗi chu kỳ lấy 4h/1m từ Binance, tính indicator,
kiểm tra exit (liquidation, ATR, 4H, early) rồi entry; gọi exchange + telegram.
"""

import time
import pandas as pd
from datetime import datetime, timezone
from config import settings as _live_settings
_tz_app = getattr(_live_settings, "GMT7", timezone.utc)

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


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def _first_1m_after(ts_4h, df_1m: pd.DataFrame):
    """Timestamp nến 1m đầu tiên sau ts_4h."""
    if df_1m.empty:
        return None
    idx = df_1m.index.searchsorted(ts_4h, side="right")
    if idx >= len(df_1m):
        return None
    return df_1m.index[idx]


def run_live_loop(client: BinanceClient, notify_func=None, status_func=None):
    """
    Chạy vòng lặp vô hạn. notify_func(text) gọi khi mở/đóng lệnh hoặc lỗi.
    status_func() gọi mỗi STATUS_INTERVAL_MIN phút để gửi status.
    """
    state.set_bot_started_at()
    last_status_min = None
    symbol = settings.SYMBOL

    while True:
        try:
            if not client.is_connected():
                if notify_func:
                    notify_func("⚠️ Bot: Không kết nối được Binance. Kiểm tra API key.")
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            # Cập nhật balance
            balance = client.get_balance()
            state.set_balance(balance)

            # Lấy dữ liệu
            df_4h_raw = client.get_klines_4h(symbol, limit=200)
            df_1m = client.get_klines_1m(symbol, limit=500)
            if df_4h_raw.empty or len(df_4h_raw) < 20:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            df_4h = add_indicators(df_4h_raw)
            if df_4h.empty or len(df_4h) < 2:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            # 2 nến 4h gần nhất (đã đóng)
            row = _ensure_series(df_4h.iloc[-1])
            prev_row = _ensure_series(df_4h.iloc[-2])
            ts_4h = df_4h.index[-1]

            pos_exchange = client.get_position(symbol)
            state.set_position(pos_exchange)
            open_trade = state.get_open_trade()

            # Nếu sàn có position nhưng state chưa có open_trade (vd bot vừa restart) -> tạo open_trade từ sàn + ATR hiện tại
            if pos_exchange and not open_trade:
                atr_now = row["ATR"]
                entry = pos_exchange["entry_price"]
                size = pos_exchange["size"]
                side = pos_exchange["side"]
                margin = balance * settings.WALLET_PCT  # ước lượng
                notional = margin * settings.LEVERAGE
                trail_dist = atr_now * settings.ATR_MULTIPLIER
                init_stop = entry - trail_dist if side == "LONG" else entry + trail_dist
                open_trade = {
                    "side": side,
                    "entry_time": datetime.now(_tz_app),
                    "entry_price": entry,
                    "size": size,
                    "margin": margin,
                    "capital_before": balance,
                    "atr": atr_now,
                    "notional": notional,
                    "trail_stop": init_stop,
                    "last_sl_check": df_1m.index[0] if not df_1m.empty else ts_4h,
                }
                state.set_open_trade(open_trade)

            # ---------- EXIT: có position ----------
            if open_trade and pos_exchange:
                entry = open_trade["entry_price"]
                size = open_trade["size"]
                side = open_trade["side"]
                max_loss = max_loss_from_capital(open_trade)
                candidates = []  # (time, pnl_net, exit_px, reason)

                # LAYER 1: Liquidation + ATR trên 1m từ last_sl_check đến hết dữ liệu 1m
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

                # Giá thoát ước lượng = giá đóng nến 1m mới nhất
                exit_px_ref = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])

                # LAYER 2: 4H exit signal
                if long_exit(prev_row, row) if side == "LONG" else short_exit(prev_row, row):
                    pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                    pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                    exit_px = px_lim if px_lim is not None else exit_px_ref
                    fee_out = size * exit_px * settings.TAKER_FEE
                    candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EXIT"))

                # LAYER 2b: Early exit
                if long_exit_early(prev_row, row) if side == "LONG" else short_exit_early(prev_row, row):
                    pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                    pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                    exit_px = px_lim if px_lim is not None else exit_px_ref
                    fee_out = size * exit_px * settings.TAKER_FEE
                    candidates.append((df_1m.index[-1] if not df_1m.empty else ts_4h, pnl_lim - fee_out, exit_px, "4H_EARLY_EXIT"))

                if candidates:
                    best_time, best_pnl, best_px, reason = min(candidates, key=lambda x: (x[0], -x[1]))
                    if not settings.DRY_RUN:
                        client.close_position(symbol)
                    closed = {
                        "entry_time": open_trade.get("entry_time"),
                        "exit_time": best_time,
                        "entry_price": entry,
                        "exit_price": best_px,
                        "side": side,
                        "profit": best_pnl,
                        "exit_reason": reason,
                    }
                    state.set_open_trade(None)
                    state.set_last_trade(closed)
                    state.append_trade_today(closed)
                    state.set_balance(balance + best_pnl)
                    if notify_func:
                        notify_func(
                            f"🔴 Đóng lệnh {side} | PnL: {best_pnl:.2f} USDT | Lý do: {reason}"
                        )
                    continue

            # ---------- ENTRY: không position, không stop ----------
            if not pos_exchange:
                state.set_open_trade(None)

            if not pos_exchange and not state.is_stop_requested():
                sig_long = long_entry(prev_row, row)
                sig_short = short_entry(prev_row, row)
                if sig_long or sig_short:
                    side = "LONG" if sig_long else "SHORT"
                    # Giá vào = giá đóng nến 1m gần nhất (hoặc giá hiện tại)
                    entry_px = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])
                    size, margin, notional = size_and_margin(balance, entry_px)
                    if size <= 0 or margin > balance:
                        time.sleep(settings.LOOP_INTERVAL_SEC)
                        continue
                    qty = round(size, 3)
                    if not settings.DRY_RUN:
                        client.set_leverage(symbol, int(settings.LEVERAGE))
                        client.place_market_order(symbol, side, qty, reduce_only=False)
                    atr_now = row["ATR"]
                    trail_dist = atr_now * settings.ATR_MULTIPLIER
                    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist
                    state.set_open_trade({
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
                    })
                    if notify_func:
                        notify_func(
                            f"🟢 Mở lệnh {side} @ {entry_px:.2f} | Size: {qty} BTC"
                        )

            # Status định kỳ
            now = datetime.now(_tz_app)
            if status_func and last_status_min is not None:
                delta_min = (now - last_status_min).total_seconds() / 60
                if delta_min >= settings.STATUS_INTERVAL_MIN:
                    status_func()
                    last_status_min = now
            elif last_status_min is None:
                last_status_min = now

        except Exception as e:
            if notify_func:
                notify_func(f"❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(settings.LOOP_INTERVAL_SEC)
