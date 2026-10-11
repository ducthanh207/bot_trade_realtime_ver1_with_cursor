# -*- coding: utf-8 -*-
"""
Vòng lặp paper trade: bốn slot song song — Paper 1/2/3/4.
Dùng giá thật từ Binance (klines); chỉ cập nhật state, không gọi sàn.
Slot stopped: bỏ qua; paused: vẫn thoát lệnh, không mở mới.
Logic vào/ra lệnh của mỗi slot nằm ở bot/slot_engine.py (dùng chung với trade thật).
"""

import time
import pandas as pd
from datetime import datetime, timezone
from config import settings as _settings

_tz_app = getattr(_settings, "GMT7", timezone.utc)

from config import settings
from exchange.binance_client import BinanceClient
from strategy import add_indicators
from strategy.strategies.paper_slots import method_for_paper_slot
from bot.slot_engine import (
    MarketContext,
    step_slot,
    update_circuit_breaker,
    as_aware_utc as _as_aware_utc,
    is_4h_boundary_window,
    FOUR_H_BOUNDARY_HOURS,
    FOUR_H_BOUNDARY_WINDOW_MINUTES,
)
import bot.state as state


MIN_KLINES_4H = 80
MIN_KLINES_1M = 80
WARMUP_RETRIES = 5
WARMUP_SLEEP_SEC = 2


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
    return is_4h_boundary_window()


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
    update_circuit_breaker(_CB_SLOT_API.get(int(slot_id)), pnl, balance)


def _paper_hooks(slot_id: int, notify_func=None) -> dict:
    """Sau khi mở/đóng lệnh paper: lưu file + báo Telegram."""
    tag = "[PAPER]" if slot_id == 1 else f"[PAPER{slot_id}]"

    def _save():
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass

    def on_opened(ot):
        _save()
        try:
            from telegram.notifier import notify_trade_opened
            if ot:
                notify_trade_opened(ot, source="loop", paper_slot=slot_id)
        except Exception:
            if notify_func and ot:
                notify_func(f"{tag} Mo lenh {ot.get('side')} @ {float(ot.get('entry_price') or 0):.2f} | Size: {round(float(ot.get('size') or 0), 3)} BTC")

    def on_closed(closed):
        _save()
        try:
            from telegram.notifier import notify_trade_closed
            notify_trade_closed(closed, source="loop", paper_slot=slot_id)
        except Exception:
            if notify_func:
                notify_func(f"{tag} Dong lenh {closed.get('side')} | PnL: {float(closed.get('profit') or 0):.2f} USDT | Ly do: {closed.get('exit_reason')}")

    return {"on_opened": on_opened, "on_closed": on_closed}


def _paper_slot_configs(notify_func=None):
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
    out = []
    for sid, api in apis:
        api["lookback"] = (lambda s=sid: _pct_lookback_trades_for_slot(s))
        api["cb"] = _CB_SLOT_API.get(sid)
        api.update(_paper_hooks(sid, notify_func))
        out.append((sid, method_for_paper_slot(sid), api))
    return out


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

            mkt = MarketContext(df_4h_raw, df_1m, df_1h, _is_4h_boundary_window())
            if not mkt.ok:
                time.sleep(settings.LOOP_INTERVAL_SEC)
                continue

            for slot_id, method, api in _paper_slot_configs(notify_func):
                step_slot(slot_id, method, api, mkt)

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
