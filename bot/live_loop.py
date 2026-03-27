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
    size_and_margin,
    atr_1h_at_entry,
    compute_exit_candidates,
    pick_best_exit,
)
from strategy.strategies import get_trading_method
from strategy.strategies.registry import uses_pct_change_bands
from strategy.pct_change_avg import build_pct_change_avg_bands_series
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
    last_hourly_status = None
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
            df_1h = pd.DataFrame()
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
                atr_now = atr_1h_at_entry(df_1h, float(row["ATR"]))
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
                entry = float(open_trade["entry_price"])
                size = float(open_trade["size"])
                side = open_trade["side"]

                exit_px_ref = float(df_1m["close"].iloc[-1]) if not df_1m.empty else float(row["close"])
                exit_time_ts = df_1m.index[-1] if not df_1m.empty else ts_4h

                row_4h_ts = df_4h.index[-1]
                entry_4h_ts = open_trade.get("entry_4h_ts")
                allow_early_exit = entry_4h_ts is None or row_4h_ts != entry_4h_ts

                method = get_trading_method()
                candidates = compute_exit_candidates(
                    open_trade,
                    df_1m,
                    df_1h,
                    df_4h_raw,
                    prev_row,
                    row,
                    exit_px_ref,
                    exit_time_ts,
                    paper_use_4h_window=False,
                    in_4h_window=True,
                    method=method,
                    lookback_trades=settings.LOOKBACK_TRADES,
                    allow_early_exit=allow_early_exit,
                )
                open_trade["last_sl_check"] = df_1m.index[-1] if not df_1m.empty else ts_4h

                best = pick_best_exit(candidates)
                if best is not None:
                    best_time, best_pnl, best_px, reason = best
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
                    atr_now = atr_1h_at_entry(df_1h, float(row["ATR"]))
                    trail_dist = atr_now * settings.ATR_MULTIPLIER
                    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist
                    tm = get_trading_method()
                    # Lưu entry_4h_ts để tránh early exit ngay trên cùng nến vừa vào (gây loop)
                    entry_4h_ts = df_4h.index[-1]
                    live_open = {
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
                        "entry_4h_ts": entry_4h_ts,
                        "trading_method": tm,
                    }
                    if uses_pct_change_bands(tm):
                        bands_at_entry = build_pct_change_avg_bands_series(
                            df_4h_raw, lookback_trades=settings.LOOKBACK_TRADES
                        )
                        live_open["pct_half_width_pct"] = bands_at_entry.get("band_half_width_pct")
                        live_open["pct_upper_at_entry"] = bands_at_entry.get("upper")
                        live_open["pct_lower_at_entry"] = bands_at_entry.get("lower")
                    state.set_open_trade(live_open)
                    if notify_func:
                        notify_func(
                            f"🟢 Mở lệnh {side} @ {entry_px:.2f} | Size: {qty} BTC"
                        )

            # Status định kỳ + báo kịch bản thoát mỗi giờ
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
            if notify_func:
                notify_func(f"❌ Lỗi: {e}")
            import traceback
            traceback.print_exc()

        time.sleep(settings.LOOP_INTERVAL_SEC)
