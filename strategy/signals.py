# -*- coding: utf-8 -*-
"""Tín hiệu vào/ra lệnh: long_entry, short_entry, long_exit, short_exit, early exit."""

import pandas as pd

from config import settings


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def long_entry(prev, row):
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    return (
        (prev["EMA_RSI"] > prev["RSI"] > prev["WMA_RSI"] and row["RSI"] > row["EMA_RSI"] > row["WMA_RSI"])
        or (prev["WMA_RSI"] > prev["EMA_RSI"] > prev["RSI"] and row["RSI"] > row["WMA_RSI"] > row["EMA_RSI"])
        or (prev["WMA_RSI"] > prev["EMA_RSI"] > prev["RSI"] and row["WMA_RSI"] > row["RSI"] > row["EMA_RSI"])
    )


def short_entry(prev, row):
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    return (
        (prev["EMA_RSI"] < prev["RSI"] < prev["WMA_RSI"] and row["RSI"] < row["EMA_RSI"] < row["WMA_RSI"])
        or (prev["WMA_RSI"] < prev["EMA_RSI"] < prev["RSI"] and row["RSI"] < row["WMA_RSI"] < row["EMA_RSI"])
        or (prev["WMA_RSI"] < prev["EMA_RSI"] < prev["RSI"] and row["WMA_RSI"] < row["RSI"] < row["EMA_RSI"])
    )


def long_exit(prev, row):
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    return (
        prev["RSI"] > prev["EMA_RSI"] > prev["WMA_RSI"]
        and row["WMA_RSI"] < row["RSI"] < row["EMA_RSI"]
    )


def short_exit(prev, row):
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    return (
        prev["RSI"] < prev["EMA_RSI"] < prev["WMA_RSI"]
        and row["WMA_RSI"] > row["RSI"] > row["EMA_RSI"]
    )


def long_exit_early(prev, row):
    if not settings.RSI_EARLY_EXIT:
        return False
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    cross_below = prev["RSI"] >= prev["EMA_RSI"] and row["RSI"] < row["EMA_RSI"]
    rsi_fall = row["RSI"] < settings.RSI_LONG_CUT
    return cross_below or rsi_fall


def short_exit_early(prev, row):
    if not settings.RSI_EARLY_EXIT:
        return False
    prev = _ensure_series(prev)
    row = _ensure_series(row)
    cross_above = prev["RSI"] <= prev["EMA_RSI"] and row["RSI"] > row["EMA_RSI"]
    rsi_rise = row["RSI"] > settings.RSI_SHORT_CUT
    return cross_above or rsi_rise


def long_early_exit_strong_b(df_4h: "pd.DataFrame", i: int, confirm_bars: int = 2) -> bool:
    """Cach B - tang manh LONG: RSI duoi nguong cung VA dang giam lien tiep confirm_bars nen."""
    if i < confirm_bars or i >= len(df_4h):
        return False
    try:
        window = df_4h["RSI"].iloc[i - confirm_bars: i + 1]
        if not bool((window < settings.RSI_LONG_CUT).all()):
            return False
        diffs = window.diff().iloc[1:]
        return bool((diffs <= 0).all())
    except Exception:
        return False


def short_early_exit_strong_b(df_4h: "pd.DataFrame", i: int, confirm_bars: int = 2) -> bool:
    """Cach B - tang manh SHORT: RSI tren nguong cung VA dang tang lien tiep confirm_bars nen."""
    if i < confirm_bars or i >= len(df_4h):
        return False
    try:
        window = df_4h["RSI"].iloc[i - confirm_bars: i + 1]
        if not bool((window > settings.RSI_SHORT_CUT).all()):
            return False
        diffs = window.diff().iloc[1:]
        return bool((diffs >= 0).all())
    except Exception:
        return False
