# -*- coding: utf-8 -*-
"""
[2026-11-14] CVD (Cumulative Volume Delta) cho PP6 = PP4 + CVD và PP6.1 = PP5 + CVD.

CVD xấp xỉ từ nến Binance Futures (không cần dữ liệu từng lệnh khớp):
    delta = taker_buy − taker_sell = 2 × taker_buy_base_volume − volume
    CVD   = tổng cộng dồn delta.

CVD cộng dồn từ một mốc tuỳ ý nên chỉ "độ dốc" mới có nghĩa. Độ dốc trên N nến đã đóng:
    ratio_N = (CVD[t] − CVD[t−N]) / tổng volume N nến = tổng delta N nến / tổng volume N nến
nằm trong [−1, +1]: > 0 là bên mua chủ động áp đảo, < 0 là bên bán. Chia cho volume để so được giữa các
coin và các giai đoạn volume to/nhỏ.

Ba chỗ dùng (mọi phép xét chỉ dùng nến ĐÃ ĐÓNG):
1) Vào lệnh (PP6, PP6.1): độ dốc CVD 4H (M6_4H_BARS nến) phải cùng chiều lệnh, vượt M6_4H_MIN_RATIO.
   Tuỳ chọn M6_1H_ENTRY_CONFIRM: độ dốc 1H (M6_1H_BARS nến) cũng phải cùng chiều.
2) Đang giữ lệnh: mỗi nến 1H đóng, nếu độ dốc 1H ngược lệnh M6_EXIT_CONFIRM_BARS nến liên tiếp
   (sau M6_EXIT_MIN_HOURS giờ kể từ lúc vào) → M6_EXIT_MODE: tighten = siết trailing về M6_TIGHT_ATR_MULT,
   close = đóng lệnh ngay (CVD_EXIT), off = bỏ qua.
3) PP6.1 khi chu kỳ ngày đi ngang: chọn phía theo dấu độ dốc CVD 4H dài (M61_SIDE_CVD_BARS nến) thay cho
   giá đóng nến ngày gần nhất (M61_SIDEWAYS_BIAS=cvd), hoặc đòi cả hai cùng phía (both), hoặc như PP5 (close).

Dùng chung cho bot (bot/slot_engine.py, strategy/exit_engine.py, strategy/risk.py) và backtest (backtest/live_replay.py).
Dữ liệu cần cột "taker_buy" (taker buy base asset volume, cột thứ 10 của kline Binance). Thiếu cột → không vào lệnh.
"""

from __future__ import annotations

import math

import pandas as pd

from config import settings

TAKER_COL = "taker_buy"


def has_taker(df) -> bool:
    return df is not None and not df.empty and TAKER_COL in df.columns and "volume" in df.columns


def delta_series(df: pd.DataFrame) -> pd.Series:
    """delta từng nến = 2 × taker_buy − volume."""
    return 2.0 * df[TAKER_COL].astype(float) - df["volume"].astype(float)


def ratio_series(df: pd.DataFrame, bars: int) -> pd.Series:
    """Độ dốc CVD trên `bars` nến (cửa sổ trượt, nhân quả): tổng delta / tổng volume. Nến có volume 0 → NaN."""
    n = max(1, int(bars))
    d = delta_series(df).rolling(n, min_periods=n).sum()
    v = df["volume"].astype(float).rolling(n, min_periods=n).sum()
    return d / v.where(v > 0)


def last_ratio(df_closed: pd.DataFrame, bars: int):
    """Độ dốc CVD tại nến đã đóng cuối cùng của df_closed; thiếu dữ liệu → None."""
    if not has_taker(df_closed) or len(df_closed) < max(1, int(bars)):
        return None
    tail = df_closed.tail(int(bars))
    v = float(tail["volume"].astype(float).sum())
    if v <= 0:
        return None
    r = float(delta_series(tail).sum()) / v
    return None if math.isnan(r) else r


def resample_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """Gộp nến 1H (volume, taker_buy) thành 4H neo giờ UTC như Binance; chỉ giữ nến 4H đủ 4 nến 1H."""
    utc = df_1h.tz_convert("UTC") if df_1h.index.tz is not None else df_1h
    g = utc[["volume", TAKER_COL]].astype(float).resample("4h", origin="epoch", label="left", closed="left")
    out = g.sum()
    out = out[g.count()["volume"] == 4]
    if df_1h.index.tz is not None:
        out.index = out.index.tz_convert(df_1h.index.tz)
    out.index.name = df_1h.index.name
    return out


# ---------------------------------------------------------------------------
# Vào lệnh
# ---------------------------------------------------------------------------
def _agrees(side: str, r, thresh: float) -> bool:
    if r is None or (isinstance(r, float) and math.isnan(r)):
        return False
    return r > thresh if side == "LONG" else r < -thresh


