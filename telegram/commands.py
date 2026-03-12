# -*- coding: utf-8 -*-
"""Long poll Telegram: /status, /pnl, /stop, /advise, /start, /ping – paper trade + tư vấn vào/đóng lệnh."""

import threading
import requests
from datetime import datetime, timezone
from config import settings

# Trạng thái chờ nhập % vốn (chat_id -> { "waiting": "pct", "side": "LONG"|"SHORT" })
_pending = {}
_pending_lock = threading.Lock()

BOT_COMMANDS = [
    ("start", "Kiểm tra bot đang chạy"),
    ("ping", "Kiểm tra bot đang chạy"),
    ("status", "Xem trạng thái: vốn, position, PnL, winrate"),
    ("pnl", "Xem PnL tổng (paper)"),
    ("advise", "Tư vấn tín hiệu + nút vào/đóng lệnh"),
    ("trade", "Vào lệnh ngay hoặc đóng lệnh (nút bấm)"),
    ("stop", "Dừng paper trade"),
]


def _set_bot_commands() -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setMyCommands"
    try:
        commands = [{"command": c[0], "description": c[1]} for c in BOT_COMMANDS]
        r = requests.post(url, json={"commands": commands}, timeout=10)
        return r.status_code == 200 and r.json().get("ok")
    except Exception:
        return False


def _reply(chat_id: str, text: str, reply_markup=None) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _answer_callback(callback_query_id: str, text: str = ""):
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
    try:
        requests.post(url, json={"callback_query_id": callback_query_id, "text": text[:200]}, timeout=5)
    except Exception:
        pass


def _format_status():
    from bot import state
    d = state.to_status_dict()
    balance = d.get("paper_balance", 0)
    pos = d.get("paper_open_trade")
    pos_str = "Không"
    if pos:
        pos_str = f"{pos.get('side', '')} @ {pos.get('entry_price', 0):.2f}"
    n = d.get("paper_trades_count", 0)
    total_pnl = d.get("paper_total_pnl", 0)
    winrate = d.get("paper_winrate", 0)
    status = d.get("paper_status", "stopped")
    started = d.get("paper_started_at") or "N/A"
    lines = [
        "[PAPER]",
        f"Vốn: {balance:.2f} USDT",
        f"Position: {pos_str}",
        f"Trạng thái: {status}",
        f"Lệnh (từ khi bắt đầu): {n}",
        f"Winrate: {winrate}%",
        f"PNL tổng: {total_pnl:.2f} USDT",
        f"Ngày bắt đầu: {started}",
    ]
    if d.get("paper_last_trade"):
        lines.append(f"Lệnh gần nhất PnL: {d['paper_last_trade'].get('profit', 0):.2f}")
    return "\n".join(lines)


def _get_entry_close_keyboard():
    """Trả về inline keyboard: Vào LONG/SHORT (nếu chưa có lệnh) hoặc Đóng lệnh (nếu đang có lệnh)."""
    from bot import state
    open_trade = state.get_paper_open_trade()
    balance = state.get_paper_balance()
    if open_trade:
        return {"inline_keyboard": [[{"text": "Đóng lệnh", "callback_data": "close_position"}]]}
    if balance and balance > 0:
        return {
            "inline_keyboard": [
                [
                    {"text": "Vào LONG", "callback_data": "entry_long"},
                    {"text": "Vào SHORT", "callback_data": "entry_short"},
                ]
            ]
        }
    return None


