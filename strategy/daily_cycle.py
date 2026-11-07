# -*- coding: utf-8 -*-
"""
[2026-11-07] Phương pháp 5 (PP5) = PP4 + lọc chu kỳ theo nến ngày (1D).

Mọi phép xét đều dùng GIÁ ĐÓNG CỬA của nến 1D ĐÃ ĐÓNG (râu/thân nến cắt EMA không tính).
d = (close − EMA) / EMA của chính ngày đó.

Hai lớp trạng thái, tính tuần tự từ nến cũ tới nến mới:

1) Xu hướng (TĂNG / GIẢM):
   - Vào TĂNG: M5_CONFIRM_BARS (2) nến liên tiếp đóng trên EMA, hoặc ĐỘT BIẾN TĂNG: đường lower của
     %change (close × (1 − h%)) nằm trên EMA, tức d > h% → vào ngay, không chờ nến thứ 2.
   - Duy trì: một nến lẻ đóng dưới EMA chưa kết thúc chu kỳ.
   - Kết thúc: 2 nến liên tiếp đóng dưới EMA = vào GIẢM. GIẢM là đối xứng.
   - Chưa có tín hiệu nào từ đầu dữ liệu → TRUNG TÍNH (chạy như PP4 gốc, cả hai phía).

2) Đi ngang (đè lên xu hướng): M5_SIDEWAYS_BARS (3) nến gần nhất đều có |d| <= X.
   X = M5_SIDEWAYS_ATR_K × ATR14(1D) / close (MODE=atr, mặc định) hoặc M5_SIDEWAYS_PCT % (MODE=pct).
   - Nến đóng gần nhất trên EMA → ĐI NGANG THIÊN LONG (3.1), dưới EMA → THIÊN SHORT (3.2)
     (M5_SIDEWAYS_MIXED=latest, mặc định). both/skip: khi 3 nến nằm lẫn hai phía EMA thì vào cả hai
     phía / bỏ lệnh.
   - Kết thúc khi có nến đóng với |d| > X (đột biến) → quay về trạng thái xu hướng ở lớp 1.

Hành động (m5_entry_decision): TĂNG chỉ LONG, GIẢM chỉ SHORT, đi ngang theo phía + "thoát nới"
(trailing M5_WIDE_ATR_MULTIPLIER cố định, size × M5_WIDE_SIZE_MULT, chốt lời dải %change, Exit B đã sửa).
Lệnh đang mở khi chu kỳ đổi: giữ nguyên, chỉ áp cho lệnh mới.

Dùng chung cho bot (bot/slot_engine.py, strategy/exit_engine.py) và backtest (backtest/live_replay.py).
"""

from __future__ import annotations

import math

import pandas as pd

from config import settings

CYCLE_UP = "UP"
CYCLE_DOWN = "DOWN"
CYCLE_NEUTRAL = "NEUTRAL"
CYCLE_SIDE_LONG = "SIDE_LONG"
CYCLE_SIDE_SHORT = "SIDE_SHORT"
CYCLE_SIDE_MIXED = "SIDE_MIXED"
SIDEWAYS = (CYCLE_SIDE_LONG, CYCLE_SIDE_SHORT, CYCLE_SIDE_MIXED)

_LABELS = {
    CYCLE_UP: "Tăng (chỉ LONG)",
    CYCLE_DOWN: "Giảm (chỉ SHORT)",
    CYCLE_NEUTRAL: "Trung tính (cả hai phía)",
    CYCLE_SIDE_LONG: "Đi ngang thiên LONG",
    CYCLE_SIDE_SHORT: "Đi ngang thiên SHORT",
    CYCLE_SIDE_MIXED: "Đi ngang hai phía",
}


def cycle_label(cycle) -> str:
    return _LABELS.get(cycle, "Chưa có dữ liệu nến ngày")

_COLS = ["open", "high", "low", "close", "volume"]


