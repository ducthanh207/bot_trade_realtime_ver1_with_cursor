# -*- coding: utf-8 -*-
"""
Tư vấn tín hiệu: đánh giá từng điều kiện LONG/SHORT, % đạt, % rủi ro.
Dùng cho /advise trên Telegram.
"""

from config import settings


def _get(row, key, default=0):
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return default


def evaluate_conditions(prev_row, row):
    """
    Đánh giá điều kiện vào lệnh LONG/SHORT dựa trên RSI, EMA_RSI, WMA_RSI.
    Trả về dict:
      - long_conditions: list of (tên điều kiện, đạt: bool)
      - short_conditions: list of (tên điều kiện, đạt: bool)
      - long_pct, short_pct: 0-100 (số điều kiện đạt / 3 * 100)
      - risk_pct: ước tính % rủi ro (ATR * mult / giá)
    """
    prev = prev_row
    r = row
    p_ema, p_rsi, p_wma = _get(prev, "EMA_RSI"), _get(prev, "RSI"), _get(prev, "WMA_RSI")
    c_ema, c_rsi, c_wma = _get(r, "EMA_RSI"), _get(r, "RSI"), _get(r, "WMA_RSI")
    close = _get(r, "close", 1)
    atr = _get(r, "ATR", 0)

    # LONG: 3 điều kiện (OR) - chỉ cần 1 đạt
    long_1 = p_ema > p_rsi > p_wma and c_rsi > c_ema > c_wma
    long_2 = p_wma > p_ema > p_rsi and c_rsi > c_wma > c_ema
    long_3 = p_wma > p_ema > p_rsi and c_wma > c_rsi > c_ema
    long_conditions = [
        ("RSI cắt lên (EMA>RSI>WMA → RSI>EMA>WMA)", long_1),
        ("RSI hồi rồi lên (WMA>EMA>RSI → RSI>WMA>EMA)", long_2),
        ("WMA>RSI>EMA (cấu hình tăng)", long_3),
    ]
    long_met = sum(1 for _, b in long_conditions if b)
    long_pct = round((long_met / 3.0) * 100) if long_conditions else 0

    # SHORT: 3 điều kiện (OR)
    short_1 = p_ema < p_rsi < p_wma and c_rsi < c_ema < c_wma
    short_2 = p_wma < p_ema < p_rsi and c_rsi < c_wma < c_ema
    short_3 = p_wma < p_ema < p_rsi and c_wma < c_rsi < c_ema
    short_conditions = [
        ("RSI cắt xuống (EMA<RSI<WMA → RSI<EMA<WMA)", short_1),
        ("RSI hồi rồi xuống (WMA<EMA<RSI → RSI<WMA<EMA)", short_2),
        ("WMA<RSI<EMA (cấu hình giảm)", short_3),
    ]
    short_met = sum(1 for _, b in short_conditions if b)
    short_pct = round((short_met / 3.0) * 100) if short_conditions else 0

    # Rủi ro: khoảng stop (ATR * mult) / giá * 100
    mult = getattr(settings, "ATR_MULTIPLIER", 1.5)
    risk_pct = round((atr * mult / close * 100), 2) if close and close > 0 else 0

    return {
        "long_conditions": long_conditions,
        "short_conditions": short_conditions,
        "long_pct": long_pct,
        "short_pct": short_pct,
        "risk_pct": risk_pct,
        "long_signal": long_met >= 1,
        "short_signal": short_met >= 1,
    }
