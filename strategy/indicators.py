# -*- coding: utf-8 -*-
"""Tính RSI, EMA_RSI, WMA_RSI, ATR trên DataFrame 4h."""

import pandas as pd
import pandas_ta as ta


def add_indicators(
    df: pd.DataFrame,
    rsi_period: int = 14,
    ema_period: int = 20,
    ema_rsi_period: int = 9,
    wma_rsi_period: int = 45,
    atr_period: int = 14,
) -> pd.DataFrame:
    out = df.copy()
    out["RSI"] = ta.rsi(out["close"], length=rsi_period)
    out["EMA_RSI"] = ta.wma(out["RSI"], length=ema_rsi_period)
    out["WMA_RSI"] = ta.wma(out["RSI"], length=wma_rsi_period)
    out["ATR"] = ta.atr(out["high"], out["low"], out["close"], length=atr_period)
    out["EMA"] = ta.ema(out["close"], length=ema_period)
    out["WMA"] = ta.wma(out["close"], length=ema_period)
    return out.dropna()


def add_indicators_m3(df: pd.DataFrame, ema_trend_len: int = 50, swing_lookback: int = 6, adx_length: int = 14) -> pd.DataFrame:
    """Extended indicators for Method 3: adds ADX, EMA_TREND (EMA50), swing structure."""
    out = add_indicators(df)
    # ADX
    adx_df = ta.adx(out["high"], out["low"], out["close"], length=adx_length)
    if adx_df is not None and not adx_df.empty:
        col_adx = [c for c in adx_df.columns if c.startswith("ADX_")]
        col_dmp = [c for c in adx_df.columns if c.startswith("DMP_")]
        col_dmn = [c for c in adx_df.columns if c.startswith("DMN_")]
        if col_adx:
            out["ADX"] = adx_df[col_adx[0]]
        if col_dmp:
            out["DI_PLUS"] = adx_df[col_dmp[0]]
        if col_dmn:
            out["DI_MINUS"] = adx_df[col_dmn[0]]
    # EMA trend (EMA50)
    out["EMA_TREND"] = ta.ema(out["close"], length=ema_trend_len)
    # Swing structure
    out["swing_low"] = out["low"].rolling(swing_lookback, min_periods=swing_lookback).min()
    out["swing_high"] = out["high"].rolling(swing_lookback, min_periods=swing_lookback).max()
    out["swing_low_prev"] = out["swing_low"].shift(swing_lookback)
    out["swing_high_prev"] = out["swing_high"].shift(swing_lookback)
    out["higher_low"] = out["swing_low"] > out["swing_low_prev"]
    out["lower_high"] = out["swing_high"] < out["swing_high_prev"]
    return out.dropna()
