# -*- coding: utf-8 -*-
"""
%change — dải ±% quanh close theo trung bình |biến động %| của các lệnh mô phỏng (entry/exit chiến lược).

Logic tách từ idea_for_update/pct_change_avg; dùng cho API chart và có thể tái sử dụng sau.
"""

import bisect
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from strategy.indicators import add_indicators
from strategy.signals import long_entry, short_entry, long_exit, short_exit


@dataclass
class SimulatedTrade:
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_open: float
    exit_close: float
    pct_change: float


def _to_float(v) -> Optional[float]:
    try:
        x = float(v)
        if pd.isna(x):
            return None
        return x
    except (TypeError, ValueError):
        return None


def _detect_trades_from_indicator_df(df: pd.DataFrame) -> List[SimulatedTrade]:
    """df: đã add_indicators, index sorted, len >= 3."""
    trades: List[SimulatedTrade] = []
    open_trade: Optional[Dict] = None

    for i in range(1, len(df)):
        prev_row = df.iloc[i - 1]
        curr_row = df.iloc[i]

        if open_trade is None:
            sig_long = bool(long_entry(prev_row, curr_row))
            sig_short = bool(short_entry(prev_row, curr_row))
            if not (sig_long or sig_short):
                continue

            side = "LONG" if sig_long else "SHORT"
            entry_open = _to_float(curr_row.get("open"))
            if entry_open is None or entry_open <= 0:
                continue

            open_trade = {
                "side": side,
                "entry_time": df.index[i],
                "entry_open": entry_open,
            }
            continue

        side = open_trade["side"]
        should_exit = bool(long_exit(prev_row, curr_row)) if side == "LONG" else bool(short_exit(prev_row, curr_row))
        if not should_exit:
            continue

        exit_close = _to_float(curr_row.get("close"))
        entry_open = _to_float(open_trade.get("entry_open"))
        if exit_close is None or entry_open is None or entry_open <= 0:
            open_trade = None
            continue

        if side == "LONG":
            pct_change = (exit_close - entry_open) / entry_open * 100.0
        else:
            pct_change = (entry_open - exit_close) / entry_open * 100.0

        trades.append(
            SimulatedTrade(
                side=side,
                entry_time=open_trade["entry_time"],
                exit_time=df.index[i],
                entry_open=entry_open,
                exit_close=exit_close,
                pct_change=float(pct_change),
            )
        )
        open_trade = None

    return trades


def detect_strategy_trades_basic(df_ohlc: pd.DataFrame) -> List[SimulatedTrade]:
    """
    Replay nến và bắt lệnh theo rule entry/exit cơ bản (bỏ early/ATR).
    """
    if df_ohlc is None or df_ohlc.empty:
        return []

    base = df_ohlc.copy().sort_index()
    need_cols = {"open", "high", "low", "close"}
    if not need_cols.issubset(set(base.columns)):
        return []

    df = add_indicators(base)
    if df.empty or len(df) < 3:
        return []

    return _detect_trades_from_indicator_df(df)


def _abs_pct_move(t: SimulatedTrade) -> float:
    return abs(float(t.pct_change))


