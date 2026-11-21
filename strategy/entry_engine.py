# -*- coding: utf-8 -*-
"""
[2026-11-21] Quyết định VÀO LỆNH dùng chung cho paper/live (bot/slot_engine.py) và backtest (backtest/live_replay.py).

Trước đây hai nơi chép cùng một chuỗi `if method in _M3_FAMILY ...`. Giờ cả hai gọi plan_entry(disk, ...) với
đĩa chiến lược (strategy/disks.py): đĩa cho biết khung (pp1..pp4) và khối nào bật, còn thứ tự các bước lọc
giữ nguyên như code cũ nên PP1–PP7 vào lệnh y hệt trước (tests/test_disks.py so sánh với kết quả đã ghi).

Thứ tự: tín hiệu 4H → lọc PP4 (RSI cực trị, RSI 1H) → giai đoạn (regime_cut) → chu kỳ ngày (daily_cycle)
→ CVD 4H (cvd) → khung PP3 (vùng ADX, trend EMA50, swing, chuỗi thua) → size → ATR / stop ban đầu.
Circuit breaker do nơi gọi kiểm tra trước (mỗi nơi giữ đồng hồ riêng: giờ thật hoặc giờ mô phỏng).
"""

from __future__ import annotations

from config import settings
from strategy.signals import long_entry, short_entry, m4_entry_1h_confirm, m4_entry_rsi_extreme_block
from strategy.risk import size_and_margin, atr_1h_at_entry, m3_adx_zone, m4_adx_zone, m3_streak_multiplier
from strategy.regime import m4_regime_entry_decision, m4_apply_regime_to_payload
from strategy.daily_cycle import m5_entry_plan, m5_apply_cycle_to_payload
from strategy import cvd as cvd_mod
from strategy.pp7 import m7_trend_allows, m7_stop_distance, m7_size_and_margin


