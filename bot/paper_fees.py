# -*- coding: utf-8 -*-
"""
Phí paper trade — một nguồn dùng chung cho loop thoát lệnh, web, CSV.

Mô hình (đồng bộ với code hiện tại, gần Binance USDT-M taker):
- Phí = |khối lượng hợp đồng| × giá × TAKER_FEE (notional × tỷ lệ).
- Vào lệnh: trừ ví một lần (paper_loop).
- Thoát lệnh: trừ trong PnL ứng viên thoát (exit_engine).

TAKER_FEE lấy từ config (.env / settings), mặc định 0.0004 — không mô phỏng VIP/BNB/funding.
"""

from __future__ import annotations

from typing import Any, Optional


def linear_taker_fee_usdt(size: Any, price: Any, taker_rate: float) -> float:
    """Phí taker một chiều (USDT) theo notional."""
    try:
        s = float(size or 0)
        p = float(price or 0)
        r = float(taker_rate)
    except (TypeError, ValueError):
        return 0.0
    if s <= 0 or p <= 0 or r < 0:
        return 0.0
    return s * p * r


def closed_trade_fee_entry_exit_usdt(trade: dict, taker_rate: float) -> tuple[float, float, float]:
    """Lệnh đã đóng: (phí vào, phí thoát, tổng)."""
    fe = linear_taker_fee_usdt(trade.get("size"), trade.get("entry_price"), taker_rate)
    fx = linear_taker_fee_usdt(trade.get("size"), trade.get("exit_price"), taker_rate)
    return fe, fx, fe + fx


def open_trade_entry_fee_usdt(open_trade: Optional[dict], taker_rate: float) -> float:
    if not open_trade:
        return 0.0
    return linear_taker_fee_usdt(open_trade.get("size"), open_trade.get("entry_price"), taker_rate)


def slot_total_fees_usdt(
    closed_trades: Optional[list],
    open_trade: Optional[dict],
    taker_rate: float,
) -> float:
    """Tổng phí slot: tất cả lệnh đóng (vào + thoát) + phí vào lệnh đang mở (nếu có)."""
    tot = 0.0
    for t in closed_trades or []:
        tot += closed_trade_fee_entry_exit_usdt(t, taker_rate)[2]
    tot += open_trade_entry_fee_usdt(open_trade, taker_rate)
    return round(tot, 2)


def wallet_balance_after_replay(
    chronological_closed_trades: Optional[list],
    initial: float,
    taker_rate: float,
    open_trade: Optional[dict],
) -> float:
    """
    Số dư ví sau khi áp lại toàn bộ lệnh đã đóng (cũ → mới) từ mốc `initial`,
    cùng thứ tự paper_loop: mỗi lệnh trừ phí vào, cộng profit (profit đã trừ phí thoát).
    Có lệnh mở: trừ thêm phí vào lệnh hiện tại → đúng `paper_balance` lúc đang giữ vị thế.
    """
    run = float(initial or 0)
    for t in chronological_closed_trades or []:
        run -= linear_taker_fee_usdt(t.get("size"), t.get("entry_price"), taker_rate)
        try:
            run += float(t.get("profit") or 0)
        except (TypeError, ValueError):
            pass
    if open_trade:
        run -= linear_taker_fee_usdt(open_trade.get("size"), open_trade.get("entry_price"), taker_rate)
    return round(run, 2)
