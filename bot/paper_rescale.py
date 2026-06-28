# -*- coding: utf-8 -*-
"""Rescale paper trade state khi đổi initial capital."""
from bot import state as _state


def apply_new_initial_with_volumetric_rescale(slot: int, new_initial: float) -> dict:
    slot = int(slot)
    if slot == 2:
        old_initial = _state.get_paper2_initial_capital()
        old_balance = _state.get_paper2_balance()
        trades = _state.get_paper2_trades()
        get_open = _state.get_paper2_open_trade
        set_initial = _state.set_paper2_initial_capital
        set_balance = _state.set_paper2_balance
        restore = _state.restore_paper2_trades
    else:
        old_initial = _state.get_paper_initial_capital()
        old_balance = _state.get_paper_balance()
        trades = _state.get_paper_trades()
        get_open = _state.get_paper_open_trade
        set_initial = _state.set_paper_initial_capital
        set_balance = _state.set_paper_balance
        restore = _state.restore_paper_trades

    if not old_initial or old_initial <= 0:
        set_initial(new_initial)
        set_balance(new_initial)
        return {"ratio": 1.0}

    ratio = new_initial / old_initial
    rescaled = []
    for t in trades:
        r = dict(t)
        for key in ("size", "margin", "profit", "capital_before", "capital_after"):
            if r.get(key) is not None:
                try:
                    r[key] = float(r[key]) * ratio
                except (TypeError, ValueError):
                    pass
        rescaled.append(r)
    restore(rescaled)
    set_initial(new_initial)
    set_balance(old_balance * ratio)
    return {"ratio": ratio}
