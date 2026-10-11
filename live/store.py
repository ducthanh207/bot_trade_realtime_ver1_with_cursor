# -*- coding: utf-8 -*-
"""
Cấu hình + trạng thái trade thật, lưu ở data/live/ (ngoài git, không bị git pull ghi đè).

- config.json: công tắc tổng, tài khoản sàn, kết nối Telegram, bot (cặp coin × chiến lược × tài khoản).
  API key / secret / token Telegram được mã hoá (live/secrets_box.py), web chỉ thấy bản che.
- state.json: vốn từng bot, lệnh đang mở, lịch sử lệnh, circuit breaker, ảnh chụp số dư mỗi giờ, nhật ký.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

import pandas as pd

from config import settings
from live import secrets_box
from live.secrets_box import DATA_DIR

_tz_app = getattr(settings, "GMT7", timezone.utc)

CONFIG_FILE = DATA_DIR / "config.json"
STATE_FILE = DATA_DIR / "state.json"

EXCHANGES = {
    "binance_usdm": "Binance Futures (USDⓈ-M)",
}
METHODS = {
    "1": "PP1 — thoát cổ điển",
    "2": "PP2 — TP %change + lọc RSI 1H",
    "3": "PP3 — Exit B + EMA filter + circuit breaker",
    "4": "PP4 — nâng cấp PP3 (hard stop % vốn)",
}
EXCHANGE_STOP_MODES = ("trail", "hard", "off")
BOT_STATUSES = ("stopped", "running", "paused")
MAX_EVENTS = 400
MAX_SNAPSHOTS = 24 * 60

_lock = threading.RLock()
_config = None
_state = None


def now_iso() -> str:
    return datetime.now(_tz_app).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------- JSON I/O
def _to_json(obj):
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _to_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json(v) for v in obj]
    try:
        import numpy as np
        if isinstance(obj, np.generic):
            return obj.item()
    except Exception:
        pass
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


def _write_atomic(path, data):
    secrets_box._ensure_dir()
    tmp = path.with_suffix(".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(_to_json(data), f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        # File hỏng: giữ bản sao để không mất dữ liệu, bắt đầu lại từ mặc định
        try:
            os.replace(path, path.with_suffix(f".broken.{int(datetime.now().timestamp())}"))
        except Exception:
            pass
        return default


_TS_KEYS = ("entry_time", "last_sl_check", "entry_4h_ts", "exit_time")


def _revive_trade(t: dict):
    """Chuỗi ISO → Timestamp có múi giờ (so sánh được với index nến)."""
    if not t:
        return t
    for k in _TS_KEYS:
        v = t.get(k)
        if isinstance(v, str) and v:
            try:
                t[k] = pd.Timestamp(v)
            except Exception:
                pass
    return t


def _load():
    global _config, _state
    if _config is None:
        cfg = _read(CONFIG_FILE, {})
        cfg.setdefault("real_trading_enabled", False)
        cfg.setdefault("accounts", {})
        cfg.setdefault("telegrams", {})
        cfg.setdefault("bots", {})
        _config = cfg
    if _state is None:
        st = _read(STATE_FILE, {})
        st.setdefault("bots", {})
        st.setdefault("snapshots", [])
        st.setdefault("events", [])
        for bs in st["bots"].values():
            _revive_trade(bs.get("open_trade"))
            for k in ("light_until", "heavy_until"):
                v = (bs.get("cb") or {}).get(k)
                if isinstance(v, str) and v:
                    bs["cb"][k] = datetime.fromisoformat(v)
        _state = st


def save_config():
    with _lock:
        _load()
        _write_atomic(CONFIG_FILE, _config)


def save_state():
    with _lock:
        _load()
        _write_atomic(STATE_FILE, _state)


def reload():
    """Chỉ dùng cho test."""
    global _config, _state, CONFIG_FILE, STATE_FILE
    with _lock:
        _config = None
        _state = None
        CONFIG_FILE = secrets_box.DATA_DIR / "config.json"
        STATE_FILE = secrets_box.DATA_DIR / "state.json"


# ---------------------------------------------------------- công tắc tổng
def real_trading_enabled() -> bool:
    with _lock:
        _load()
        return bool(_config.get("real_trading_enabled"))


def set_real_trading_enabled(on: bool, by: str = "web"):
    with _lock:
        _load()
        _config["real_trading_enabled"] = bool(on)
        save_config()
    add_event("switch", f"Công tắc trade thật: {'BẬT' if on else 'TẮT'} (bởi {by})")


# ------------------------------------------------------------- tài khoản
def list_accounts(public: bool = True) -> list:
    with _lock:
        _load()
        out = []
        for a in _config["accounts"].values():
            out.append(_public_account(a) if public else dict(a))
        return sorted(out, key=lambda x: x.get("created_at", ""))


def _public_account(a: dict) -> dict:
    return {k: v for k, v in a.items() if not k.endswith("_enc")}


def get_account(acc_id: str) -> dict | None:
    with _lock:
        _load()
        a = _config["accounts"].get(acc_id)
        return dict(a) if a else None


def account_credentials(acc_id: str):
    a = get_account(acc_id)
    if not a:
        return None, None
    return secrets_box.decrypt(a.get("api_key_enc", "")), secrets_box.decrypt(a.get("api_secret_enc", ""))


def upsert_account(data: dict) -> dict:
    from exchange.binance_futures import BASE_URLS
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Cần đặt tên tài khoản")
    exchange = data.get("exchange") or "binance_usdm"
    if exchange not in EXCHANGES:
        raise ValueError("Sàn chưa được hỗ trợ")
    env = data.get("env") or "mainnet"
    if env not in BASE_URLS:
        raise ValueError("Môi trường không hợp lệ")
    with _lock:
        _load()
        acc_id = data.get("id")
        if acc_id and acc_id not in _config["accounts"]:
            raise ValueError("Không tìm thấy tài khoản")
        a = dict(_config["accounts"].get(acc_id) or {})
        if not acc_id:
            acc_id = _new_id("acc")
            a = {"id": acc_id, "created_at": now_iso(), "enabled": False}
        a.update({"name": name, "exchange": exchange, "env": env})
        key = (data.get("api_key") or "").strip()
        secret = (data.get("api_secret") or "").strip()
        if key:
            a["api_key_enc"] = secrets_box.encrypt(key)
            a["key_hint"] = secrets_box.hint(key)
        if secret:
            a["api_secret_enc"] = secrets_box.encrypt(secret)
        a["has_keys"] = bool(a.get("api_key_enc") and a.get("api_secret_enc"))
        if "enabled" in data:
            a["enabled"] = bool(data["enabled"]) and a["has_keys"]
        _config["accounts"][acc_id] = a
        save_config()
        return _public_account(a)


def set_account_field(acc_id: str, **fields):
    with _lock:
        _load()
        a = _config["accounts"].get(acc_id)
        if not a:
            raise ValueError("Không tìm thấy tài khoản")
        a.update(fields)
        save_config()


def delete_account(acc_id: str):
    with _lock:
        _load()
        if any(b.get("account_id") == acc_id for b in _config["bots"].values()):
            raise ValueError("Tài khoản đang được bot sử dụng — xoá bot trước")
        _config["accounts"].pop(acc_id, None)
        save_config()


# -------------------------------------------------------------- Telegram
def _public_telegram(t: dict) -> dict:
    return {k: v for k, v in t.items() if not k.endswith("_enc")}


def list_telegrams(public: bool = True) -> list:
    with _lock:
        _load()
        out = [(_public_telegram(t) if public else dict(t)) for t in _config["telegrams"].values()]
        return sorted(out, key=lambda x: x.get("created_at", ""))


def telegram_token(tg_id: str) -> str:
    with _lock:
        _load()
        t = _config["telegrams"].get(tg_id)
        return secrets_box.decrypt(t.get("token_enc", "")) if t else ""


def upsert_telegram(data: dict) -> dict:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Cần đặt tên kết nối Telegram")
    chat_id = str(data.get("chat_id") or "").strip()
    if not chat_id or not chat_id.lstrip("-").isdigit():
        raise ValueError("Chat ID phải là số (vd 916843176)")
    with _lock:
        _load()
        tg_id = data.get("id")
        if tg_id and tg_id not in _config["telegrams"]:
            raise ValueError("Không tìm thấy kết nối Telegram")
        t = dict(_config["telegrams"].get(tg_id) or {})
        if not tg_id:
            tg_id = _new_id("tg")
            t = {"id": tg_id, "created_at": now_iso()}
        token = (data.get("token") or "").strip()
        if token:
            if ":" not in token:
                raise ValueError("Token bot không đúng dạng (123456:ABC...)")
            t["token_enc"] = secrets_box.encrypt(token)
            t["token_hint"] = secrets_box.hint(token)
        if not t.get("token_enc"):
            raise ValueError("Cần nhập token bot Telegram")
        t.update({
            "name": name,
            "chat_id": chat_id,
            "enabled": bool(data.get("enabled", t.get("enabled", True))),
            "notify_trades": bool(data.get("notify_trades", t.get("notify_trades", True))),
            "notify_hourly": bool(data.get("notify_hourly", t.get("notify_hourly", True))),
            "notify_errors": bool(data.get("notify_errors", t.get("notify_errors", True))),
            "allow_control": bool(data.get("allow_control", t.get("allow_control", True))),
        })
        _config["telegrams"][tg_id] = t
        save_config()
        return _public_telegram(t)


def delete_telegram(tg_id: str):
    with _lock:
        _load()
        _config["telegrams"].pop(tg_id, None)
        for b in _config["bots"].values():
            if tg_id in (b.get("telegram_ids") or []):
                b["telegram_ids"].remove(tg_id)
        save_config()


# ------------------------------------------------------------------- bot
def list_bots() -> list:
    with _lock:
        _load()
        return sorted((dict(b) for b in _config["bots"].values()), key=lambda x: x.get("created_at", ""))


def get_bot(bot_id: str) -> dict | None:
    with _lock:
        _load()
        b = _config["bots"].get(bot_id)
        return dict(b) if b else None


def upsert_bot(data: dict) -> dict:
    with _lock:
        _load()
        bot_id = data.get("id")
        if bot_id and bot_id not in _config["bots"]:
            raise ValueError("Không tìm thấy bot")
        old = _config["bots"].get(bot_id) or {}
        bs = _state["bots"].get(bot_id) or {}
        has_open = bool(bs.get("open_trade"))

        account_id = data.get("account_id") or old.get("account_id")
        if account_id not in _config["accounts"]:
            raise ValueError("Chọn tài khoản sàn")
        symbol = (data.get("symbol") or old.get("symbol") or "").strip().upper()
        if not symbol.isalnum() or not symbol.endswith("USDT"):
            raise ValueError("Cặp coin phải dạng XXXUSDT (vd BTCUSDT)")
        method = str(data.get("method") or old.get("method") or "4")
        if method not in METHODS:
            raise ValueError("Chiến lược không hợp lệ")
        if has_open and (account_id != old.get("account_id") or symbol != old.get("symbol") or method != old.get("method")):
            raise ValueError("Bot đang có lệnh mở — đóng lệnh trước khi đổi tài khoản / cặp coin / chiến lược")
        for other in _config["bots"].values():
            if other["id"] != bot_id and other.get("account_id") == account_id and other.get("symbol") == symbol:
                raise ValueError(f"Tài khoản này đã có bot khác chạy {symbol} — mỗi tài khoản chỉ 1 bot / cặp coin")

        def num(key, default, lo, hi, label):
            v = data.get(key, old.get(key, default))
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{label} phải là số")
            if not (lo <= v <= hi):
                raise ValueError(f"{label} phải trong khoảng {lo}–{hi}")
            return v

        capital = num("capital", 50, 1, 10_000_000, "Vốn phân bổ")
        leverage = int(num("leverage", settings.LEVERAGE, 1, 125, "Đòn bẩy"))
        wallet_pct = num("wallet_pct", settings.WALLET_PCT, 0.01, 1.0, "% vốn mỗi lệnh")
        ex_stop = data.get("exchange_stop", old.get("exchange_stop", "trail"))
        if ex_stop not in EXCHANGE_STOP_MODES:
            raise ValueError("Chế độ stop trên sàn không hợp lệ")
        tg_ids = data.get("telegram_ids", old.get("telegram_ids", []))
        tg_ids = [t for t in (tg_ids or []) if t in _config["telegrams"]]

        if not bot_id:
            bot_id = _new_id("bot")
            old = {"id": bot_id, "created_at": now_iso(), "status": "stopped"}
        b = dict(old)
        b.update({
            "name": (data.get("name") or old.get("name") or f"{symbol} PP{method}").strip(),
            "account_id": account_id,
            "symbol": symbol,
            "method": method,
            "capital": capital,
            "leverage": leverage,
            "wallet_pct": wallet_pct,
            "exchange_stop": ex_stop,
            "telegram_ids": tg_ids,
        })
        _config["bots"][bot_id] = b
        st = _state["bots"].setdefault(bot_id, {})
        if not st.get("started_at"):
            st["balance"] = capital
        elif not has_open and data.get("reset_capital"):
            st["balance"] = capital
        save_config()
        save_state()
        return dict(b)


def set_bot_status(bot_id: str, status: str):
    if status not in BOT_STATUSES:
        raise ValueError("Trạng thái không hợp lệ")
    with _lock:
        _load()
        b = _config["bots"].get(bot_id)
        if not b:
            raise ValueError("Không tìm thấy bot")
        b["status"] = status
        st = _state["bots"].setdefault(bot_id, {})
        if status == "running" and not st.get("started_at"):
            st["started_at"] = now_iso()
            st.setdefault("balance", b["capital"])
        save_config()
        save_state()


def delete_bot(bot_id: str):
    with _lock:
        _load()
        if (_state["bots"].get(bot_id) or {}).get("open_trade"):
            raise ValueError("Bot đang có lệnh mở — đóng lệnh trước khi xoá")
        _config["bots"].pop(bot_id, None)
        _state["bots"].pop(bot_id, None)
        save_config()
        save_state()


def bot_state(bot_id: str) -> dict:
    """Trả dict trạng thái SỐNG của bot (engine sửa trực tiếp, rồi gọi save_state)."""
    with _lock:
        _load()
        st = _state["bots"].setdefault(bot_id, {})
        st.setdefault("balance", float((_config["bots"].get(bot_id) or {}).get("capital") or 0))
        st.setdefault("open_trade", None)
        st.setdefault("trades", [])
        st.setdefault("last_trade", None)
        st.setdefault("cb", {"losses": 0, "light_until": None, "heavy_until": None})
        return st


# ----------------------------------------------------- nhật ký + snapshot
def add_event(kind: str, text: str, bot_id: str = None):
    with _lock:
        _load()
        _state["events"].append({"t": now_iso(), "kind": kind, "text": text, "bot_id": bot_id})
        del _state["events"][:-MAX_EVENTS]
        save_state()


def events(limit: int = 100) -> list:
    with _lock:
        _load()
        return list(reversed(_state["events"][-limit:]))


def add_snapshot(snap: dict):
    with _lock:
        _load()
        _state["snapshots"].append(snap)
        del _state["snapshots"][:-MAX_SNAPSHOTS]
        save_state()


def snapshots(limit: int = 200) -> list:
    with _lock:
        _load()
        return list(_state["snapshots"][-limit:])


def lock():
    return _lock
