# -*- coding: utf-8 -*-
"""
Telegram cho trade thật — nhiều bot Telegram / nhiều chat, cấu hình trên web (/live).

- broadcast(kind, text): gửi tới các kết nối bật cờ tương ứng (trades / hourly / errors).
- Bảng điều khiển: /live (nút bấm) — bật/tắt trade thật, tạm dừng/chạy từng bot, xem status/PnL,
  đóng lệnh. Chỉ nhận lệnh từ đúng chat_id đã nhập trên web và kết nối có "cho phép điều khiển".
- Mỗi token có một luồng long-poll riêng. Token trùng TELEGRAM_BOT_TOKEN trong .env thì dùng luồng
  sẵn có của telegram/commands.py (gọi try_handle_env_update) để không tranh getUpdates.
"""

from __future__ import annotations

import threading
import time

import requests

from config import settings
from live import store

API = "https://api.telegram.org/bot{token}/{method}"

LIVE_COMMANDS = [
    ("live", "Bảng điều khiển trade thật (nút bấm)"),
    ("live_status", "Trade thật: số dư, vị thế, PnL từng bot"),
    ("live_on", "BẬT trade thật (cho phép mở lệnh mới)"),
    ("live_off", "TẮT trade thật (chỉ quản lý lệnh đang mở)"),
    ("live_closeall", "Đóng TẤT CẢ vị thế thật + tắt trade thật"),
]

_pollers = {}       # token -> (thread, stop_event)
_pollers_lock = threading.Lock()


def _call(token: str, method: str, payload: dict, timeout: float = 10):
    r = requests.post(API.format(token=token, method=method), json=payload, timeout=timeout)
    data = r.json() if r.content else {}
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"HTTP {r.status_code}")
    return data.get("result")


def send(token: str, chat_id: str, text: str, keyboard=None) -> bool:
    payload = {"chat_id": chat_id, "text": text[:4000], "disable_web_page_preview": True}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        _call(token, "sendMessage", payload)
        return True
    except Exception as e:
        print("[LIVE-TG] gửi lỗi:", e)
        return False


def send_test(tg_id: str) -> str:
    """Gửi tin thử; trả '' nếu OK, ngược lại là thông báo lỗi."""
    t = next((x for x in store.list_telegrams() if x["id"] == tg_id), None)
    if not t:
        return "Không tìm thấy kết nối"
    token = store.telegram_token(tg_id)
    try:
        me = _call(token, "getMe", {})
        _call(token, "sendMessage", {"chat_id": t["chat_id"], "text": f"✅ Kết nối OK — bot @{me.get('username')} sẽ gửi thông báo trade thật vào đây. Gõ /live để mở bảng điều khiển."})
        return ""
    except Exception as e:
        return str(e)


def broadcast(kind: str, text: str, tg_ids=None):
    """kind: trades | hourly | errors. tg_ids=None → mọi kết nối bật cờ kind."""
    flag = {"trades": "notify_trades", "hourly": "notify_hourly", "errors": "notify_errors"}.get(kind, "notify_trades")
    for t in store.list_telegrams():
        if not t.get("enabled") or not t.get(flag):
            continue
        if tg_ids and t["id"] not in tg_ids:
            continue
        send(store.telegram_token(t["id"]), t["chat_id"], text)


# ------------------------------------------------------------------ điều khiển
def _engine():
    from live.engine import get_engine
    return get_engine()


