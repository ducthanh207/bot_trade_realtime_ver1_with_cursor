# -*- coding: utf-8 -*-
"""
[2026-11-01] Nhận diện giai đoạn thị trường cho Phương pháp 4 (PP4) + các hàm cắt lỗ sớm.

Bộ phân loại dùng N nến 4H ĐÃ ĐÓNG (mặc định N = M4_REGIME_LOOKBACK = 20):

- Efficiency Ratio (ER, Kaufman) = |close[-1] - close[-1-N]| / tổng |close[i] - close[i-1]| trong N nến.
  ER gần 1: giá đi thẳng (trend). ER gần 0: giá chạy loanh quanh (đi ngang).
- Độ dốc EMA50 = (EMA50[-1] - EMA50[-1-N]) / ATR4H[-1]  (tính theo số lần ATR để dùng chung cho mọi coin).

Kết quả:
- "UP":    ER >= M4_REGIME_ER_TREND, EMA50 dốc lên >= M4_REGIME_SLOPE_ATR và close > EMA50
- "DOWN":  ER >= M4_REGIME_ER_TREND, EMA50 dốc xuống <= -M4_REGIME_SLOPE_ATR và close < EMA50
- "RANGE": còn lại (đi ngang hoặc tín hiệu lẫn lộn → xếp vào nhóm an toàn)

Mọi tính năng ở đây đều MẶC ĐỊNH TẮT (xem config/settings.py, khối [2026-11-01]).
Dùng chung cho paper/live (bot/slot_engine.py, strategy/exit_engine.py) và backtest (backtest/live_replay.py).
"""

from __future__ import annotations

import math

import pandas as pd

from config import settings

REGIME_UP = "UP"
REGIME_DOWN = "DOWN"
REGIME_RANGE = "RANGE"


def efficiency_ratio(close: pd.Series, n: int) -> float:
    """ER Kaufman của n bước giá cuối. NaN nếu chưa đủ n+1 giá."""
    c = pd.Series(close).astype(float).dropna()
    if n <= 0 or len(c) < n + 1:
        return float("nan")
    w = c.iloc[-(n + 1):]
    path = float(w.diff().abs().sum())
    if path <= 0:
        return 0.0
    return abs(float(w.iloc[-1]) - float(w.iloc[0])) / path


def classify_regime(df_4h_m3: pd.DataFrame, lookback: int = None) -> dict:
    """
    Phân loại giai đoạn trên các nến 4H ĐÃ ĐÓNG (dòng cuối của df là nến 4H vừa đóng).
    df cần cột close, EMA_TREND (EMA50), ATR — đúng như strategy.indicators.add_indicators_m3.
    Trả {"regime", "er", "slope_atr"}; thiếu dữ liệu → regime None (không áp dụng gì).
    """
    n = int(lookback or settings.M4_REGIME_LOOKBACK)
    out = {"regime": None, "er": None, "slope_atr": None}
    try:
        if df_4h_m3 is None or len(df_4h_m3) < n + 1:
            return out
        er = efficiency_ratio(df_4h_m3["close"], n)
        ema = df_4h_m3["EMA_TREND"].astype(float)
        atr = float(df_4h_m3["ATR"].iloc[-1])
        if math.isnan(er) or not atr or math.isnan(atr) or pd.isna(ema.iloc[-1 - n]):
            return out
        slope = (float(ema.iloc[-1]) - float(ema.iloc[-1 - n])) / atr
        close = float(df_4h_m3["close"].iloc[-1])
        regime = REGIME_RANGE
        if er >= settings.M4_REGIME_ER_TREND:
            if slope >= settings.M4_REGIME_SLOPE_ATR and close > float(ema.iloc[-1]):
                regime = REGIME_UP
            elif slope <= -settings.M4_REGIME_SLOPE_ATR and close < float(ema.iloc[-1]):
                regime = REGIME_DOWN
        out.update(regime=regime, er=round(er, 4), slope_atr=round(slope, 3))
    except (KeyError, IndexError, TypeError, ValueError):
        pass
    return out


def m4_regime_entry_decision(side: str, regime: str | None):
    """
    Quyết định vào lệnh theo giai đoạn. Trả (allow, tight):
    - allow=False: bỏ lệnh (E: RANGE + M4_RANGE_SKIP_ENTRY, hoặc ngược trend + M4_COUNTER_TREND_BLOCK)
    - tight=True: lệnh vào lúc đi ngang / ngược trend → stop chặt (M4_TIGHT_ATR_MULTIPLIER) và cắt sớm A/B
    regime None (tắt tính năng hoặc thiếu dữ liệu) → (True, False): giữ nguyên PP4 gốc.
    """
    if not regime:
        return True, False
    if regime == REGIME_RANGE:
        if settings.M4_RANGE_SKIP_ENTRY:
            return False, False
        return True, True
    counter = (side == "LONG" and regime == REGIME_DOWN) or (side == "SHORT" and regime == REGIME_UP)
    if counter:
        if settings.M4_COUNTER_TREND_BLOCK:
            return False, False
        return True, True
    return True, False


def _ts(v):
    """entry_time có thể là datetime hoặc chuỗi ISO (sau khi bot khởi động lại) → pd.Timestamp có tz, hoặc None."""
    if v is None:
        return None
    try:
        t = pd.Timestamp(v)
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    return t


