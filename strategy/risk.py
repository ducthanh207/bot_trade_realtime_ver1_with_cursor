# -*- coding: utf-8 -*-
"""Size, margin, ATR trailing, max loss, limit PnL."""

import pandas as pd

from config import settings


def size_and_margin(capital: float, entry: float, leverage: float = None, wallet_pct: float = None):
    leverage = leverage if leverage is not None else settings.LEVERAGE
    wallet_pct = wallet_pct if wallet_pct is not None else settings.WALLET_PCT
    margin = capital * wallet_pct
    notional = margin * leverage
    size = notional / entry if entry > 0 else 0
    return size, margin, notional


def check_atr_trailing(open_trade: dict, row_1m: pd.Series):
    """
    Trailing stop trên nến 1m. Trả (pnl_raw, exit_px) nếu hit, else (None, None).
    """
    side = open_trade["side"]
    entry = open_trade["entry_price"]
    size = open_trade["size"]
    atr = open_trade["atr"]
    high = row_1m["high"]
    low = row_1m["low"]
    mult = settings.ATR_MULTIPLIER
    trail_dist = atr * mult

    if side == "LONG":
        new_stop = low - trail_dist
        if new_stop > open_trade["trail_stop"]:
            open_trade["trail_stop"] = new_stop
        stop_px = open_trade["trail_stop"]
        if low <= stop_px:
            return (stop_px - entry) * size, stop_px
        return None, None
    else:
        new_stop = high + trail_dist
        if new_stop < open_trade["trail_stop"]:
            open_trade["trail_stop"] = new_stop
        stop_px = open_trade["trail_stop"]
        if high >= stop_px:
            return (entry - stop_px) * size, stop_px
        return None, None


def max_loss_from_capital(open_trade: dict) -> float:
    return open_trade["capital_before"] * settings.MAX_STOP_CAPITAL_PCT


def limit_pnl_and_exit_price(side: str, entry: float, size: float, pnl_raw: float, max_loss: float):
    """Giới hạn PnL không lỗ quá max_loss. Trả (pnl_limited, exit_px_override hoặc None)."""
    if pnl_raw >= -max_loss:
        return pnl_raw, None
    pnl_limited = -max_loss
    if side == "LONG":
        exit_px = entry - max_loss / size
    else:
        exit_px = entry + max_loss / size
    return pnl_limited, exit_px
