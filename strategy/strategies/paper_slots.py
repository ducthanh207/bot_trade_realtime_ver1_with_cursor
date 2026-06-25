# -*- coding: utf-8 -*-
from strategy.strategies.registry import METHOD_1, METHOD_2, METHOD_3

SLOT_METHOD = {
    1: METHOD_1,
    2: METHOD_2,
    3: METHOD_3,
}


def method_for_paper_slot(slot_id: int) -> str:
    try:
        sid = int(slot_id)
    except (TypeError, ValueError):
        return METHOD_1
    return SLOT_METHOD.get(sid, METHOD_1)
