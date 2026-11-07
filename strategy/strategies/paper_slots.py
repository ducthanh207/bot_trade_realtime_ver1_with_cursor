# -*- coding: utf-8 -*-
from strategy.strategies.registry import METHOD_1, METHOD_2, METHOD_3, METHOD_4, METHOD_5

SLOT_METHOD = {
    1: METHOD_1,
    2: METHOD_2,
    3: METHOD_3,
    4: METHOD_4,
    5: METHOD_5,  # [2026-11-07] Paper 5 = PP5
}


def method_for_paper_slot(slot_id: int) -> str:
    try:
        sid = int(slot_id)
    except (TypeError, ValueError):
        return METHOD_1
    return SLOT_METHOD.get(sid, METHOD_1)
