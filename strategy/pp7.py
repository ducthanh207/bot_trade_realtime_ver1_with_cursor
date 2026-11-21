# -*- coding: utf-8 -*-
"""
[2026-11-20] Phương pháp 7 = PP4 + 3 sửa đổi rút ra từ phân tích backtest PP4 (SOL/BNB/ETH 2026):

1. Size theo rủi ro: mỗi lệnh chỉ mất cố định M7_RISK_PCT vốn nếu chạm stop ban đầu
   (PP4 vào 20x × 30% = 6 lần vốn, nên tiền lỗ mỗi lệnh phụ thuộc ATR, có lệnh mất 7–10% vốn).
2. Lọc trend luôn bật: LONG chỉ khi giá đóng nến 4H trên EMA50, SHORT khi dưới
   (PP4 chỉ lọc khi ADX > 30 → vẫn LONG suốt lúc giá giảm mạnh mà ADX thấp).
3. Stop theo khung 4H: stop ban đầu và trailing = M7_ATR4H_MULT × ATR nến 4H lúc vào lệnh, không siết sau 12h
   (PP4 dùng 2.5 × ATR nến 1H → một nửa số lệnh thua bị quét trong 8 giờ đầu).

Còn lại giữ nguyên PP4: tín hiệu RSI/EMA/WMA 4H, chặn RSI cực trị, xác nhận RSI 1H, vùng ADX, swing, streak, circuit breaker,
thoát 4H_EXIT. Chỉ chạy trong backtest (backtest/live_replay.py) — bot paper/live không dùng PP7.
"""

from __future__ import annotations

import math

from config import settings


def _num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def m7_trend_allows(side: str, close, ema, ema_ref=None) -> bool:
    """
    Lọc trend PP7 (không phụ thuộc ADX). Thiếu dữ liệu EMA → không chặn (như PP4).
    ema_ref: EMA50 của M7_TREND_SLOPE_BARS nến trước (chỉ xét khi M7_TREND_SLOPE_BARS > 0).
    """
    if not settings.M7_TREND_FILTER:
        return True
    c, e = _num(close), _num(ema)
    if c is None or e is None or c <= 0 or e <= 0:
        return True
    if side == "LONG" and c <= e:
        return False
    if side == "SHORT" and c >= e:
        return False
    if int(settings.M7_TREND_SLOPE_BARS) > 0:
        r = _num(ema_ref)
        if r is not None and r > 0:
            if side == "LONG" and e <= r:
                return False
            if side == "SHORT" and e >= r:
                return False
    return True


def m7_stop_distance(atr_4h) -> float | None:
    """Khoảng cách stop (giá) = M7_ATR4H_MULT × ATR 4H. None nếu ATR không hợp lệ."""
    a = _num(atr_4h)
    if a is None or a <= 0:
        return None
    return a * float(settings.M7_ATR4H_MULT)


def m7_size_and_margin(balance: float, entry: float, stop_dist: float, size_mult: float,
                       leverage: float, wallet_pct: float):
    """
    Size theo rủi ro: size = (M7_RISK_PCT × vốn × size_mult) / khoảng cách stop.
    Notional không vượt mức PP4 (vốn × wallet_pct × leverage × size_mult) → stop quá hẹp thì rủi ro thực tế < M7_RISK_PCT.
    Trả (size, margin, notional); size 0 nếu không vào được.
    """
    if balance <= 0 or entry <= 0 or not stop_dist or stop_dist <= 0 or leverage <= 0:
        return 0.0, 0.0, 0.0
    mult = max(0.0, float(size_mult))
    risk_usdt = balance * float(settings.M7_RISK_PCT) * mult
    size = risk_usdt / stop_dist
    max_notional = balance * float(wallet_pct) * float(leverage) * mult
    notional = min(size * entry, max_notional)
    size = notional / entry
    margin = notional / float(leverage)
    return size, margin, notional
