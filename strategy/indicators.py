# -*- coding: utf-8 -*-
"""Tính RSI, EMA_RSI, WMA_RSI, ATR trên DataFrame 4h."""

import pandas as pd
import pandas_ta as ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Thêm cột RSI, EMA_RSI (WMA 9), WMA_RSI (45), ATR, EMA (trên close) vào df.
    Trả về bản copy đã dropna.
    """
    out = df.copy()
    out["RSI"] = ta.rsi(out["close"], length=14)
    out["EMA_RSI"] = ta.wma(out["RSI"], length=9)
    out["WMA_RSI"] = ta.wma(out["RSI"], length=45)
    out["ATR"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["EMA"] = ta.ema(out["close"], length=20)
    out["WMA"] = ta.wma(out["close"], length=20)
    return out.dropna()
