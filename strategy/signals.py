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


def m4_entry_1h_confirm(side: str, df_1h: "pd.DataFrame") -> bool:
    """
    Method 4: xác nhận hướng RSI 1H trên 2 nến đã đóng (iloc[-3] vs iloc[-2]).
    LONG cần RSI 1H đang tăng, SHORT cần đang giảm.
    Thiếu dữ liệu 1H (API lỗi) → không chặn để bot không đứng im vô hạn.
    """
    try:
        if df_1h is None or df_1h.empty or len(df_1h) < 3:
            return True
        a = float(df_1h.iloc[-3]["RSI"])
        b = float(df_1h.iloc[-2]["RSI"])
        if pd.isna(a) or pd.isna(b):
            return True
        return b > a if side == "LONG" else b < a
    except (KeyError, TypeError, ValueError, IndexError):
        return True


def m4_entry_rsi_extreme_block(side: str, rsi_value) -> bool:
    """
    Method 4: True nếu PHẢI CHẶN lệnh vì RSI nến tín hiệu đã ở vùng cực trị —
    SHORT khi RSI đã quá bán (đuổi giá giảm) hoặc LONG khi RSI đã quá mua.
    """
    try:
        r = float(rsi_value)
        if pd.isna(r):
            return False
        if side == "SHORT":
            return r < settings.M4_RSI_SHORT_FLOOR
        return r > settings.M4_RSI_LONG_CEIL
    except (TypeError, ValueError):
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
