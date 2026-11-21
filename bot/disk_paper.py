# -*- coding: utf-8 -*-
"""
[2026-11-21] Paper trade chung cho mọi đĩa chiến lược không có trang Paper riêng
(PP6, PP6.1, PP7 và mọi đĩa nạp từ web). Paper 1–5 giữ nguyên trang + state cũ.

- Mỗi đĩa có một "khe" paper riêng: vốn, đòn bẩy, % vốn, cặp coin, lệnh đang mở, lịch sử, circuit breaker.
- Mặc định DỪNG. Chỉ admin (đăng nhập như /live) bật được trên trang Chiến lược.
- Chạy cùng vòng lặp bot/paper_loop.py, cùng hàm bot/slot_engine.step_slot như Paper 1–5 → cùng logic vào/ra lệnh.
- Không bao giờ đặt lệnh thật. Lên live vẫn là thao tác riêng ở /live.
- Lưu ra data/disk_paper.json (giữ qua restart / git pull).
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import settings

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "disk_paper.json"
OWN_PAGE_IDS = ("1", "2", "3", "4", "5")  # đã có trang Paper riêng (/paper .. /paper5)
MAX_TRADES = 1000
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")
_DT_KEYS = ("entry_time", "exit_time", "last_sl_check", "cvd_last_h", "cvd_tight_at", "entry_4h_ts")

_lock = threading.RLock()
_state: dict = {}
_loaded = False


def _now():
    return datetime.now(timezone.utc)


def _ser(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _ser(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_ser(x) for x in v]
    try:
        import numpy as np
        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass
    return v


def _parse_ts(v):
    if v is None or hasattr(v, "isoformat"):
        return v
    try:
        return pd.Timestamp(str(v)).to_pydatetime()
    except Exception:
        return None


def _fix_trade(t: dict | None):
    if not t:
        return t
    t = dict(t)
    for k in _DT_KEYS:
        if t.get(k) is not None:
            v = _parse_ts(t[k])
            t[k] = pd.Timestamp(v) if k in ("entry_4h_ts", "cvd_last_h", "cvd_tight_at") and v is not None else v
    return t


def _default(disk_id: str) -> dict:
    cap = float(getattr(settings, "CAPITAL_START", 50.0))
    return {
        "id": disk_id, "status": "stopped", "symbol": settings.SYMBOL,
        "initial_capital": cap, "balance": cap,
        "leverage": float(settings.LEVERAGE), "wallet_pct": float(settings.WALLET_PCT),
        "open_trade": None, "last_trade": None, "trades": [],
        "losses": 0, "cb_light": None, "cb_heavy": None, "started_at": None,
    }


def load():
    global _loaded
    with _lock:
        _loaded = True
        try:
            raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for did, st in (raw.get("slots") or {}).items():
            s = _default(did)
            s.update({k: v for k, v in st.items() if k in s})
            s["open_trade"] = _fix_trade(s.get("open_trade"))
            s["last_trade"] = _fix_trade(s.get("last_trade"))
            s["trades"] = [_fix_trade(t) for t in (s.get("trades") or [])]
            s["cb_light"] = _parse_ts(s.get("cb_light"))
            s["cb_heavy"] = _parse_ts(s.get("cb_heavy"))
            _state[did] = s


def save():
    with _lock:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"slots": _ser(_state)}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)


def _ensure_loaded():
    if not _loaded:
        load()


def slot(disk_id: str) -> dict:
    _ensure_loaded()
    with _lock:
        s = _state.get(disk_id)
        if s is None:
            s = _state[disk_id] = _default(disk_id)
        return s


def paper_disks():
    from strategy.disks import sorted_disks
    return [d for d in sorted_disks() if d.id not in OWN_PAGE_IDS]


def active_ids():
    """Khe đang chạy / tạm dừng (tạm dừng vẫn xét thoát lệnh) của các đĩa còn tồn tại."""
    _ensure_loaded()
    ids = {d.id for d in paper_disks()}
    with _lock:
        return [k for k, s in _state.items() if k in ids and s.get("status") in ("running", "paused")]


# ---------------------------------------------------------------- điều khiển (web, admin)
def start(disk_id: str, capital=None, leverage=None, wallet_pct=None, symbol=None):
    from strategy.disks import find_disk
    if disk_id in OWN_PAGE_IDS or find_disk(disk_id) is None:
        raise ValueError("Không có đĩa này (Paper 1–5 dùng trang riêng)")
    with _lock:
        s = slot(disk_id)
        if symbol:
            sym = str(symbol).strip().upper()
            if not _SYMBOL_RE.match(sym):
                raise ValueError("Cặp coin không hợp lệ (vd BTCUSDT)")
            if s.get("open_trade") and sym != s["symbol"]:
                raise ValueError("Đang có lệnh mở, chưa đổi cặp được")
            s["symbol"] = sym
        if leverage is not None:
            lev = float(leverage)
            if not 1 <= lev <= 125:
                raise ValueError("Đòn bẩy 1–125")
            s["leverage"] = lev
        if wallet_pct is not None:
            w = float(wallet_pct)
            w = w / 100.0 if w > 1 else w
            if not 0 < w <= 1:
                raise ValueError("% vốn mỗi lệnh 1–100")
            s["wallet_pct"] = w
        if capital is not None and not s.get("trades") and not s.get("open_trade"):
            c = float(capital)
            if not 1 <= c <= 1e9:
                raise ValueError("Vốn không hợp lệ")
            s["initial_capital"] = s["balance"] = c
        s["status"] = "running"
        s["started_at"] = s.get("started_at") or _now().isoformat()
        save()
        return s


def set_status(disk_id: str, status: str):
    if status not in ("running", "paused", "stopped"):
        raise ValueError("Trạng thái không hợp lệ")
    with _lock:
        s = slot(disk_id)
        s["status"] = status
        save()
        return s


def reset(disk_id: str, capital=None):
    """Xoá lịch sử + đặt lại vốn. Chỉ khi không có lệnh mở."""
    with _lock:
        s = slot(disk_id)
        if s.get("open_trade"):
            raise ValueError("Đang có lệnh mở, đóng lệnh trước")
        cap = float(capital) if capital not in (None, "") else float(s["initial_capital"])
        if not 1 <= cap <= 1e9:
            raise ValueError("Vốn không hợp lệ")
        keep = {k: s[k] for k in ("symbol", "leverage", "wallet_pct")}
        s.clear()
        s.update(_default(disk_id))
        s.update(keep)
        s["initial_capital"] = s["balance"] = cap
        save()
        return s


def close_now(disk_id: str, price: float, reason: str = "MANUAL"):
    """Đóng lệnh paper đang mở theo giá thị trường (phí taker như bot)."""
    from bot.paper_fees import linear_taker_fee_usdt
    from strategy.risk import limit_pnl_and_exit_price, max_loss_from_capital
    with _lock:
        s = slot(disk_id)
        ot = s.get("open_trade")
        if not ot:
            raise ValueError("Không có lệnh mở")
        entry, size, side = float(ot["entry_price"]), float(ot["size"]), ot["side"]
        pnl_raw = (price - entry) * size if side == "LONG" else (entry - price) * size
        pnl, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss_from_capital(ot))
        px = px_lim if px_lim is not None else price
        pnl -= linear_taker_fee_usdt(size, px, float(settings.TAKER_FEE))
        bal = float(s["balance"])
        closed = {
            "entry_time": ot.get("entry_time"), "exit_time": _now(), "entry_price": entry, "exit_price": px,
            "side": side, "size": size, "margin": ot.get("margin"), "profit": pnl,
            "capital_before": bal, "capital_after": bal + pnl, "exit_reason": reason,
            "entry_rsi": ot.get("entry_rsi"), "paper_slot": f"disk:{disk_id}",
        }
        s["open_trade"] = None
        s["last_trade"] = closed
        s["trades"].append(closed)
        del s["trades"][:-MAX_TRADES]
        s["balance"] = bal + pnl
        save()
        return closed


# ---------------------------------------------------------------- API cho step_slot
def make_api(disk_id: str) -> dict:
    s = slot(disk_id)
    tag = f"disk:{disk_id}"

    def set_open(v):
        s["open_trade"] = v

    def append_trade(t):
        s["trades"].append(t)
        del s["trades"][:-MAX_TRADES]

    def on_opened(ot):
        save()
        try:
            from telegram.notifier import notify_trade_opened
            if ot:
                notify_trade_opened(ot, source="loop", paper_slot=tag)
        except Exception:
            pass

    def on_closed(closed):
        save()
        try:
            from telegram.notifier import notify_trade_closed
            notify_trade_closed(closed, source="loop", paper_slot=tag)
        except Exception:
            pass

    cb = {
        "get_losses": lambda: int(s.get("losses") or 0),
        "set_losses": lambda v: s.__setitem__("losses", int(v)),
        "get_light": lambda: s.get("cb_light"),
        "set_light": lambda v: s.__setitem__("cb_light", v),
        "get_heavy": lambda: s.get("cb_heavy"),
        "set_heavy": lambda v: s.__setitem__("cb_heavy", v),
        "get_trades": lambda: s["trades"],
    }
    return {
        "get_status": lambda: s.get("status", "stopped"),
        "get_balance": lambda: float(s["balance"]),
        "set_balance": lambda v: s.__setitem__("balance", float(v)),
        "get_open": lambda: s.get("open_trade"),
        "set_open": set_open,
        "append_trade": append_trade,
        "set_last": lambda v: s.__setitem__("last_trade", v),
        "get_lev": lambda: float(s["leverage"]),
        "get_wct": lambda: float(s["wallet_pct"]),
        "lookback": lambda: min(max(int(getattr(settings, "LOOKBACK_TRADES", 15)), 1), 200),
        "cb": cb,
        "on_opened": on_opened,
        "on_closed": on_closed,
    }


def step_all(get_market):
    """
    Gọi mỗi vòng paper_loop. get_market(symbol, need_daily) → MarketContext (None nếu thiếu dữ liệu).
    Trả số khe đã chạy.
    """
    from bot.slot_engine import step_slot
    from strategy.disks import find_disk
    n = 0
    for did in active_ids():
        d = find_disk(did)
        if d is None:
            continue
        s = slot(did)
        mkt = get_market(s["symbol"], d.daily)
        if mkt is None or not mkt.ok:
            continue
        with _lock:
            step_slot(f"disk:{did}", did, make_api(did), mkt)
        n += 1
    return n


def public(disk_id: str, last_price: float | None = None) -> dict:
    s = slot(disk_id)
    ot = s.get("open_trade")
    upnl = None
    if ot and last_price:
        e, z = float(ot["entry_price"]), float(ot["size"])
        upnl = (last_price - e) * z if ot["side"] == "LONG" else (e - last_price) * z
    trades = s.get("trades") or []
    wins = sum(1 for t in trades if float(t.get("profit") or 0) > 0)
    return _ser({
        "id": disk_id, "status": s.get("status"), "symbol": s.get("symbol"),
        "initial_capital": s.get("initial_capital"), "balance": s.get("balance"),
        "leverage": s.get("leverage"), "wallet_pct": s.get("wallet_pct"),
        "open_trade": {k: ot.get(k) for k in ("side", "entry_time", "entry_price", "size", "margin", "trail_stop", "atr")} if ot else None,
        "unrealized_pnl": upnl, "n_trades": len(trades), "wins": wins,
        "trades": list(reversed(trades[-200:])), "cb_heavy": s.get("cb_heavy"), "cb_light": s.get("cb_light"),
        "started_at": s.get("started_at"),
    })