def _panel():
    on = store.real_trading_enabled()
    rows = [[
        {"text": ("🟢 Trade thật: BẬT" if on else "⚪ Trade thật: TẮT"), "callback_data": "lv:noop"},
        {"text": ("Tắt" if on else "Bật"), "callback_data": "lv:off" if on else "lv:on"},
    ]]
    for b in store.list_bots():
        st = store.bot_state(b["id"])
        has_open = bool(st.get("open_trade"))
        label = f"{'▶' if b['status'] == 'running' else '⏸' if b['status'] == 'paused' else '⏹'} {b['name']}"
        row = [{"text": label, "callback_data": "lv:noop"}]
        if b["status"] == "running":
            row.append({"text": "Tạm dừng", "callback_data": f"lv:pause:{b['id']}"})
        else:
            row.append({"text": "Chạy", "callback_data": f"lv:run:{b['id']}"})
        if has_open:
            row.append({"text": "Đóng lệnh", "callback_data": f"lv:askclose:{b['id']}"})
        rows.append(row)
    rows.append([
        {"text": "📊 Status", "callback_data": "lv:status"},
        {"text": "🔄 Làm mới", "callback_data": "lv:panel"},
    ])
    rows.append([{"text": "🛑 Đóng tất cả", "callback_data": "lv:askcloseall"}])
    text = ("🎛 Bảng điều khiển trade thật\n"
            "▶ chạy | ⏸ tạm dừng (chỉ quản lý lệnh đang mở) | ⏹ dừng\n"
            "Tắt công tắc tổng = không mở lệnh mới ở mọi bot.")
    return text, {"inline_keyboard": rows}


def _confirm(text: str, yes_data: str):
    return text, {"inline_keyboard": [[
        {"text": "✅ Xác nhận", "callback_data": yes_data},
        {"text": "Huỷ", "callback_data": "lv:panel"},
    ]]}


def handle(conn: dict, token: str, chat_id: str, text: str = "", data: str = ""):
    """Xử lý một lệnh / nút bấm. Trả True nếu là lệnh trade thật."""
    who = f"telegram:{conn.get('name')}"
    t = (text or "").strip().split("@")[0].lower()
    reply = None
    kb = None
    if data:
        parts = data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""
        if action == "noop":
            return True
        if action == "on":
            store.set_real_trading_enabled(True, by=who)
            reply, kb = _panel()
        elif action == "off":
            store.set_real_trading_enabled(False, by=who)
            reply, kb = _panel()
        elif action in ("pause", "run"):
            try:
                store.set_bot_status(arg, "paused" if action == "pause" else "running")
                store.add_event("bot", f"Bot {arg}: {'tạm dừng' if action == 'pause' else 'chạy'} (bởi {who})", arg)
            except ValueError as e:
                reply = f"Lỗi: {e}"
            if reply is None:
                reply, kb = _panel()
        elif action == "askclose":
            b = store.get_bot(arg)
            reply, kb = _confirm(f"Đóng lệnh đang mở của {b['name'] if b else arg} bằng lệnh MARKET?", f"lv:close:{arg}")
        elif action == "close":
            _engine().request_close(arg, by="telegram")
            reply = "⏳ Đã gửi lệnh đóng, kết quả sẽ báo trong vài giây."
        elif action == "askcloseall":
            reply, kb = _confirm("Đóng TẤT CẢ vị thế thật (MARKET) và TẮT trade thật?", "lv:closeall")
        elif action == "closeall":
            _engine().request_close_all(by="telegram")
            reply = "⏳ Đã tắt trade thật và gửi lệnh đóng mọi vị thế."
        elif action == "status":
            reply = _engine().hourly_text()
        else:
            reply, kb = _panel()
    elif t in ("/live", "/panel", "/start_live"):
        reply, kb = _panel()
    elif t in ("/live_status", "/live_pnl"):
        reply = _engine().hourly_text()
    elif t == "/live_on":
        store.set_real_trading_enabled(True, by=who)
        reply = "🟢 Đã BẬT trade thật."
    elif t == "/live_off":
        store.set_real_trading_enabled(False, by=who)
        reply = "⚪ Đã TẮT trade thật (lệnh đang mở vẫn được quản lý thoát)."
    elif t == "/live_closeall":
        reply, kb = _confirm("Đóng TẤT CẢ vị thế thật (MARKET) và TẮT trade thật?", "lv:closeall")
    else:
        return False
    if reply:
        send(token, chat_id, reply, kb)
    return True


