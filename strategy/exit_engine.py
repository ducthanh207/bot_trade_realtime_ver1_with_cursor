# -*- coding: utf-8 -*-
"""
Tính toán các ứng viên thoát lệnh (paper + live) theo phương pháp 1 hoặc 2.

Phương pháp 1: giữ hành vi cũ (4H exit / early không lọc PnL hay RSI 1H).
Phương pháp 2: 4H exit và early chỉ khi PnL thô > 0 và có đảo chiều RSI trên 2 nến 1H đã đóng;
thêm PCT_CHANGE_TP khi PnL>0, đảo chiều RSI 1H, và giá (trong nến 4H đang chạy) chạm dải upper/lower %change.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

import pandas as pd

from config import settings
from strategy.pct_change_avg import build_pct_change_avg_bands_series
from strategy.signals import long_exit, long_exit_early, short_exit, short_exit_early
from strategy.strategies.registry import METHOD_1, METHOD_2
from strategy.risk import (
    check_atr_trailing,
    limit_pnl_and_exit_price,
    max_loss_from_capital,
    refresh_atr_from_1h,
)

Candidate = Tuple[Any, float, float, str]


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def rsi_1h_reversal(side: str, df_1h: pd.DataFrame) -> bool:
    """
    So sánh RSI trên 2 nến 1H đã đóng gần nhất (iloc[-3] vs iloc[-2]).
    Long: đảo chiều giảm — RSI nến sau < nến trước.
    Short: đảo chiều tăng — RSI nến sau > nến trước.
    """
    if df_1h is None or df_1h.empty or len(df_1h) < 3:
        return False
    try:
        a = float(df_1h.iloc[-3]["RSI"])
        b = float(df_1h.iloc[-2]["RSI"])
        if pd.isna(a) or pd.isna(b):
            return False
        if side == "LONG":
            return b < a
        return b > a
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def touch_pct_band_in_forming_4h(
    side: str,
    df_1m: pd.DataFrame,
    upper: Optional[float],
    lower: Optional[float],
    forming_4h_open_time: Any,
) -> bool:
    """Trong khoảng từ mở nến 4H hiện tại đến nay, có nến 1m nào chạm upper (long) / lower (short)."""
    if upper is None or lower is None or df_1m is None or df_1m.empty:
        return False
    try:
        u = float(upper)
        lo = float(lower)
        sl = df_1m.loc[df_1m.index >= forming_4h_open_time]
        if sl.empty:
            sl = df_1m.tail(5)
        if side == "LONG":
            return bool((sl["high"].astype(float) >= u).any())
        return bool((sl["low"].astype(float) <= lo).any())
    except Exception:
        return False


def compute_exit_candidates(
    open_trade: dict,
    df_1m: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_4h_raw: pd.DataFrame,
    signal_prev,
    signal_curr,
    exit_px_ref: float,
    exit_time_ts: Any,
    *,
    paper_use_4h_window: bool,
    in_4h_window: bool,
    method: str,
    lookback_trades: int,
    allow_early_exit: bool,
) -> List[Candidate]:
    """
    Trả về danh sách (thời điểm, pnl_net ước lượng, exit_px, reason).
    """
    candidates: List[Candidate] = []
    if not open_trade:
        return candidates

    entry = float(open_trade["entry_price"])
    size = float(open_trade["size"])
    side = open_trade["side"]
    max_loss = max_loss_from_capital(open_trade)

    # ---------- LAYER 1: thanh lý + ATR 1m (giữ nguyên cả phương pháp 1 và 2) ----------
    last_check = open_trade.get("last_sl_check")
    if last_check is not None and not df_1m.empty:
        df_slice = df_1m.loc[df_1m.index >= last_check]
        refresh_atr_from_1h(open_trade, df_1h)
        margin = open_trade["margin"]
        notional = open_trade["notional"]
        maint = settings.MAINT_MARGIN_RATE * notional

        for t_1m, m1 in df_slice.iterrows():
            if side == "LONG":
                liq_px = entry + (maint - margin) / size
                if m1["low"] <= liq_px:
                    candidates.append((t_1m, -margin, liq_px, "LIQUIDATION"))
                    break
            else:
                liq_px = entry - (maint - margin) / size
                if m1["high"] >= liq_px:
                    candidates.append((t_1m, -margin, liq_px, "LIQUIDATION"))
                    break

            pnl_raw, exit_px = check_atr_trailing(open_trade, m1)
            if pnl_raw is not None:
                pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                if px_lim is not None:
                    exit_px = px_lim
                fee_out = size * exit_px * settings.TAKER_FEE
                candidates.append((t_1m, pnl_lim - fee_out, exit_px, "ATR_TRAIL"))
                break

    sp = _ensure_series(signal_prev)
    sc = _ensure_series(signal_curr)

    apply_4h_layer = True
    if paper_use_4h_window and not in_4h_window:
        apply_4h_layer = False

    sig_exit = bool(long_exit(sp, sc)) if side == "LONG" else bool(short_exit(sp, sc))
    sig_early = bool(long_exit_early(sp, sc)) if side == "LONG" else bool(short_exit_early(sp, sc))

    rev = rsi_1h_reversal(side, df_1h)

    if apply_4h_layer and sig_exit:
        pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
        take = True
        if method == METHOD_2:
            take = pnl_raw > 0 and rev
        if take:
            pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
            exit_px = px_lim if px_lim is not None else exit_px_ref
            fee_out = size * exit_px * settings.TAKER_FEE
            candidates.append((exit_time_ts, pnl_lim - fee_out, exit_px, "4H_EXIT"))

    if apply_4h_layer and allow_early_exit and sig_early:
        pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
        take = True
        if method == METHOD_2:
            take = pnl_raw > 0 and rev
        if take:
            pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
            exit_px = px_lim if px_lim is not None else exit_px_ref
            fee_out = size * exit_px * settings.TAKER_FEE
            candidates.append((exit_time_ts, pnl_lim - fee_out, exit_px, "4H_EARLY_EXIT"))

    # ---------- Phương pháp 2: TP theo %change ----------
    if method == METHOD_2 and df_4h_raw is not None and not df_4h_raw.empty:
        bands = build_pct_change_avg_bands_series(df_4h_raw, lookback_trades=lookback_trades)
        upper = bands.get("upper")
        lower = bands.get("lower")
        forming_t = df_4h_raw.index[-1]
        touched = touch_pct_band_in_forming_4h(side, df_1m, upper, lower, forming_t)
        pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
        if pnl_raw > 0 and rev and touched and upper is not None and lower is not None:
            if side == "LONG":
                exit_px = float(upper)
            else:
                exit_px = float(lower)
            pnl_raw2 = (exit_px - entry) * size if side == "LONG" else (entry - exit_px) * size
            pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw2, max_loss)
            if px_lim is not None:
                exit_px = px_lim
            fee_out = size * exit_px * settings.TAKER_FEE
            candidates.append((exit_time_ts, pnl_lim - fee_out, exit_px, "PCT_CHANGE_TP"))

    return candidates


def pick_best_exit(candidates: List[Candidate]) -> Optional[Candidate]:
    if not candidates:
        return None
    return min(candidates, key=lambda x: (x[0], -x[1]))
