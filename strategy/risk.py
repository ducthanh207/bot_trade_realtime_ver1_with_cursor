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


def refresh_atr_from_1h(open_trade: dict, df_1h: pd.DataFrame) -> None:
    """
    Cập nhật open_trade['atr'] theo ATR nến 1H đã đóng mới nhất (iloc[-2]).
    Trailing (check_atr_trailing) dùng atr * ATR_MULTIPLIER — cập nhật mỗi vòng lặp
    để có thể thoát theo biến động 1H khi nến 4H chưa đóng.
    """
    if not open_trade or df_1h is None or df_1h.empty or len(df_1h) < 3:
        return
    try:
        atr = float(df_1h.iloc[-2]["ATR"])
        if pd.notna(atr) and atr > 0:
            open_trade["atr"] = atr
    except (KeyError, TypeError, ValueError, IndexError):
        pass


def atr_1h_at_entry(df_1h: pd.DataFrame, fallback: float) -> float:
    """ATR từ nến 1H đã đóng; nếu thiếu dữ liệu thì dùng fallback (vd ATR 4H)."""
    if df_1h is None or df_1h.empty or len(df_1h) < 3:
        return fallback
    try:
        atr = float(df_1h.iloc[-2]["ATR"])
        if pd.notna(atr) and atr > 0:
            return atr
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    return fallback


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
    mult = open_trade.get("atr_multiplier_override") or settings.ATR_MULTIPLIER
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


def m3_adx_zone(adx_value: float):
    """Tra ve (allow_entry, size_multiplier) theo ADX 3 vung."""
    from config import settings
    if adx_value < settings.M3_ADX_LOW:
        return False, 0.0
    if adx_value < settings.M3_ADX_HIGH:
        return True, settings.M3_ADX_MID_SIZE
    return True, 1.0


def m3_streak_multiplier(consecutive_losses: int) -> float:
    from config import settings
    return max(settings.M3_SIZING_FLOOR, 1.0 - consecutive_losses * settings.M3_SIZING_STEP)


def m3_atr_multiplier(entry_time) -> float:
    """Grace period: dung multiplier rong hon trong M3_ATR_GRACE_HOURS dau."""
    from config import settings
    from datetime import datetime, timezone
    try:
        now = datetime.now(timezone.utc)
        if hasattr(entry_time, "tzinfo") and entry_time.tzinfo is not None:
            elapsed_hours = (now - entry_time).total_seconds() / 3600
        else:
            elapsed_hours = settings.M3_ATR_GRACE_HOURS + 1
        if elapsed_hours < settings.M3_ATR_GRACE_HOURS:
            return settings.M3_ATR_MULTIPLIER_GRACE
    except Exception:
        pass
    return settings.M3_ATR_MULTIPLIER


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
