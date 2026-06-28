# -*- coding: utf-8 -*-
"""
Ước tính các mức thoát (ATR trail, %change, early exit, stoploss max loss) để báo Telegram.
Không thay thế logic trong exit_engine — chỉ hiển thị.
"""

from typing import Any, Dict, Optional

import pandas as pd

from config import settings
from strategy.pct_change_avg import build_pct_change_avg_bands_series
from strategy.risk import max_loss_from_capital
from strategy.strategies.registry import uses_pct_change_bands


def build_exit_scenarios_dict(
    open_trade: dict,
    df_4h_raw: Optional[pd.DataFrame],
    lookback_trades: int,
) -> Dict[str, Any]:
    """Trả về dict mô tả các kịch bản thoát cho lệnh đang mở."""
    method = str(open_trade.get("trading_method") or getattr(settings, "TRADING_METHOD", "1")).strip()
    out: Dict[str, Any] = {
        "atr_trail_px": open_trade.get("trail_stop"),
        "pct_upper": None,
        "pct_lower": None,
        "pct_half_width_pct": None,
        "early_exit_hint": None,
        "stoploss_px": None,
        "method": method,
    }
    side = str(open_trade.get("side", "LONG")).upper()
    entry = float(open_trade.get("entry_price") or 0)
    size = float(open_trade.get("size") or 0)
    if size <= 0 or entry <= 0:
        return out

    max_loss = max_loss_from_capital(open_trade)
    if side == "LONG":
        out["stoploss_px"] = entry - max_loss / size
    else:
        out["stoploss_px"] = entry + max_loss / size

    if settings.RSI_EARLY_EXIT:
        if side == "LONG":
            out["early_exit_hint"] = (
                f"RSI cắt xuống EMA_RSI hoặc RSI < {settings.RSI_LONG_CUT}"
            )
        else:
            out["early_exit_hint"] = (
                f"RSI cắt lên EMA_RSI hoặc RSI > {settings.RSI_SHORT_CUT}"
            )
    else:
        out["early_exit_hint"] = "Early exit tắt (RSI_EARLY_EXIT=false)"

    if df_4h_raw is not None and not df_4h_raw.empty and uses_pct_change_bands(method):
        try:
            bands = build_pct_change_avg_bands_series(df_4h_raw, lookback_trades=lookback_trades)
            out["pct_upper"] = bands.get("upper")
            out["pct_lower"] = bands.get("lower")
            out["pct_half_width_pct"] = bands.get("band_half_width_pct")
        except Exception:
            pass

    return out


def format_exit_scenarios_text(sc: Dict[str, Any], side: str) -> str:
    """Chuỗi nhiều dòng cho Telegram."""
    method = str(sc.get("method", "1"))
    lines = [
        f"Chiến lược: Phương pháp {method}",
        "Kịch bản thoát (ước lượng):",
    ]
    atr = sc.get("atr_trail_px")
    if atr is not None:
        lines.append(f"  1) ATR trailing: {float(atr):.2f}")
    if uses_pct_change_bands(method):
        pu = sc.get("pct_upper")
        pl = sc.get("pct_lower")
        hw = sc.get("pct_half_width_pct")
        if pu is not None and pl is not None:
            lines.append(f"  2) %change band (±{hw}% nếu có): LONG→upper {float(pu):.2f} | SHORT→lower {float(pl):.2f}")
        else:
            lines.append("  2) %change: chưa tính được (thiếu dữ liệu 4H)")
    else:
        lines.append("  2) %change: không áp dụng (phương pháp cổ điển)")
    eh = sc.get("early_exit_hint")
    if eh:
        lines.append(f"  3) Early exit: {eh}")
    sl = sc.get("stoploss_px")
    if sl is not None:
        lines.append(f"  4) Stoploss (max loss vốn): {float(sl):.2f}")
    return "\n".join(lines)