def _pct_change_half_width(df_1d: pd.DataFrame) -> pd.Series:
    """h% của chỉ báo %change trên nến ngày tại từng nến (0 khi chưa có lệnh mô phỏng nào)."""
    from strategy.pct_change_avg import build_pct_change_avg_bands_series

    cols = [c for c in _COLS if c in df_1d.columns]
    bands = build_pct_change_avg_bands_series(df_1d[cols], lookback_trades=settings.M5_PCT_LOOKBACK_TRADES)
    up, mid = bands["lines"]["upper"], bands["lines"]["mid"]
    if not up:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex([p["time"] for p in up])
    return pd.Series([(u["value"] / m["value"] - 1) * 100 for u, m in zip(up, mid)], index=idx)


def daily_cycle_table(df_1d_closed: pd.DataFrame) -> pd.DataFrame:
    """
    Bảng chu kỳ cho từng nến 1D đã đóng: close, ema, d (%), x (%), h (%), trend, cycle.
    df_1d_closed: nến ngày ĐÃ ĐÓNG (không có nến đang chạy), cột open/high/low/close.
    """
    import pandas_ta as ta

    if df_1d_closed is None or df_1d_closed.empty:
        return pd.DataFrame()
    df = df_1d_closed.sort_index()
    close = df["close"].astype(float)
    ema = ta.ema(close, length=settings.M5_DAILY_EMA_LEN)
    atr = ta.atr(df["high"].astype(float), df["low"].astype(float), close, length=14)
    if ema is None:
        return pd.DataFrame()
    h = _pct_change_half_width(df) if settings.M5_SPIKE_ENABLED else pd.Series(dtype=float)
    h = h.reindex(df.index).fillna(0.0)

    mode = settings.M5_SIDEWAYS_MODE
    xs = []
    for ts in df.index:
        c = float(close.loc[ts])
        if mode == "pct":
            xs.append(float(settings.M5_SIDEWAYS_PCT))
        else:
            a = atr.loc[ts] if atr is not None else float("nan")
            xs.append(float(settings.M5_SIDEWAYS_ATR_K) * float(a) / c * 100 if pd.notna(a) and c > 0 else float("nan"))
    return classify_cycles(df.index, close.to_numpy(float), ema.to_numpy(float), xs, h.to_numpy(float))


def classify_cycles(times, closes, emas, xs, hs) -> pd.DataFrame:
    """
    Máy trạng thái chu kỳ trên chuỗi nến ngày đã đóng (từ cũ tới mới).
    closes/emas: giá; xs: ngưỡng đi ngang X (%) từng ngày; hs: h% của %change từng ngày (0 = chưa có).
    """
    confirm = max(1, int(settings.M5_CONFIRM_BARS))
    nside = max(1, int(settings.M5_SIDEWAYS_BARS))
    mixed_mode = settings.M5_SIDEWAYS_MIXED

    rows = []
    trend = CYCLE_NEUTRAL
    run_above = run_below = 0
    hist = []  # (d, x) các nến gần nhất cho lớp đi ngang
    for ts, c, e, x, hp in zip(times, closes, emas, xs, hs):
        c, e, x, hp = float(c), float(e), float(x), float(hp) if not pd.isna(hp) else 0.0
        if math.isnan(e) or not e or c <= 0:
            continue
        d = (c - e) / e * 100

        # Lớp 1: xu hướng
        if c > e:
            run_above, run_below = run_above + 1, 0
        elif c < e:
            run_above, run_below = 0, run_below + 1
        else:
            run_above = run_below = 0
        spike_up = hp > 0 and c * (1 - hp / 100) > e      # đường lower %change nằm trên EMA
        spike_down = hp > 0 and c * (1 + hp / 100) < e    # đường upper %change nằm dưới EMA
        if run_above >= confirm or spike_up:
            trend = CYCLE_UP
        elif run_below >= confirm or spike_down:
            trend = CYCLE_DOWN

        # Lớp 2: đi ngang
        hist.append((d, x))
        hist = hist[-nside:]
        cycle = trend
        if len(hist) == nside and all(not math.isnan(xx) and abs(dd) <= xx for dd, xx in hist):
            above = [dd > 0 for dd, _ in hist]
            if all(above):
                cycle = CYCLE_SIDE_LONG
            elif not any(above):
                cycle = CYCLE_SIDE_SHORT
            elif mixed_mode in ("both", "skip"):
                cycle = CYCLE_SIDE_MIXED
            else:  # latest: theo giá đóng nến gần nhất
                cycle = CYCLE_SIDE_LONG if d > 0 else CYCLE_SIDE_SHORT
        rows.append({"time": ts, "close": c, "ema": e, "d": d, "x": x, "h": hp, "trend": trend, "cycle": cycle})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("time")


