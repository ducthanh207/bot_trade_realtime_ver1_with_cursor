# -*- coding: utf-8 -*-
"""Trạng thái bot: real (sau này) + paper trade (vốn ảo, từ ngày kích hoạt)."""

from datetime import datetime, timezone

try:
    from config import settings
    _tz_app = getattr(settings, "GMT7", timezone.utc)
except Exception:
    _tz_app = timezone.utc

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
# Quy tắc vốn (khóa từ web): None = dùng config
_paper_leverage = None
_paper_wallet_pct = None

# ---------- Paper trade 2 (phương pháp 2 — tách biệt với paper slot 1) ----------
_paper2_initial_capital = 0.0
_paper2_balance = 0.0
_paper2_started_at = None
_paper2_status = "stopped"
_paper2_open_trade = None
_paper2_trades = []
_paper2_last_trade = None
_paper2_leverage = None
_paper2_wallet_pct = None
# Lookback %change (số lệnh đã đóng trong cửa sổ tính trung bình) — None = dùng config LOOKBACK_TRADES
_paper2_lookback_trades = None


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
    _bot_started_at = dt or datetime.now(_tz_app)


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


def restore_paper_trades(trades: list):
    """Khôi phục danh sách lệnh đã đóng (sau khi load từ file)."""
    global _paper_trades
    _paper_trades = list(trades) if trades else []


def set_paper_last_trade(trade: dict or None):
    global _paper_last_trade
    _paper_last_trade = trade


def get_paper_last_trade():
    return _paper_last_trade


def get_paper_leverage():
    return _paper_leverage


def set_paper_leverage(value: float or None):
    global _paper_leverage
    _paper_leverage = float(value) if value is not None else None


def get_paper_wallet_pct():
    return _paper_wallet_pct


def set_paper_wallet_pct(value: float or None):
    global _paper_wallet_pct
    _paper_wallet_pct = float(value) if value is not None else None


def paper_start(initial_capital: float):
    """Gọi khi bấm Kích hoạt: chỉ start/resume bot, không xóa lịch sử lệnh."""
    global _paper_initial_capital, _paper_balance, _paper_started_at, _paper_status
    global _paper_open_trade
    _paper_open_trade = None
    _paper_status = "running"
    if _paper_started_at is None:
        _paper_initial_capital = float(initial_capital)
        _paper_balance = float(initial_capital)
        _paper_started_at = datetime.now(_tz_app)
    else:
        _paper_initial_capital = float(initial_capital) if initial_capital and initial_capital > 0 else _paper_initial_capital


def paper_clear_history():
    """Gọi khi bấm Xóa toàn bộ: xóa toàn bộ lịch sử lệnh, reset về trạng thái ban đầu."""
    global _paper_trades, _paper_last_trade, _paper_open_trade
    global _paper_initial_capital, _paper_balance, _paper_started_at, _paper_status
    _paper_trades = []
    _paper_last_trade = None
    _paper_open_trade = None
    _paper_started_at = None
    _paper_status = "stopped"
    _paper_balance = _paper_initial_capital if _paper_initial_capital else 0


def paper_pause():
    global _paper_status
    _paper_status = "paused"


def paper_stop():
    global _paper_status
    _paper_status = "stopped"


# ---------- Paper trade 2 ----------
def set_paper2_initial_capital(value: float):
    global _paper2_initial_capital
    _paper2_initial_capital = value


def get_paper2_initial_capital() -> float:
    return _paper2_initial_capital


def set_paper2_balance(value: float):
    global _paper2_balance
    _paper2_balance = value


def get_paper2_balance() -> float:
    return _paper2_balance


def set_paper2_started_at(dt: datetime or None):
    global _paper2_started_at
    _paper2_started_at = dt


def get_paper2_started_at():
    return _paper2_started_at


def set_paper2_status(value: str):
    global _paper2_status
    if value in ("stopped", "running", "paused"):
        _paper2_status = value


def get_paper2_status() -> str:
    return _paper2_status


def set_paper2_open_trade(trade: dict or None):
    global _paper2_open_trade
    _paper2_open_trade = trade


def get_paper2_open_trade():
    return _paper2_open_trade


def append_paper2_trade(trade: dict):
    global _paper2_trades
    _paper2_trades.append(trade)


def get_paper2_trades():
    return list(_paper2_trades)


def restore_paper2_trades(trades: list):
    global _paper2_trades
    _paper2_trades = list(trades) if trades else []


def set_paper2_last_trade(trade: dict or None):
    global _paper2_last_trade
    _paper2_last_trade = trade