def build_pct_change_avg_bands_series(
    df_ohlc: pd.DataFrame,
    lookback_trades: int = 15,
) -> Dict:
    """
    Dải upper/mid/lower trên giá: mid=close, upper/lower = close * (1 ± half_width_pct/100),
    half_width_pct = mean(|pct_change|) trên cửa sổ lookback_trades lệnh đã đóng (cập nhật mỗi khi có exit).
    """
    empty: Dict = {
        "trade_count": 0,
        "avg_signed_pct": 0.0,
        "avg_abs_pct": 0.0,
        "band_half_width_pct": None,
        "band_half_width_usdt": None,
        "current_close": None,
        "upper": None,
        "mid": None,
        "lower": None,
        "lines": {"upper": [], "mid": [], "lower": []},
        "trades": [],
    }
    if df_ohlc is None or df_ohlc.empty:
        return empty

    base = df_ohlc.copy().sort_index()
    need_cols = {"open", "high", "low", "close"}
    if not need_cols.issubset(set(base.columns)):
        return empty

    df = add_indicators(base)
    if df.empty or len(df) < 3:
        return empty

    trades = _detect_trades_from_indicator_df(df)
    if not trades:
        out_trades: List[Dict] = []
        return {
            "trade_count": 0,
            "avg_signed_pct": 0.0,
            "avg_abs_pct": 0.0,
            "band_half_width_pct": None,
            "band_half_width_usdt": None,
            "current_close": _to_float(df.iloc[-1].get("close")),
            "upper": None,
            "mid": _to_float(df.iloc[-1].get("close")),
            "lower": None,
            "lines": {"upper": [], "mid": [], "lower": []},
            "trades": out_trades,
        }

    trades_sorted = sorted(trades, key=lambda t: pd.Timestamp(t.exit_time))
    exit_times = [pd.Timestamp(t.exit_time) for t in trades_sorted]
    n_tr = len(trades_sorted)

    half_width_pct_at_exit: List[float] = []
    signed_at_exit: List[float] = []
    for j in range(n_tr):
        w_start = max(0, j + 1 - lookback_trades)
        window = trades_sorted[w_start : j + 1]
        abs_pcts = [_abs_pct_move(t) for t in window]
        half_p = float(sum(abs_pcts) / len(abs_pcts))
        half_width_pct_at_exit.append(half_p)
        pcs = [float(t.pct_change) for t in window]
        signed_at_exit.append(float(sum(pcs) / len(pcs)))

    upper_line: List[Dict] = []
    mid_line: List[Dict] = []
    lower_line: List[Dict] = []

    last_half_pct = 0.0
    last_signed = 0.0
    last_window_len = 0

    for ts in df.index:
        ts_cmp = pd.Timestamp(ts)
        k = bisect.bisect_right(exit_times, ts_cmp)
        if k <= 0:
            half_pct = 0.0
            avg_s = 0.0
            cnt = 0
        else:
            j_idx = k - 1
            half_pct = half_width_pct_at_exit[j_idx]
            avg_s = signed_at_exit[j_idx]
            w_start = max(0, j_idx + 1 - lookback_trades)
            cnt = j_idx + 1 - w_start

        close_px = _to_float(df.loc[ts, "close"])
        if close_px is None or close_px <= 0:
            continue

        f = 1.0 + half_pct / 100.0
        g = 1.0 - half_pct / 100.0
        upper_line.append({"time": ts, "value": close_px * f})
        mid_line.append({"time": ts, "value": close_px})
        lower_line.append({"time": ts, "value": close_px * g})

        last_half_pct = half_pct
        last_signed = avg_s
        last_window_len = cnt

    out_trades = [
        {
            "side": t.side,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "entry_open": t.entry_open,
            "exit_close": t.exit_close,
            "pct_change": t.pct_change,
        }
        for t in trades
    ]

    last_close = _to_float(df.iloc[-1].get("close"))
    half_usdt = (last_close * last_half_pct / 100.0) if last_close and last_close > 0 else None
    return {
        "trade_count": last_window_len,
        "avg_signed_pct": last_signed,
        "avg_abs_pct": last_half_pct,
        "band_half_width_pct": last_half_pct,
        "band_half_width_usdt": half_usdt,
        "current_close": last_close,
        "upper": upper_line[-1]["value"] if upper_line else None,
        "mid": mid_line[-1]["value"] if mid_line else last_close,
        "lower": lower_line[-1]["value"] if lower_line else None,
        "lines": {
            "upper": upper_line,
            "mid": mid_line,
            "lower": lower_line,
        },
        "trades": out_trades,
    }


def build_pct_change_avg_bands(df_ohlc: pd.DataFrame, lookback_trades: int = 20) -> Dict:
    """Alias cho API / tương thích tên cũ."""
    return build_pct_change_avg_bands_series(df_ohlc, lookback_trades=lookback_trades)
