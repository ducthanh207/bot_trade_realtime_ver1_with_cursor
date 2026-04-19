# -*- coding: utf-8 -*-
"""
Đối chiếu vốn / PnL paper: cùng logic replay CSV (phí vào + profit đóng).

Chạy script: python tools/paper_reconcile_check.py --slot 2
Hoặc khi web bật: GET /api/paper/reconcile?slot=2
"""

from __future__ import annotations

import hashlib
from typing import Any


def trade_key_closed(t: dict) -> str:
    parts = [
        str(t.get("entry_time", "")),
        str(t.get("exit_time", "")),
        str(t.get("entry_price", "")),
        str(t.get("exit_price", "")),
        str(t.get("side", "")),
        format(float(t.get("profit", 0) or 0), ".8f"),
    ]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def infer_initial_capital(trades_chrono: list, state_initial: float, taker_fee: float) -> float:
    """
    Mốc replay / %PnL vốn / Cap After trên UI & CSV:
    - Ưu tiên vốn đã cấu hình trong state (paper*_initial_capital > 0) để đổi mốc là tính lại đồng bộ.
    - Nếu state = 0 nhưng có lịch sử: suy từ lệnh đầu (bản cũ / thiếu persistence).
    """
    ini = float(state_initial or 0)
    if ini > 0:
        return ini
    if trades_chrono:
        t0 = trades_chrono[0]
        entry = float(t0.get("entry_price") or 0)
        size = float(t0.get("size") or 0)
        cb = float(t0.get("capital_before") or 0)
        fee0 = size * entry * float(taker_fee) if size and entry else 0.0
        inferred = cb + fee0
        if inferred > 0:
            return inferred
    return 0.0


def paper_ledger_meta(trades_chrono: list, initial: float, taker_fee: float) -> list:
    run = float(initial or 0)
    out = []
    for idx, t in enumerate(trades_chrono):
        entry = float(t.get("entry_price") or 0)
        size = float(t.get("size") or 0)
        profit = float(t.get("profit") or 0)
        fee_in = size * entry * float(taker_fee) if size and entry else 0.0
        cap_equity_before_open = run
        run -= fee_in
        run += profit
        out.append(
            {
                "replay_index": idx,
                "trade_key": trade_key_closed(t),
                "capital_equity_before_open": round(cap_equity_before_open, 2),
                "capital_after_close": round(run, 2),
                "fee_entry": round(fee_in, 8),
            }
        )
    return out


def _entry_fee(t: dict, taker_fee: float) -> float:
    entry = float(t.get("entry_price") or 0)
    size = float(t.get("size") or 0)
    return size * entry * float(taker_fee) if size and entry else 0.0


def reconcile_trades(
    trades_chrono: list,
    state_initial: float,
    taker_fee: float,
    live_balance: float | None = None,
    has_open: bool = False,
) -> dict[str, Any]:
    """
    trades_chrono: list đã đóng, thứ tự cũ → mới (như state.get_*_trades()).
    profit trong từng trade: đã trừ phí thoát; phí vào không nằm trong profit (bot trừ balance lúc mở).
    """
    initial = infer_initial_capital(trades_chrono, state_initial, taker_fee)
    meta = paper_ledger_meta(trades_chrono, initial, taker_fee)
    sum_profit = sum(float(t.get("profit") or 0) for t in trades_chrono)
    sum_fee_in = sum(_entry_fee(t, taker_fee) for t in trades_chrono)
    replay_end = float(meta[-1]["capital_after_close"]) if meta else float(initial)

    formula = initial - sum_fee_in + sum_profit
    formula_ok = abs(replay_end - formula) < 0.02

    last_stored = None
    if trades_chrono:
        last_stored = float(trades_chrono[-1].get("capital_after") or 0)

    diff_replay_stored = None
    if last_stored is not None:
        diff_replay_stored = round(replay_end - last_stored, 4)

    diff_balance = None
    if not has_open and live_balance is not None:
        diff_balance = round(float(live_balance) - replay_end, 4)

    return {
        "closed_trades": len(trades_chrono),
        "state_initial_capital": round(float(state_initial or 0), 4),
        "replay_initial_capital": round(float(initial), 4),
        "sum_profit_closed": round(sum_profit, 8),
        "sum_entry_fees": round(sum_fee_in, 8),
        "replay_final_after_last_close": round(replay_end, 4),
        "identity_replay_equals_initial_minus_fees_plus_profit": formula_ok,
        "identity_detail": round(formula, 4),
        "stored_last_trade_capital_after": round(last_stored, 4) if last_stored is not None else None,
        "diff_replay_final_minus_stored_last_capital_after": diff_replay_stored,
        "wrong_excel_state_initial_plus_sum_profit": round(float(state_initial or 0) + sum_profit, 4),
        "wrong_excel_replay_initial_plus_sum_profit_only": round(initial + sum_profit, 4),
        "correct_closed_wallet_replay": round(replay_end, 4),
        "has_open_position": bool(has_open),
        "live_balance": round(float(live_balance), 4) if live_balance is not None else None,
        "diff_live_balance_minus_replay_final_when_flat": diff_balance,
        "hints_vi": [
            "Paper (slot=1) và Paper 2 (slot=2) là hai ví riêng — đừng so CSV slot 1 với số hiển thị Paper 2.",
            "Nếu paper*_initial_capital > 0: mốc replay = giá trị đó (đổi qua UI «Lưu mốc vốn») — Cap After / %PnL vốn tính lại theo mốc; balance ví sim là thực tế bot, có thể khác nếu chỉ đổi mốc hiển thị.",
            "Cột profit = PnL vị thế (đã trừ phí thoát); Excel: initial + SUM(wallet_change) với wallet_change = profit − entry_fee.",
        ],
    }