def _hours_since_entry(open_trade: dict, now) -> float | None:
    t0, t1 = _ts(open_trade.get("entry_time")), _ts(now)
    if t0 is None or t1 is None:
        return None
    return (t1 - t0).total_seconds() / 3600


def _early_cut_applies(open_trade: dict) -> bool:
    if str(open_trade.get("trading_method", "")) != "4":
        return False
    if settings.M4_EARLY_CUT_ONLY_TIGHT and not open_trade.get("m4_tight"):
        return False
    return True


def m4_invalidation_hit(open_trade: dict, h1_open_time, h1_close: float) -> bool:
    """
    (A) Thoát khi tín hiệu thất bại. Xét MỘT nến 1H đã đóng (mở lúc h1_open_time, giá đóng h1_close):
    trong M4_INVALIDATION_HOURS đầu, nếu LONG đóng dưới đáy nến 4H tín hiệu − buffer×ATR
    (SHORT: trên đỉnh + buffer×ATR) → True. Chỉ xét nến 1H mở từ giờ vào lệnh trở đi.
    """
    if not settings.M4_INVALIDATION_EXIT or not _early_cut_applies(open_trade):
        return False
    try:
        lo, hi = open_trade.get("signal_low"), open_trade.get("signal_high")
        t_open = _ts(h1_open_time)
        t_entry = _ts(open_trade.get("entry_time"))
        if lo is None or hi is None or t_open is None or t_entry is None or h1_close is None:
            return False
        if t_open < t_entry.floor("h"):
            return False  # nến 1H đã có trước khi vào lệnh
        if (t_open - t_entry).total_seconds() / 3600 >= settings.M4_INVALIDATION_HOURS:
            return False
        buf = settings.M4_INVALIDATION_BUFFER_ATR * float(open_trade.get("atr") or 0)
        c = float(h1_close)
        if open_trade["side"] == "LONG":
            return c < float(lo) - buf
        return c > float(hi) + buf
    except (KeyError, TypeError, ValueError):
        return False


def m4_time_stop_hit(open_trade: dict, now, pnl_raw: float) -> bool:
    """
    (B) Dừng theo thời gian: gọi ở mốc 4H. Đã giữ lệnh >= M4_TIME_STOP_HOURS (sai số 15 phút vì
    live vào lệnh vài giây sau mốc 4H) mà PnL thô vẫn <= 0 → True.
    """
    if not settings.M4_TIME_STOP or not _early_cut_applies(open_trade):
        return False
    h = _hours_since_entry(open_trade, now)
    if h is None:
        return False
    return h + 0.25 >= settings.M4_TIME_STOP_HOURS and pnl_raw <= 0


def m4_trailing_multiplier(open_trade: dict, now_ts) -> float:
    """
    Hệ số ATR trailing của PP4 tại thời điểm now_ts.
    - Lệnh "chặt" (m4_tight): M4_TIGHT_ATR_MULTIPLIER cố định.
    - Mặc định (PP4 gốc): grace M4_ATR_MULTIPLIER_GRACE trong M4_ATR_GRACE_HOURS đầu, sau đó M4_ATR_MULTIPLIER.
    - (D) M4_SMOOTH_GRACE: giảm tuyến tính từ grace về hệ số thường trong M4_ATR_GRACE_HOURS.
    """
    if open_trade.get("m4_tight"):
        return float(open_trade.get("atr_multiplier_override") or settings.M4_TIGHT_ATR_MULTIPLIER)
    g, m, gh = settings.M4_ATR_MULTIPLIER_GRACE, settings.M4_ATR_MULTIPLIER, settings.M4_ATR_GRACE_HOURS
    entry_time = open_trade.get("entry_time")
    try:
        if entry_time is not None and getattr(entry_time, "tzinfo", None) is not None and now_ts is not None:
            elapsed = (pd.Timestamp(now_ts) - pd.Timestamp(entry_time)).total_seconds() / 3600
            if settings.M4_SMOOTH_GRACE and gh > 0:
                frac = min(1.0, max(0.0, elapsed / gh))
                return g - (g - m) * frac
            return g if elapsed < gh else m
    except (TypeError, ValueError):
        pass
    return m


def m4_apply_regime_to_payload(payload: dict, side: str, regime_info: dict, tight: bool, row_closed) -> None:
    """
    Ghi thông tin giai đoạn vào lệnh vừa mở (dùng chung paper/live và backtest):
    regime/er/slope, đỉnh-đáy nến 4H tín hiệu (cho A), và nếu tight thì đổi hệ số + stop ban đầu.
    """
    payload["regime"] = regime_info.get("regime")
    payload["regime_er"] = regime_info.get("er")
    payload["regime_slope_atr"] = regime_info.get("slope_atr")
    try:
        payload["signal_high"] = float(row_closed["high"])
        payload["signal_low"] = float(row_closed["low"])
    except (KeyError, TypeError, ValueError):
        pass
    if tight:
        mult = settings.M4_TIGHT_ATR_MULTIPLIER
        dist = float(payload["atr"]) * mult
        entry = float(payload["entry_price"])
        payload["m4_tight"] = True
        payload["atr_multiplier_override"] = mult
        payload["trail_stop"] = entry - dist if side == "LONG" else entry + dist