def plan_entry(disk, *, prev_row_closed, row_closed, get_row_m3, df_1h, get_regime, get_daily, get_cvd,
               get_ema_ref, losses: int, balance: float, entry_px: float, leverage: float, wallet_pct: float,
               m3_grace_mult: float):
    """
    Trả None (không vào) hoặc dict kế hoạch: side, size, margin, notional, atr, atr_mult, init_stop + dữ liệu
    để apply_entry_extras ghi thêm vào lệnh. Các get_* là hàm (chỉ gọi khi khối cần, như code cũ).
    """
    row_m3 = get_row_m3() if disk.m3 else None

    sig_long = long_entry(prev_row_closed, row_closed)
    sig_short = short_entry(prev_row_closed, row_closed)
    if not (sig_long or sig_short):
        return None
    side = "LONG" if sig_long else "SHORT"

    # Khung PP4: chặn RSI cực trị + cần xác nhận hướng RSI 1H
    if disk.m4:
        if m4_entry_rsi_extreme_block(side, row_closed.get("RSI")):
            return None
        if getattr(settings, "M4_REQUIRE_1H_CONFIRM", True) and not m4_entry_1h_confirm(side, df_1h):
            return None

    # Khối regime_cut (PP4): nhận diện giai đoạn (mặc định tắt)
    m4_regime, m4_tight = {}, False
    if disk.regime and getattr(settings, "M4_REGIME_ENABLED", False):
        m4_regime = get_regime() or {}
        allow_regime, m4_tight = m4_regime_entry_decision(side, m4_regime.get("regime"))
        if not allow_regime:
            return None

    # Khối daily_cycle (PP5) — ghép với cvd (PP6.1) thì đi ngang chọn phía theo CVD
    m5_info, m5_wide, m5_size, m5_counter = {}, False, 1.0, False
    cvd = get_cvd() if disk.cvd else {}
    if disk.daily:
        m5_info = get_daily() or {}
        if disk.cvd:
            allow_cycle, m5_wide, m5_size, m5_counter = cvd_mod.m61_entry_plan(side, m5_info.get("cycle"), cvd.get("r_side"))
        else:
            allow_cycle, m5_wide, m5_size, m5_counter = m5_entry_plan(side, m5_info.get("cycle"))
        if not allow_cycle:
            return None

    # Khối cvd (PP6): CVD 4H (và tuỳ chọn 1H) cùng chiều lệnh
    if disk.cvd and not cvd_mod.cvd_entry_ok(side, cvd.get("r4"), cvd.get("r1")):
        return None

    # Khung PP3: vùng ADX, trend EMA50, swing, chuỗi thua
    size_mult = 1.0
    if disk.m3 and row_m3 is not None:
        adx_val = float(row_m3.get("ADX", 25.0) or 25.0)
        allow, adx_size_mult = m4_adx_zone(adx_val) if disk.m4 else m3_adx_zone(adx_val)
        if not allow:
            return None
        size_mult = adx_size_mult
        if disk.trend_always:
            # Khối trend_filter_always (PP7): lọc trend EMA50 luôn bật (PP4 chỉ lọc khi ADX > 30)
            if not m7_trend_allows(side, row_m3.get("close"), row_m3.get("EMA_TREND"), get_ema_ref()):
                return None
        elif adx_val > getattr(settings, "M3_EMA_TREND_ADX_ABOVE", 30.0):
            ema_trend_val = float(row_m3.get("EMA_TREND", 0.0) or 0.0)
            close_val = float(row_m3.get("close", 0.0) or 0.0)
            if ema_trend_val > 0 and close_val > 0:
                if side == "LONG" and close_val < ema_trend_val:
                    return None
                if side == "SHORT" and close_val > ema_trend_val:
                    return None
        disagree_size = getattr(settings, "M3_SWING_DISAGREE_SIZE", 0.6)
        higher_low = bool(row_m3.get("higher_low", False))
        lower_high = bool(row_m3.get("lower_high", False))
        if side == "LONG" and lower_high and not higher_low:
            size_mult = min(size_mult, disagree_size)
        elif side == "SHORT" and higher_low and not lower_high:
            size_mult = min(size_mult, disagree_size)
        size_mult = size_mult * m3_streak_multiplier(losses)
    if disk.daily and m5_wide:
        size_mult = size_mult * float(settings.M5_WIDE_SIZE_MULT)
    if disk.daily and m5_counter:  # lệnh ngược chu kỳ (mặc định không có)
        size_mult = size_mult * float(m5_size)

    # Size
    if disk.risk_sizing:
        # Khối risk_sizing (PP7): size theo rủi ro, stop = M7_ATR4H_MULT × ATR 4H của nến vừa đóng
        dist = m7_stop_distance(row_closed.get("ATR"))
        if dist is None:
            return None
        size, margin, notional = m7_size_and_margin(balance, entry_px, dist, size_mult, leverage, wallet_pct)
    else:
        size, margin, notional = size_and_margin(balance, entry_px, leverage=leverage, wallet_pct=wallet_pct)
        if disk.m3 and size_mult < 1.0:
            size, margin, notional = size * size_mult, margin * size_mult, notional * size_mult
    if size <= 0 or margin > balance:
        return None

    # ATR + hệ số trailing lúc mở
    atr_now = atr_1h_at_entry(df_1h, float(row_closed["ATR"]))
    if disk.stop4h:
        atr_now = float(row_closed["ATR"])
        atr_mult_now = settings.M7_ATR4H_MULT
    elif disk.pp3_only:
        atr_mult_now = m3_grace_mult
    elif disk.m4:
        atr_mult_now = settings.M4_ATR_MULTIPLIER_GRACE
    else:
        atr_mult_now = settings.ATR_MULTIPLIER
    trail_dist = atr_now * atr_mult_now
    init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist

    return {
        "side": side, "size": size, "margin": margin, "notional": notional,
        "atr": atr_now, "atr_mult": atr_mult_now, "init_stop": init_stop,
        "_m4_regime": m4_regime, "_m4_tight": m4_tight,
        "_m5_info": m5_info, "_m5_wide": m5_wide, "_m5_counter": m5_counter, "_cvd": cvd,
    }


def apply_entry_extras(disk, payload: dict, plan: dict, row_closed) -> None:
    """Ghi phần riêng của từng khối vào lệnh vừa tạo (sau khi nơi gọi đã điền các trường chung)."""
    side = plan["side"]
    if disk.m3:
        payload["atr_multiplier_override"] = plan["atr_mult"]
    if disk.m4:
        payload["max_stop_capital_pct"] = (settings.M7_MAX_STOP_CAPITAL_PCT if disk.stop4h
                                           else settings.M4_MAX_STOP_CAPITAL_PCT)
    if disk.regime and (getattr(settings, "M4_REGIME_ENABLED", False) or getattr(settings, "M4_INVALIDATION_EXIT", False)):
        m4_apply_regime_to_payload(payload, side, plan["_m4_regime"], plan["_m4_tight"], row_closed)
    if disk.daily:
        m5_apply_cycle_to_payload(payload, side, plan["_m5_info"], plan["_m5_wide"], plan["_m5_counter"])
    if disk.cvd:
        cvd = plan["_cvd"]
        cvd_mod.apply_cvd_to_payload(payload, cvd.get("r4"), cvd.get("r1"), cvd.get("r_side"))