def daily_cycle_info(df_1d_closed: pd.DataFrame) -> dict:
    """Chu kỳ tại nến 1D đã đóng gần nhất: {"cycle", "trend", "d", "x", "h", "day"}; thiếu dữ liệu → cycle None."""
    out = {"cycle": None, "trend": None, "d": None, "x": None, "h": None, "day": None}
    try:
        tab = daily_cycle_table(df_1d_closed)
    except (KeyError, TypeError, ValueError, IndexError):
        return out
    if tab.empty:
        return out
    last = tab.iloc[-1]
    out.update(
        cycle=last["cycle"], trend=last["trend"], day=tab.index[-1],
        d=round(float(last["d"]), 3), x=None if pd.isna(last["x"]) else round(float(last["x"]), 3),
        h=round(float(last["h"]), 3),
    )
    return out


def m5_entry_decision(side: str, cycle: str | None):
    """Trả (allow, wide). Không có dữ liệu ngày → không vào lệnh."""
    if not cycle:
        return False, False
    if cycle == CYCLE_NEUTRAL:
        return True, False
    if cycle == CYCLE_UP:
        return side == "LONG", False
    if cycle == CYCLE_DOWN:
        return side == "SHORT", False
    if cycle == CYCLE_SIDE_LONG:
        return side == "LONG", True
    if cycle == CYCLE_SIDE_SHORT:
        return side == "SHORT", True
    if cycle == CYCLE_SIDE_MIXED:
        both = settings.M5_SIDEWAYS_MIXED == "both"
        return both, both
    return False, False


def m5_apply_cycle_to_payload(payload: dict, side: str, info: dict, wide: bool) -> None:
    """Ghi chu kỳ vào lệnh vừa mở; lệnh đi ngang → hệ số trailing nới + stop ban đầu tương ứng."""
    payload["m5_cycle"] = info.get("cycle")
    payload["m5_d_pct"] = info.get("d")
    payload["m5_x_pct"] = info.get("x")
    payload["m5_h_pct"] = info.get("h")
    payload["m5_wide"] = bool(wide)
    if wide:
        mult = settings.M5_WIDE_ATR_MULTIPLIER
        dist = float(payload["atr"]) * mult
        entry = float(payload["entry_price"])
        payload["atr_multiplier_override"] = mult
        payload["trail_stop"] = entry - dist if side == "LONG" else entry + dist


def m5_trailing_multiplier(open_trade: dict, now_ts) -> float:
    """PP5: lệnh đi ngang → hệ số nới cố định; còn lại y hệt PP4 gốc (grace 2.5 trong 12h rồi 2.2)."""
    if open_trade.get("m5_wide"):
        return float(settings.M5_WIDE_ATR_MULTIPLIER)
    g, m, gh = settings.M4_ATR_MULTIPLIER_GRACE, settings.M4_ATR_MULTIPLIER, settings.M4_ATR_GRACE_HOURS
    entry_time = open_trade.get("entry_time")
    try:
        if entry_time is not None and getattr(entry_time, "tzinfo", None) is not None and now_ts is not None:
            elapsed = (pd.Timestamp(now_ts) - pd.Timestamp(entry_time)).total_seconds() / 3600
            return g if elapsed < gh else m
    except (TypeError, ValueError):
        pass
    return m


def m5_exit_b_fixed(open_trade: dict) -> bool:
    """Lệnh PP5 này dùng Exit B đã sửa (RSI nến 4H đã đóng) không?"""
    mode = settings.M5_EXIT_B
    if mode == "all":
        return True
    if mode == "wide":
        return bool(open_trade.get("m5_wide"))
    return False
