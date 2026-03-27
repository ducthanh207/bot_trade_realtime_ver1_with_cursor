# -*- coding: utf-8 -*-
"""
Logic draft for "% change avg".

This module is intentionally isolated in idea_for_update and does not change
current production flow.
"""

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


def _as_candle_dict(ts: pd.Timestamp, row: pd.Series) -> Dict:
    return {
        "time": ts,
        "open": _to_float(row.get("open")),
        "high": _to_float(row.get("high")),
        "low": _to_float(row.get("low")),
        "close": _to_float(row.get("close")),
    }


def detect_strategy_trades_basic(df_ohlc: pd.DataFrame) -> List[SimulatedTrade]:
    """
    Replay historical candles and detect trades by base rules only:
    - Entry: long_entry / short_entry
    - Exit: long_exit / short_exit
    - Ignore early-exit and ATR trailing

    Assumptions:
    - df_ohlc index is datetime-like and sorted ascending.
    - Required columns: open, high, low, close
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

    trades: List[SimulatedTrade] = []
    open_trade: Optional[Dict] = None

    # We need i-1 and i for signal transitions.
    for i in range(1, len(df)):
        prev_ts = df.index[i - 1]
        curr_ts = df.index[i]
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
                "entry_time": curr_ts,
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
                exit_time=curr_ts,
                entry_open=entry_open,
                exit_close=exit_close,
                pct_change=float(pct_change),
            )
        )
        open_trade = None

    return trades


def compute_pct_change_avg(
    df_ohlc: pd.DataFrame,
    lookback_trades: int = 20,
) -> Dict:
    """
    Compute avg change from detected completed trades.
    Returns signed and absolute averages.
    """
    trades = detect_strategy_trades_basic(df_ohlc)
    if lookback_trades > 0:
        trades = trades[-lookback_trades:]

    if not trades:
        return {
            "trades": [],
            "trade_count": 0,
            "avg_signed_pct": 0.0,
            "avg_abs_pct": 0.0,
        }

    pct_list = [float(t.pct_change) for t in trades]
    abs_list = [abs(x) for x in pct_list]
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
    return {
        "trades": out_trades,
        "trade_count": len(trades),
        "avg_signed_pct": float(sum(pct_list) / len(pct_list)),
        "avg_abs_pct": float(sum(abs_list) / len(abs_list)),
    }


def build_pct_change_avg_bands(
    df_ohlc: pd.DataFrame,
    lookback_trades: int = 20,
) -> Dict:
    """
    Build horizontal upper/mid/lower band values around current close.
    Band width is avg_abs_pct from completed historical trades.

    Returns line series ready for chart overlay:
    - each line is constant over the current candle timeline.
    """
    if df_ohlc is None or df_ohlc.empty:
        return {
            "trade_count": 0,
            "avg_signed_pct": 0.0,
            "avg_abs_pct": 0.0,
            "current_close": None,
            "upper": None,
            "mid": None,
            "lower": None,
            "lines": {"upper": [], "mid": [], "lower": []},
        }

    base = df_ohlc.copy().sort_index()
    stats = compute_pct_change_avg(base, lookback_trades=lookback_trades)

    current_close = _to_float(base.iloc[-1].get("close"))
    if current_close is None or current_close <= 0:
        return {
            **stats,
            "current_close": None,
            "upper": None,
            "mid": None,
            "lower": None,
            "lines": {"upper": [], "mid": [], "lower": []},
        }

    width_pct = float(stats["avg_abs_pct"])
    upper = current_close * (1.0 + width_pct / 100.0)
    lower = current_close * (1.0 - width_pct / 100.0)
    mid = current_close

    times = list(base.index)
    upper_line = [{"time": t, "value": upper} for t in times]
    mid_line = [{"time": t, "value": mid} for t in times]
    lower_line = [{"time": t, "value": lower} for t in times]

    return {
        **stats,
        "current_close": float(current_close),
        "upper": float(upper),
        "mid": float(mid),
        "lower": float(lower),
        "lines": {
            "upper": upper_line,
            "mid": mid_line,
            "lower": lower_line,
        },
    }


if __name__ == "__main__":
    # Minimal local demonstration with synthetic data.
    rng = pd.date_range("2026-01-01", periods=300, freq="4H")
    close = pd.Series(range(300), index=rng).astype(float) + 10000.0
    demo = pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 10.0,
            "low": close - 10.0,
            "close": close,
            "volume": 1.0,
        },
        index=rng,
    )
    result = build_pct_change_avg_bands(demo, lookback_trades=20)
    print(
        {
            "trade_count": result["trade_count"],
            "avg_signed_pct": round(result["avg_signed_pct"], 4),
            "avg_abs_pct": round(result["avg_abs_pct"], 4),
            "upper": result["upper"],
            "mid": result["mid"],
            "lower": result["lower"],
        }
    )
