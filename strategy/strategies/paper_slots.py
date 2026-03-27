# -*- coding: utf-8 -*-
"""
Ánh xạ slot Paper trên web (paper.js: slot 1, 2, …) → hằng phương pháp METHOD_*.

- Slot 1 = Phương pháp 1 (logic cổ điển, không gắn %change).
- Slot 2 = Phương pháp 2 (có TP %change + lọc RSI 1H trong exit_engine).

Mở rộng sau: thêm METHOD_3, state paper3, API /paper3, rồi bổ sung SLOT_METHOD[3] = METHOD_3.
"""

from strategy.strategies.registry import METHOD_1, METHOD_2

# Mỗi khóa = paper_slot (int) như trong closed["paper_slot"] / PAPER_UI.slot
SLOT_METHOD = {
    1: METHOD_1,
    2: METHOD_2,
}


def method_for_paper_slot(slot_id: int) -> str:
    """Trả về METHOD_* cho slot; slot lạ → METHOD_1 (an toàn)."""
    try:
        sid = int(slot_id)
    except (TypeError, ValueError):
        return METHOD_1
    return SLOT_METHOD.get(sid, METHOD_1)