def get_paper2_last_trade():
    return _paper2_last_trade


def get_paper2_leverage():
    return _paper2_leverage


def set_paper2_leverage(value: float or None):
    global _paper2_leverage
    _paper2_leverage = float(value) if value is not None else None


def get_paper2_wallet_pct():
    return _paper2_wallet_pct


def set_paper2_wallet_pct(value: float or None):
    global _paper2_wallet_pct
    _paper2_wallet_pct = float(value) if value is not None else None


def get_paper2_lookback_trades():
    """None → bot dùng settings.LOOKBACK_TRADES. Đơn vị: số lệnh (lookback), không phải số nến."""
    return _paper2_lookback_trades


def set_paper2_lookback_trades(value):
    global _paper2_lookback_trades
    if value is None:
        _paper2_lookback_trades = None
    else:
        _paper2_lookback_trades = int(value)


def paper2_start(initial_capital: float):
    global _paper2_initial_capital, _paper2_balance, _paper2_started_at, _paper2_status
    global _paper2_open_trade
    _paper2_open_trade = None
    _paper2_status = "running"
    if _paper2_started_at is None:
        _paper2_initial_capital = float(initial_capital)
        _paper2_balance = float(initial_capital)
        _paper2_started_at = datetime.now(_tz_app)
    else:
        _paper2_initial_capital = float(initial_capital) if initial_capital and initial_capital > 0 else _paper2_initial_capital


def paper2_clear_history():
    global _paper2_trades, _paper2_last_trade, _paper2_open_trade
    global _paper2_initial_capital, _paper2_balance, _paper2_started_at, _paper2_status
    _paper2_trades = []
    _paper2_last_trade = None
    _paper2_open_trade = None
    _paper2_started_at = None
    _paper2_status = "stopped"
    _paper2_balance = _paper2_initial_capital if _paper2_initial_capital else 0


def paper2_pause():
    global _paper2_status
    _paper2_status = "paused"


def paper2_stop():
    global _paper2_status
    _paper2_status = "stopped"


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

    paper2_trades = get_paper2_trades()
    n2 = len(paper2_trades)
    wins2 = sum(1 for t in paper2_trades if float(t.get("profit", 0)) > 0)
    total_pnl2 = sum(float(t.get("profit", 0)) for t in paper2_trades)
    long_ct2 = sum(1 for t in paper2_trades if str(t.get("side", "")).upper() == "LONG")
    short_ct2 = n2 - long_ct2
    winrate2 = (wins2 / n2 * 100.0) if n2 else 0.0
    paper2_started = get_paper2_started_at()

    try:
        from config import settings as _fee_cfg
        from bot.paper_fees import slot_total_fees_usdt

        _tf = float(getattr(_fee_cfg, "TAKER_FEE", 0.0004))
        _paper_total_fees = slot_total_fees_usdt(paper_trades, get_paper_open_trade(), _tf)
        _paper2_total_fees = slot_total_fees_usdt(paper2_trades, get_paper2_open_trade(), _tf)
    except Exception:
        _paper_total_fees = 0.0
        _paper2_total_fees = 0.0

    return {
        "balance": get_balance(),
        "position": pos,
        "last_trade": get_last_trade(),
        "trades_today_count": len(get_trades_today()),
        "bot_started_at": started.isoformat() if started else None,
        "stop_requested": is_stop_requested(),
        # Paper (phương pháp 1)
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
        "paper_total_fees": _paper_total_fees,
        "paper_long_count": long_ct,
        "paper_short_count": short_ct,
        "paper_leverage": _paper_leverage,
        "paper_wallet_pct": _paper_wallet_pct,
        # Paper 2 (phương pháp 2)
        "paper2_initial_capital": get_paper2_initial_capital(),
        "paper2_balance": get_paper2_balance(),
        "paper2_started_at": paper2_started.isoformat() if paper2_started else None,
        "paper2_status": get_paper2_status(),
        "paper2_open_trade": get_paper2_open_trade(),
        "paper2_trades": paper2_trades,
        "paper2_last_trade": get_paper2_last_trade(),
        "paper2_trades_count": n2,
        "paper2_winrate": round(winrate2, 2),
        "paper2_total_pnl": round(total_pnl2, 2),
        "paper2_total_fees": _paper2_total_fees,
        "paper2_long_count": long_ct2,
        "paper2_short_count": short_ct2,
        "paper2_leverage": _paper2_leverage,
        "paper2_wallet_pct": _paper2_wallet_pct,
        "paper2_lookback_trades": _paper2_lookback_trades,
    }