def _parse_update(upd: dict):
    """(chat_id, text, callback_data, callback_id)"""
    if upd.get("callback_query"):
        cq = upd["callback_query"]
        msg = cq.get("message") or {}
        return str(msg.get("chat", {}).get("id", "")), "", (cq.get("data") or ""), cq.get("id")
    msg = upd.get("message") or upd.get("edited_message") or {}
    return str(msg.get("chat", {}).get("id", "")), (msg.get("text") or ""), "", None


def _process(conn: dict, token: str, upd: dict, own_poller: bool) -> bool:
    chat_id, text, data, cq_id = _parse_update(upd)
    if not chat_id or chat_id != str(conn.get("chat_id")) or not conn.get("allow_control") or not conn.get("enabled"):
        return False
    if data and not data.startswith("lv:"):
        return False
    if cq_id:
        try:
            _call(token, "answerCallbackQuery", {"callback_query_id": cq_id}, timeout=5)
        except Exception:
            pass
    # Bot Telegram riêng cho trade thật: chấp nhận thêm lệnh ngắn
    if own_poller and not data:
        alias = {"/start": "/live", "/status": "/live_status", "/pnl": "/live_status", "/on": "/live_on",
                 "/off": "/live_off", "/closeall": "/live_closeall"}
        key = (text or "").strip().split("@")[0].lower()
        text = alias.get(key, text)
    try:
        return handle(conn, token, chat_id, text, data)
    except Exception as e:
        send(token, chat_id, f"Lỗi: {e}")
        return True


def try_handle_env_update(upd: dict) -> bool:
    """Gọi từ telegram/commands.py (luồng poll của TELEGRAM_BOT_TOKEN trong .env)."""
    env_token = settings.TELEGRAM_BOT_TOKEN
    if not env_token:
        return False
    try:
        for t in store.list_telegrams():
            if store.telegram_token(t["id"]) == env_token:
                if _process(t, env_token, upd, own_poller=False):
                    return True
    except Exception:
        return False
    return False


def _poll_loop(tg_id: str, token: str, stop: threading.Event):
    try:
        _call(token, "setMyCommands", {"commands": [{"command": c, "description": d} for c, d in LIVE_COMMANDS]})
    except Exception:
        pass
    offset = 0
    while not stop.is_set():
        try:
            r = requests.get(API.format(token=token, method="getUpdates"),
                             params={"offset": offset, "timeout": 25}, timeout=30)
            data = r.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = upd["update_id"] + 1
                conn = next((x for x in store.list_telegrams() if x["id"] == tg_id), None)
                if conn:
                    _process(conn, token, upd, own_poller=True)
        except Exception:
            time.sleep(5)


def sync_pollers():
    """Bật/tắt luồng poll theo cấu hình hiện tại (gọi định kỳ)."""
    env_token = settings.TELEGRAM_BOT_TOKEN
    wanted = {}
    for t in store.list_telegrams():
        if not (t.get("enabled") and t.get("allow_control")):
            continue
        token = store.telegram_token(t["id"])
        if not token or token == env_token or token in wanted:
            continue
        wanted[token] = t["id"]
    with _pollers_lock:
        for token in list(_pollers):
            if token not in wanted:
                _pollers[token][1].set()
                del _pollers[token]
        for token, tg_id in wanted.items():
            if token in _pollers and _pollers[token][0].is_alive():
                continue
            stop = threading.Event()
            th = threading.Thread(target=_poll_loop, args=(tg_id, token, stop), name=f"live-tg-{tg_id}", daemon=True)
            th.start()
            _pollers[token] = (th, stop)


def start_poller_manager():
    def loop():
        while True:
            try:
                sync_pollers()
            except Exception as e:
                print("[LIVE-TG] sync lỗi:", e)
            time.sleep(30)
    th = threading.Thread(target=loop, name="live-tg-manager", daemon=True)
    th.start()
    return th