def _get_advise_text_and_keyboard(chat_id: str):
    """Lấy nội dung tư vấn + inline keyboard (Vào LONG/SHORT hoặc Đóng lệnh)."""
    from exchange.binance_client import BinanceClient
    from strategy import add_indicators, evaluate_conditions
    from bot import state

    open_trade = state.get_paper_open_trade()
    balance = state.get_paper_balance()

    lines = ["[TƯ VẤN TÍN HIỆU]"]
    keyboard = _get_entry_close_keyboard()

    try:
        client = BinanceClient()
        df_4h_raw = client.get_klines_4h(settings.SYMBOL, limit=100)
        if df_4h_raw.empty or len(df_4h_raw) < 50:
            lines.append("Chưa đủ dữ liệu nến 4h.")
            return "\n".join(lines), keyboard
        df_4h = add_indicators(df_4h_raw)
        if df_4h.empty or len(df_4h) < 2:
            lines.append("Không tính được indicator.")
            return "\n".join(lines), keyboard

        prev_row = df_4h.iloc[-2]
        row = df_4h.iloc[-1]
        res = evaluate_conditions(prev_row, row)

        lines.append(f"LONG: {res['long_pct']}% đạt (1/3)")
        for name, met in res["long_conditions"]:
            lines.append(f"  • {name}: {'✅' if met else '❌'}")
        lines.append(f"SHORT: {res['short_pct']}% đạt (1/3)")
        for name, met in res["short_conditions"]:
            lines.append(f"  • {name}: {'✅' if met else '❌'}")
        lines.append(f"Rủi ro ước tính: {res['risk_pct']}%")

        if open_trade:
            entry = float(open_trade.get("entry_price", 0))
            side = open_trade.get("side", "")
            df_1m = client.get_klines_1m(settings.SYMBOL, limit=1)
            price = float(df_1m["close"].iloc[-1]) if not df_1m.empty else entry
            size = float(open_trade.get("size", 0))
            if side == "LONG":
                pnl = (price - entry) * size
            else:
                pnl = (entry - price) * size
            lines.append("")
            lines.append(f"📌 Lệnh {side} @ {entry:.2f} | Giá: {price:.2f} | PnL: {pnl:+.2f} USDT")
        else:
            if balance and balance > 0:
                lines.append("")
                lines.append("👉 Chọn Vào LONG / Vào SHORT bên dưới, rồi nhập % vốn (1-100).")
            else:
                lines.append("Vốn = 0. Vào web Kích hoạt và nhập vốn.")
    except Exception as e:
        lines.append(f"Lỗi: {e}")

    return "\n".join(lines), keyboard


def _do_paper_entry(chat_id: str, side: str, pct: float) -> str:
    """Vào lệnh paper thủ công. Trả về thông báo."""
    from bot import state
    from exchange.binance_client import BinanceClient
    from strategy.risk import size_and_margin

    if state.get_paper_open_trade():
        return "Đang có lệnh rồi, không thể mở thêm."
    balance = state.get_paper_balance()
    if not balance or balance <= 0:
        return "Vốn = 0. Vào web Kích hoạt và nhập vốn."
    try:
        client = BinanceClient()
        df = client.get_klines_1m(settings.SYMBOL, limit=1)
        if df.empty:
            return "Không lấy được giá."
        entry_px = float(df["close"].iloc[-1])
        row_4h = None
        try:
            df_4h = client.get_klines_4h(settings.SYMBOL, limit=100)
            from strategy import add_indicators
            df_4h = add_indicators(df_4h)
            if not df_4h.empty:
                row_4h = df_4h.iloc[-1]
        except Exception:
            pass
        atr_now = float(row_4h["ATR"]) if row_4h is not None and "ATR" in row_4h else entry_px * 0.01
        wallet_pct = max(0.01, min(1.0, pct / 100.0))
        size, margin, notional = size_and_margin(balance, entry_px, wallet_pct=wallet_pct)
        if size <= 0 or margin > balance:
            return "Không đủ margin hoặc size = 0."
        fee_in = size * entry_px * settings.TAKER_FEE
        balance_after = balance - fee_in
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
            "last_sl_check": df.index[-1],
        })
        state.set_paper_balance(balance_after)
        return f"Đã vào lệnh {side} @ {entry_px:.2f} | % vốn: {pct}% | Size: {size:.4f} | Margin: {margin:.2f} USDT"
    except Exception as e:
        return f"Lỗi: {e}"


def _do_paper_close(chat_id: str) -> str:
    """Đóng lệnh paper thủ công. Trả về thông báo."""
    from bot import state
    from exchange.binance_client import BinanceClient

    open_trade = state.get_paper_open_trade()
    if not open_trade:
        return "Không có lệnh nào đang mở."
    balance = state.get_paper_balance()
    entry = float(open_trade["entry_price"])
    side = open_trade["side"]
    size = float(open_trade["size"])
    try:
        client = BinanceClient()
        df = client.get_klines_1m(settings.SYMBOL, limit=1)
        exit_px = float(df["close"].iloc[-1]) if not df.empty else entry
    except Exception:
        exit_px = entry
    if side == "LONG":
        pnl = (exit_px - entry) * size
    else:
        pnl = (entry - exit_px) * size
    fee_out = size * exit_px * settings.TAKER_FEE
    pnl_net = pnl - fee_out
    capital_after = balance + pnl_net
    closed = {
        "entry_time": open_trade.get("entry_time"),
        "exit_time": datetime.now(timezone.utc),
        "entry_price": entry,
        "exit_price": exit_px,
        "side": side,
        "profit": pnl_net,
        "capital_before": balance,
        "capital_after": capital_after,
        "exit_reason": "MANUAL_TELEGRAM",
    }
    state.set_paper_open_trade(None)
    state.set_paper_last_trade(closed)
    state.append_paper_trade(closed)
    state.set_paper_balance(capital_after)
    return f"Đã đóng lệnh {side}. PnL: {pnl_net:+.2f} USDT | Vốn sau: {capital_after:.2f} USDT"


