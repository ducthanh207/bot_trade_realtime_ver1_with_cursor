# -*- coding: utf-8 -*-
"""Trạng thái bot: real (sau này) + paper trade (vốn ảo, từ ngày kích hoạt)."""

from datetime import datetime, timezone

# ---------- Real trade (giữ cho sau) ----------
_balance = 0.0
_position = None
_open_trade = None
_last_trade = None
_trades_today = []
_bot_started_at = None
_stop_requested = False

# ---------- Paper trade ----------
_paper_initial_capital = 0.0
_paper_balance = 0.0
_paper_started_at = None  # datetime khi bấm Kích hoạt
_paper_status = "stopped"  # "stopped" | "running" | "paused"
_paper_open_trade = None   # dict giống open_trade (entry_price, size, side, atr, ...)
_paper_trades = []        # list các lệnh đã đóng
_paper_last_trade = None   # lệnh gần nhất đóng


def set_balance(value: float):
    global _balance
    _balance = value


def get_balance() -> float:
    return _balance


def set_position(pos: dict or None):
    global _position
    _position = pos


def get_position():
    return _position


def set_open_trade(trade: dict or None):
    global _open_trade
    _open_trade = trade


def get_open_trade():
    return _open_trade


def set_last_trade(trade: dict or None):
    global _last_trade
    _last_trade = trade


def get_last_trade():
    return _last_trade


def append_trade_today(trade: dict):
    global _trades_today
    _trades_today.append(trade)


def get_trades_today():
    return list(_trades_today)


def reset_trades_today():
    global _trades_today
    _trades_today = []


def set_bot_started_at(dt: datetime = None):
    global _bot_started_at
    _bot_started_at = dt or datetime.now(timezone.utc)


def get_bot_started_at():
    return _bot_started_at


def set_stop_requested(value: bool = True):
    global _stop_requested
    _stop_requested = value


def is_stop_requested() -> bool:
    return _stop_requested


# ---------- Paper trade ----------
def set_paper_initial_capital(value: float):
    global _paper_initial_capital
    _paper_initial_capital = value


def get_paper_initial_capital() -> float:
    return _paper_initial_capital


def set_paper_balance(value: float):
    global _paper_balance
    _paper_balance = value


def get_paper_balance() -> float:
    return _paper_balance


def set_paper_started_at(dt: datetime or None):
    global _paper_started_at
    _paper_started_at = dt


def get_paper_started_at():
    return _paper_started_at


def set_paper_status(value: str):
    global _paper_status
    if value in ("stopped", "running", "paused"):
        _paper_status = value


def get_paper_status() -> str:
    return _paper_status


def set_paper_open_trade(trade: dict or None):
    global _paper_open_trade
    _paper_open_trade = trade


def get_paper_open_trade():
    return _paper_open_trade


def append_paper_trade(trade: dict):
    global _paper_trades
    _paper_trades.append(trade)


def get_paper_trades():
    return list(_paper_trades)


def set_paper_last_trade(trade: dict or None):
    global _paper_last_trade
    _paper_last_trade = trade


def get_paper_last_trade():
    return _paper_last_trade


def paper_start(initial_capital: float):
    """Gọi khi bấm Kích hoạt: set vốn, ngày bắt đầu, status running, xóa lịch sử."""
    global _paper_initial_capital, _paper_balance, _paper_started_at, _paper_status
    global _paper_open_trade, _paper_trades, _paper_last_trade
    _paper_initial_capital = float(initial_capital)
    _paper_balance = float(initial_capital)
    _paper_started_at = datetime.now(timezone.utc)
    _paper_status = "running"
    _paper_open_trade = None
    _paper_trades = []
    _paper_last_trade = None


def paper_pause():
    global _paper_status
    _paper_status = "paused"


def paper_stop():
    global _paper_status
    _paper_status = "stopped"


def to_status_dict():
    """Dict cho web/Telegram. Ưu tiên paper trade."""
    pos = get_position()
    started = get_bot_started_at()
    # Paper
    paper_started = get_paper_started_at()
    paper_trades = get_paper_trades()
    n = len(paper_trades)
    wins = sum(1 for t in paper_trades if float(t.get("profit", 0)) > 0)
    total_pnl = sum(float(t.get("profit", 0)) for t in paper_trades)
    long_ct = sum(1 for t in paper_trades if str(t.get("side", "")).upper() == "LONG")
    short_ct = n - long_ct
    winrate = (wins / n * 100.0) if n else 0.0

    return {
        "balance": get_balance(),
        "position": pos,
        "last_trade": get_last_trade(),
        "trades_today_count": len(get_trades_today()),
        "bot_started_at": started.isoformat() if started else None,
        "stop_requested": is_stop_requested(),
        # Paper
        "paper_initial_capital": get_paper_initial_capital(),
        "paper_balance": get_paper_balance(),
        "paper_started_at": paper_started.isoformat() if paper_started else None,
        "paper_status": get_paper_status(),
        "paper_open_trade": get_paper_open_trade(),
        "paper_trades": paper_trades,
        "paper_last_trade": get_paper_last_trade(),
        "paper_trades_count": n,
        "paper_winrate": round(winrate, 2),
        "paper_total_pnl": round(total_pnl, 2),
        "paper_long_count": long_ct,
        "paper_short_count": short_ct,
    }
