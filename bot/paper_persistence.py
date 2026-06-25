# -*- coding: utf-8 -*-
"""Lưu/khôi phục trạng thái paper trade ra file JSON để giữ qua lần deploy/pull."""

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "paper_state.json"

_restore_pending = False
_restore_pending_paper2 = False
_restore_pending_paper3 = False


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
        open2 = state.get_paper2_open_trade()
        started2 = state.get_paper2_started_at()
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
            "paper2_initial_capital": state.get_paper2_initial_capital(),
            "paper2_balance": state.get_paper2_balance(),
            "paper2_started_at": started2.isoformat() if started2 else None,
            "paper2_status": state.get_paper2_status(),
            "paper2_open_trade": _serialize_for_save(open2) if open2 else None,
            "paper2_trades": _serialize_for_save(state.get_paper2_trades()),
            "paper2_last_trade": _serialize_for_save(state.get_paper2_last_trade()) if state.get_paper2_last_trade() else None,
            "paper2_leverage": state.get_paper2_leverage(),
            "paper2_wallet_pct": state.get_paper2_wallet_pct(),
            "paper2_lookback_trades": state.get_paper2_lookback_trades(),
            "paper3_initial_capital": state.get_paper3_initial_capital(),
            "paper3_balance": state.get_paper3_balance(),
            "paper3_started_at": state.get_paper3_started_at().isoformat() if state.get_paper3_started_at() else None,
            "paper3_status": state.get_paper3_status(),
            "paper3_open_trade": _serialize_for_save(state.get_paper3_open_trade()) if state.get_paper3_open_trade() else None,
            "paper3_trades": _serialize_for_save(state.get_paper3_trades()),
            "paper3_last_trade": _serialize_for_save(state.get_paper3_last_trade()) if state.get_paper3_last_trade() else None,
            "paper3_leverage": state.get_paper3_leverage(),
            "paper3_wallet_pct": state.get_paper3_wallet_pct(),
            "paper3_consecutive_losses": state.get_paper3_consecutive_losses(),
            "paper3_cb_light_until": state.get_paper3_cb_light_until().isoformat() if state.get_paper3_cb_light_until() else None,
            "paper3_cb_heavy_until": state.get_paper3_cb_heavy_until().isoformat() if state.get_paper3_cb_heavy_until() else None,
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=0)
    except Exception:
        pass


def load_paper_state():
    """
    Đọc file và áp dụng vào state. Trả về True nếu đã khôi phục và có lệnh đang mở (paper 1 hoặc 2).
    """
    global _restore_pending, _restore_pending_paper2
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
        if data.get("paper2_initial_capital") is not None:
            state.set_paper2_initial_capital(float(data.get("paper2_initial_capital") or 0))
        if data.get("paper2_balance") is not None:
            state.set_paper2_balance(float(data.get("paper2_balance") or 0))
        started2 = _parse_dt(data.get("paper2_started_at"))
        state.set_paper2_started_at(started2)
        state.set_paper2_status(str(data.get("paper2_status") or "stopped"))
        trades2_raw = data.get("paper2_trades") or []
        trades2 = []
        for t in trades2_raw:
            tt = dict(t)
            tt["entry_time"] = _parse_dt(t.get("entry_time"))
            tt["exit_time"] = _parse_dt(t.get("exit_time"))
            trades2.append(tt)
        state.restore_paper2_trades(trades2)
        lev2 = data.get("paper2_leverage")
        if lev2 is not None:
            state.set_paper2_leverage(float(lev2))
        wct2 = data.get("paper2_wallet_pct")
        if wct2 is not None:
            state.set_paper2_wallet_pct(float(wct2))
        lb2 = data.get("paper2_lookback_trades")
        if lb2 is not None:
            try:
                state.set_paper2_lookback_trades(int(lb2))
            except (TypeError, ValueError):
                state.set_paper2_lookback_trades(None)
        last2 = data.get("paper2_last_trade")
        if last2:
            last2 = dict(last2)
            last2["entry_time"] = _parse_dt(last2.get("entry_time"))
            last2["exit_time"] = _parse_dt(last2.get("exit_time"))
            state.set_paper2_last_trade(last2)
        open2 = data.get("paper2_open_trade")
        if open2:
            open2 = dict(open2)
            open2["entry_time"] = _parse_dt(open2.get("entry_time"))
            if open2.get("last_sl_check"):
                open2["last_sl_check"] = _parse_dt(open2["last_sl_check"])
            state.set_paper2_open_trade(open2)
            _restore_pending_paper2 = True
        if data.get("paper3_initial_capital") is not None:
            state.set_paper3_initial_capital(float(data.get("paper3_initial_capital") or 0))
        if data.get("paper3_balance") is not None:
            state.set_paper3_balance(float(data.get("paper3_balance") or 0))
        started3 = _parse_dt(data.get("paper3_started_at"))
        state.set_paper3_started_at(started3)
        state.set_paper3_status(str(data.get("paper3_status") or "stopped"))
        trades3_raw = data.get("paper3_trades") or []
        trades3 = []
        for t in trades3_raw:
            tt = dict(t)
            tt["entry_time"] = _parse_dt(t.get("entry_time"))
            tt["exit_time"] = _parse_dt(t.get("exit_time"))
            trades3.append(tt)
        state.restore_paper3_trades(trades3)
        lev3 = data.get("paper3_leverage")
        if lev3 is not None:
            state.set_paper3_leverage(float(lev3))
        wct3 = data.get("paper3_wallet_pct")
        if wct3 is not None:
            state.set_paper3_wallet_pct(float(wct3))
        try:
            state.set_paper3_consecutive_losses(int(data.get("paper3_consecutive_losses") or 0))
        except (TypeError, ValueError):
            pass
        cl_until = _parse_dt(data.get("paper3_cb_light_until"))
        if cl_until:
            state.set_paper3_cb_light_until(cl_until)
        ch_until = _parse_dt(data.get("paper3_cb_heavy_until"))
        if ch_until:
            state.set_paper3_cb_heavy_until(ch_until)
        last3 = data.get("paper3_last_trade")
        if last3:
            last3 = dict(last3)
            last3["entry_time"] = _parse_dt(last3.get("entry_time"))
            last3["exit_time"] = _parse_dt(last3.get("exit_time"))
            state.set_paper3_last_trade(last3)
        open3 = data.get("paper3_open_trade")
        if open3:
            open3 = dict(open3)
            open3["entry_time"] = _parse_dt(open3.get("entry_time"))
            if open3.get("last_sl_check"):
                open3["last_sl_check"] = _parse_dt(open3["last_sl_check"])
            state.set_paper3_open_trade(open3)
            _restore_pending_paper3 = True
        if _restore_pending or _restore_pending_paper2 or _restore_pending_paper3:
            return True
        return False
    except Exception:
        return False


def get_restore_pending():
    return _restore_pending


def clear_restore_pending():
    global _restore_pending, _restore_pending_paper2, _restore_pending_paper3
    _restore_pending = False
    _restore_pending_paper2 = False
    _restore_pending_paper3 = False


def clear_restore_pending_paper():
    global _restore_pending
    _restore_pending = False


def clear_restore_pending_paper2():
    global _restore_pending_paper2
    _restore_pending_paper2 = False


def get_restore_pending_paper2():
    return _restore_pending_paper2


def clear_restore_pending_paper3():
    global _restore_pending_paper3
    _restore_pending_paper3 = False


def get_restore_pending_paper3():
    return _restore_pending_paper3
