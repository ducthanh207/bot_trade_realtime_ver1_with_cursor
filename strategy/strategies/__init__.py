# -*- coding: utf-8 -*-
"""
Đăng ký phương pháp giao dịch (chiến lược) để so sánh / backtest.

- Phương pháp 1: thoát theo logic cũ (ATR trail, tín hiệu 4H, early exit, SL max loss).
- Phương pháp 2: cùng nền tảng + TP theo %change khi đảo chiều RSI 1H + chạm dải;
  các thoát theo tín hiệu 4H/early chỉ khi PnL dương và có đảo chiều RSI 1H.
"""

from strategy.strategies.registry import (
    METHOD_1,
    METHOD_2,
    get_trading_method,
    get_method_label,
    describe_method,
    uses_pct_change_bands,
)
from strategy.strategies.paper_slots import SLOT_METHOD, method_for_paper_slot

__all__ = [
    "METHOD_1",
    "METHOD_2",
    "get_trading_method",
    "get_method_label",
    "describe_method",
    "uses_pct_change_bands",
    "SLOT_METHOD",
    "method_for_paper_slot",
]