def cvd_entry_ok(side: str, r4, r1=None) -> bool:
    """CVD 4H (và tuỳ chọn 1H) cùng chiều lệnh."""
    if not _agrees(side, r4, float(settings.M6_4H_MIN_RATIO)):
        return False
    if settings.M6_1H_ENTRY_CONFIRM and not _agrees(side, r1, 0.0):
        return False
    return True


def cvd_side(r_side):
    """Phía theo dấu độ dốc CVD dài: LONG / SHORT / None (không có dữ liệu hoặc đúng 0)."""
    if r_side is None or (isinstance(r_side, float) and math.isnan(r_side)) or r_side == 0:
        return None
    return "LONG" if r_side > 0 else "SHORT"


def m61_entry_plan(side: str, cycle, r_side):
    """PP6.1: như m5_entry_plan (allow, wide, size_mult, counter), nhưng khi chu kỳ đi ngang thì phía do CVD quyết
    (M61_SIDEWAYS_BIAS=cvd) hoặc phải trùng cả nến đóng gần nhất lẫn CVD (both)."""
    from strategy.daily_cycle import SIDEWAYS, m5_entry_plan

    bias = settings.M61_SIDEWAYS_BIAS
    if cycle in SIDEWAYS and bias in ("cvd", "both"):
        cs = cvd_side(r_side)
        if bias == "cvd":
            return (side == cs), True, 1.0, False
        allow, wide, k, counter = m5_entry_plan(side, cycle)
        if not allow or counter or side != cs:
            return False, False, 1.0, False
        return True, wide, k, False
    return m5_entry_plan(side, cycle)


def apply_cvd_to_payload(payload: dict, r4, r1, r_side=None) -> None:
    payload["cvd4_ratio"] = None if r4 is None else round(float(r4), 5)
    payload["cvd1_ratio"] = None if r1 is None else round(float(r1), 5)
    payload["cvd_side_ratio"] = None if r_side is None else round(float(r_side), 5)
    payload["cvd_against_n"] = 0
    payload["cvd_last_h"] = None
    payload["cvd_tight"] = False
    payload["cvd_tight_at"] = None


# ---------------------------------------------------------------------------
# Đang giữ lệnh: CVD 1H
# ---------------------------------------------------------------------------
def cvd_exit_step(open_trade: dict, h_open, r1) -> bool:
    """
    Gọi khi nến 1H mở lúc h_open vừa đóng, r1 = độ dốc 1H tại nến đó. Cập nhật bộ đếm "ngược" trong open_trade.
    Trả True khi cần ĐÓNG lệnh (M6_EXIT_MODE=close); chế độ tighten chỉ đánh dấu open_trade["cvd_tight"].
    Mỗi nến 1H chỉ đếm một lần (cvd_last_h).
    """
    mode = settings.M6_EXIT_MODE
    if mode not in ("tighten", "close") or h_open is None:
        return False
    h = pd.Timestamp(h_open)
    last = open_trade.get("cvd_last_h")
    if last is not None and h <= pd.Timestamp(last):
        return False
    entry_time = open_trade.get("entry_time")
    try:
        et = pd.Timestamp(entry_time)
        if h < et.floor("h"):
            return False  # nến 1H trước lúc vào lệnh
        held_h = (h + pd.Timedelta(hours=1) - et).total_seconds() / 3600
    except (TypeError, ValueError):
        return False
    open_trade["cvd_last_h"] = h
    if r1 is None or (isinstance(r1, float) and math.isnan(r1)):
        return False
    side = open_trade["side"]
    th = float(settings.M6_EXIT_AGAINST_RATIO)
    against = r1 < -th if side == "LONG" else r1 > th
    n = int(open_trade.get("cvd_against_n") or 0) + 1 if against else 0
    open_trade["cvd_against_n"] = n
    if held_h < float(settings.M6_EXIT_MIN_HOURS) or n < max(1, int(settings.M6_EXIT_CONFIRM_BARS)):
        return False
    if mode == "close":
        return True
    if not open_trade.get("cvd_tight"):
        open_trade["cvd_tight"] = True
        open_trade["cvd_tight_at"] = h + pd.Timedelta(hours=1)
    return False


def cvd_trailing_multiplier(open_trade: dict, base: float) -> float:
    """Sau khi CVD 1H ngược lệnh: hệ số trailing = min(hệ số đang dùng, M6_TIGHT_ATR_MULT). Stop chỉ đi về phía có lợi."""
    if open_trade.get("cvd_tight"):
        return min(float(base), float(settings.M6_TIGHT_ATR_MULT))
    return float(base)
