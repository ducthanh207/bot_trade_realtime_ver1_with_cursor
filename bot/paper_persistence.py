# -*- coding: utf-8 -*-
"""Lưu/khôi phục trạng thái paper trade ra file JSON để giữ qua lần deploy/pull."""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "paper_state.json"

_restore_pending = False


def _parse_dt(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v
    try:
        s = str(v).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _serialize_for_save(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize_for_save(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_for_save(x) for x in obj]
    return obj


def save_paper_state():
    """Ghi trạng thái paper hiện tại ra file."""
    try:
        from bot import state
        open_trade = state.get_paper_open_trade()
        started = state.get_paper_started_at()
        data = {
            "paper_initial_capital": state.get_paper_initial_capital(),
            "paper_balance": state.get_paper_balance(),
            "paper_started_at": started.isoformat() if started else None,
            "paper_status": state.get_paper_status(),
            "paper_open_trade": _serialize_for_save(open_trade) if open_trade else None,
            "paper_trades": _serialize_for_save(state.get_paper_trades()),
            "paper_last_trade": _serialize_for_save(state.get_paper_last_trade()) if state.get_paper_last_trade() else None,
            "paper_leverage": state.get_paper_leverage(),
            "paper_wallet_pct": state.get_paper_wallet_pct(),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def load_paper_state():
    """
    Đọc file và áp dụng vào state. Trả về True nếu đã khôi phục và có lệnh đang mở.
    """
    global _restore_pending
    if not STATE_FILE.exists():
        return False
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    try:
        from bot import state
        state.set_paper_initial_capital(float(data.get("paper_initial_capital") or 0))
        state.set_paper_balance(float(data.get("paper_balance") or 0))
        started = _parse_dt(data.get("paper_started_at"))
        state.set_paper_started_at(started)
        state.set_paper_status(str(data.get("paper_status") or "stopped"))
        trades_raw = data.get("paper_trades") or []
        trades = []
        for t in trades_raw:
            tt = dict(t)
            tt["entry_time"] = _parse_dt(t.get("entry_time"))
            tt["exit_time"] = _parse_dt(t.get("exit_time"))
            trades.append(tt)
        state.restore_paper_trades(trades)
        lev = data.get("paper_leverage")
        if lev is not None:
            state.set_paper_leverage(float(lev))
        wct = data.get("paper_wallet_pct")
        if wct is not None:
            state.set_paper_wallet_pct(float(wct))
        last = data.get("paper_last_trade")
        if last:
            last = dict(last)
            last["entry_time"] = _parse_dt(last.get("entry_time"))
            last["exit_time"] = _parse_dt(last.get("exit_time"))
            state.set_paper_last_trade(last)
        open_trade = data.get("paper_open_trade")
        if open_trade:
            open_trade = dict(open_trade)
            open_trade["entry_time"] = _parse_dt(open_trade.get("entry_time"))
            if open_trade.get("last_sl_check"):
                open_trade["last_sl_check"] = _parse_dt(open_trade["last_sl_check"])
            state.set_paper_open_trade(open_trade)
            _restore_pending = True
            return True
        return False
    except Exception:
        return False


def get_restore_pending():
    return _restore_pending


def clear_restore_pending():
    global _restore_pending
    _restore_pending = False
