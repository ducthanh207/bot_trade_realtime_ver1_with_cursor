# -*- coding: utf-8 -*-
"""Long poll Telegram: /status, /pnl, /stop, /start, /ping – đọc thông tin paper trade."""

import threading
import requests
from config import settings

# Danh sách lệnh hiển thị trong menu Telegram (khi user bấm / hoặc menu)
BOT_COMMANDS = [
    ("start", "Kiểm tra bot đang chạy"),
    ("ping", "Kiểm tra bot đang chạy"),
    ("status", "Xem trạng thái: vốn, position, PnL, winrate"),
    ("pnl", "Xem PnL tổng (paper)"),
    ("stop", "Dừng paper trade"),
]


def _set_bot_commands() -> bool:
    """Đăng ký menu lệnh với Telegram để hiện gợi ý khi user gõ /."""
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setMyCommands"
    try:
        commands = [{"command": c[0], "description": c[1]} for c in BOT_COMMANDS]
        r = requests.post(url, json={"commands": commands}, timeout=10)
        return r.status_code == 200 and r.json().get("ok")
    except Exception:
        return False


def _reply(chat_id: str, text: str) -> bool:
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _format_status():
    """Nội dung /status: paper balance, position, số lệnh, PnL, trạng thái."""
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


def run_telegram_commands(stop_event: threading.Event = None):
    """
    Long poll getUpdates: /status, /pnl (paper), /stop (dừng paper), /start, /ping.
    Đăng ký menu lệnh với Telegram khi khởi động để hiện gợi ý khi user gõ /.
    """
    if not settings.TELEGRAM_BOT_TOKEN:
        return
    _set_bot_commands()
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = 0
    while stop_event is None or not stop_event.is_set():
        try:
            r = requests.get(url, params={"offset": offset, "timeout": 30}, timeout=35)
            if r.status_code != 200:
                continue
            data = r.json()
            if not data.get("ok"):
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                chat_id = str(msg["chat"]["id"])
                if chat_id != settings.TELEGRAM_CHAT_ID:
                    continue
                text = (msg.get("text") or "").strip().lower()
                if text == "/start" or text == "/ping":
                    _reply(chat_id, "Bot đang chạy (chế độ paper trade).")
                elif text == "/status":
                    _reply(chat_id, _format_status())
                elif text == "/pnl":
                    from bot import state
                    trades = state.get_paper_trades()
                    if not trades:
                        _reply(chat_id, "[PAPER] Chưa có lệnh nào.")
                    else:
                        total = sum(float(t.get("profit", 0)) for t in trades)
                        _reply(chat_id, f"[PAPER] PnL tổng: {total:.2f} USDT ({len(trades)} lệnh)")
                elif text == "/stop":
                    from bot import state
                    state.paper_stop()
                    _reply(chat_id, "[PAPER] Đã dừng paper trade. Vào web bấm Kích hoạt để chạy lại.")
        except Exception:
            pass
        if stop_event:
            for _ in range(10):
                if stop_event.is_set():
                    break
                threading.Event().wait(timeout=1)