def _process_update(upd: dict, offset_ref: list):
    """Xử lý 1 update: message hoặc callback_query."""
    offset_ref[0] = upd["update_id"] + 1
    chat_id = None
    text = ""
    callback_query_id = None
    callback_data = None

    if upd.get("callback_query"):
        cq = upd["callback_query"]
        callback_query_id = cq.get("id")
        callback_data = (cq.get("data") or "").strip()
        msg = cq.get("message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
    else:
        msg = upd.get("message") or upd.get("edited_message")
        if not msg:
            return
        chat_id = str(msg["chat"]["id"])
        text = (msg.get("text") or "").strip()

    if not chat_id or chat_id != settings.TELEGRAM_CHAT_ID:
        return

    base_url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}"

    # Callback: Vào LONG / Vào SHORT / Đóng lệnh
    if callback_query_id is not None and callback_data:
        _answer_callback(callback_query_id)
        if callback_data == "entry_long":
            with _pending_lock:
                _pending[chat_id] = {"waiting": "pct", "side": "LONG"}
            _reply(chat_id, "Bạn chọn LONG. Nhập % vốn (1-100), ví dụ: 30")
        elif callback_data == "entry_short":
            with _pending_lock:
                _pending[chat_id] = {"waiting": "pct", "side": "SHORT"}
            _reply(chat_id, "Bạn chọn SHORT. Nhập % vốn (1-100), ví dụ: 30")
        elif callback_data == "close_position":
            msg_close = _do_paper_close(chat_id)
            _reply(chat_id, msg_close)
        return

    # Đang chờ nhập % vốn
    with _pending_lock:
        pend = _pending.get(chat_id)
    if pend and pend.get("waiting") == "pct" and text:
        try:
            pct = float(text.replace(",", "."))
            if 1 <= pct <= 100:
                side = pend["side"]
                with _pending_lock:
                    _pending.pop(chat_id, None)
                msg_ent = _do_paper_entry(chat_id, side, pct)
                _reply(chat_id, msg_ent)
            else:
                _reply(chat_id, "Nhập số từ 1 đến 100 (%).")
        except ValueError:
            _reply(chat_id, "Nhập số % vốn, ví dụ: 30")
        return

    # Lệnh text
    text_lower = text.lower()
    if text_lower == "/start" or text_lower == "/ping":
        _reply(chat_id, "Bot đang chạy (chế độ paper trade).")
    elif text_lower == "/status":
        _reply(chat_id, _format_status())
    elif text_lower == "/pnl":
        from bot import state
        trades = state.get_paper_trades()
        if not trades:
            _reply(chat_id, "[PAPER] Chưa có lệnh nào.")
        else:
            total = sum(float(t.get("profit", 0)) for t in trades)
            _reply(chat_id, f"[PAPER] PnL tổng: {total:.2f} USDT ({len(trades)} lệnh)")
    elif text_lower == "/stop":
        from bot import state
        state.paper_stop()
        _reply(chat_id, "[PAPER] Đã dừng paper trade. Vào web bấm Kích hoạt để chạy lại.")
    elif text_lower == "/advise":
        advise_text, keyboard = _get_advise_text_and_keyboard(chat_id)
        _reply(chat_id, advise_text, reply_markup=keyboard)
    elif text_lower == "/trade":
        keyb = _get_entry_close_keyboard()
        if keyb:
            _reply(chat_id, "Chọn hành động (vào lệnh hoặc đóng lệnh):", reply_markup=keyb)
        else:
            _reply(chat_id, "Vốn = 0. Vào web Kích hoạt và nhập vốn, sau đó dùng /trade hoặc /advise.")


def run_telegram_commands(stop_event: threading.Event = None):
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    _set_bot_commands()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = [0]
    while stop_event is None or not stop_event.is_set():
        try:
            r = requests.get(url, params={"offset": offset[0], "timeout": 30}, timeout=35)
            if r.status_code != 200:
                continue
            data = r.json()
            if not data.get("ok"):
                continue
            for upd in data.get("result", []):
                _process_update(upd, offset)
        except Exception:
            pass
        if stop_event:
            for _ in range(10):
                if stop_event.is_set():
                    break
                threading.Event().wait(timeout=1)
