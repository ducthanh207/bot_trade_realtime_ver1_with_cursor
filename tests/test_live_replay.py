# -*- coding: utf-8 -*-
"""
Kiểm tra backtest/live_replay.py khớp với code live:
- Tầng 1 (thanh lý / hard stop / ATR trailing) chạy nhanh từng phút phải cho cùng điểm thoát
  với việc gọi thẳng strategy.exit_engine.compute_exit_candidates mỗi tick như paper_loop.
- Chạy trọn vòng lặp trên dữ liệu giả lập không lỗi và sổ vốn khớp.
"""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backtest.live_replay import ALL_METHODS, MarketData, SlotSim, run_symbol
from strategy.exit_engine import compute_exit_candidates, pick_best_exit
from strategy.strategies.registry import METHOD_1, METHOD_4


def _synthetic_1m(days=40, seed=7):
    rng = np.random.default_rng(seed)
    n = 60 * 24 * days
    idx = pd.date_range("2025-01-01", periods=n, freq="1min", tz="UTC").tz_convert("Asia/Bangkok")
    ret = rng.normal(0, 0.0009, n) + 0.00002 * np.sin(np.arange(n) / (60 * 24 * 7))
    c = 60000 * np.exp(np.cumsum(ret))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.0004, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.0004, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx)


DF_1M = _synthetic_1m()
MD = MarketData("SYN", DF_1M, strict=False)
MD_STRICT = MarketData("SYN", DF_1M, strict=True)


def _df_1h_at(t):
    """df_1h như live tại t: iloc[-3], iloc[-2] = 2 nến 1H đã đóng, iloc[-1] = nến đang chạy."""
    closed = MD.ind1h.loc[: t - pd.Timedelta(hours=1)].tail(2)
    forming = closed.iloc[[-1]].copy()
    forming.index = pd.DatetimeIndex([t.floor("h")])
    return pd.concat([closed, forming])


def _open(slot, i, side, mult):
    t, px = MD.idx[i], float(MD.o[i])
    atr = float(MD.atr_at(i))
    size = slot.balance * slot.wallet_pct * slot.leverage / px
    ot = {
        "side": side, "entry_time": t, "entry_price": px, "size": size,
        "margin": slot.balance * slot.wallet_pct, "notional": size * px,
        "capital_before": slot.balance, "atr": atr,
        "trail_stop": px - atr * mult if side == "LONG" else px + atr * mult,
        "last_sl_check": t, "entry_4h_ts": t - pd.Timedelta(hours=4),
        "trading_method": slot.method, "atr_multiplier_override": mult, "_fee_in": 0.0,
    }
    if slot.method == METHOD_4:
        ot["max_stop_capital_pct"] = 0.10
    slot.open_trade = ot
    slot._prepare_risk()


def _first_exit_fast(slot, i0, limit):
    for i in range(i0 + 1, i0 + limit):
        best = pick_best_exit(slot.step_layer1(MD, i))
        if best:
            return best
    return None


def _first_exit_reference(ot, method, i0, limit):
    """Như paper_loop: mỗi tick gọi compute_exit_candidates với df_1m = [nến vừa đóng, nến đang chạy]."""
    for i in range(i0 + 1, i0 + limit):
        t, prev_t = MD.idx[i], MD.idx[i - 1]
        df_1m = pd.DataFrame(
            {"open": [MD.o[i - 1], MD.o[i]], "high": [MD.h[i - 1], MD.o[i]],
             "low": [MD.l[i - 1], MD.o[i]], "close": [MD.c[i - 1], MD.o[i]]},
            index=pd.DatetimeIndex([prev_t, t]),
        )
        cands = compute_exit_candidates(
            ot, df_1m, _df_1h_at(t), pd.DataFrame(), MD.ind4.iloc[-3], MD.ind4.iloc[-2], float(MD.o[i]), t,
            paper_use_4h_window=True, in_4h_window=False, method=method,
            lookback_trades=15, allow_early_exit=False,
        )
        ot["last_sl_check"] = t
        best = pick_best_exit(cands)
        if best:
            return best
    return None


def test_layer1_matches_exit_engine():
    checked = 0
    for method, mult in ((METHOD_1, 1.5), (METHOD_4, 2.5)):
        for side in ("LONG", "SHORT"):
            for i0 in range(60 * 24 * 12, 60 * 24 * 35, 60 * 24 * 3 + 37):
                slot = SlotSim(method, 50.0, 20.0, 0.3, 15)
                _open(slot, i0, side, mult)
                ref_ot = copy.deepcopy(slot.open_trade)
                fast = _first_exit_fast(slot, i0, 3000)
                ref = _first_exit_reference(ref_ot, method, i0, 3000)
                assert (fast is None) == (ref is None), (method, side, i0, fast, ref)
                if fast:
                    assert fast[0] == ref[0] and fast[3] == ref[3], (fast, ref)
                    assert abs(fast[1] - ref[1]) < 1e-9 and abs(fast[2] - ref[2]) < 1e-6
                    checked += 1
    assert checked >= 8


def _same(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, pd.DataFrame):
        return a.index.equals(b.index) and np.allclose(a.to_numpy(float), b.to_numpy(float), equal_nan=True, rtol=0, atol=0)
    sa, sb = pd.Series(a).astype(float), pd.Series(b).astype(float)
    return sa.index.equals(sb.index) and np.array_equal(sa.to_numpy(), sb.to_numpy(), equal_nan=True)


def test_no_lookahead_data_cut_at_t():
    """Cắt bỏ toàn bộ dữ liệu sau thời điểm t: mọi thứ bot thấy tại t phải giữ nguyên → không nhìn trước."""
    bpos = np.flatnonzero(MD.is_boundary)
    for strict in (False, True):
        full = MD_STRICT if strict else MD
        for i in bpos[60::25]:
            cut = MarketData("SYN", DF_1M.iloc[: i + 1], strict=strict)  # chỉ còn dữ liệu đến giá mở phút i
            a, b = full.context_at(i), cut.context_at(i)
            assert (a is None) == (b is None)
            if a is None:
                continue
            for k in ("row_closed", "prev_row_closed", "row_m3", "df_1h", "df_4h_raw"):
                assert _same(a[k], b[k]), (strict, i, k)
            for j in (i, i - 1, i - 59):
                x, y = full.atr_at(j), cut.atr_at(j)
                assert (np.isnan(x) and np.isnan(y)) or x == y


def test_strict_matches_fast_indicators():
    """Chế độ strict (tính lại trên cửa sổ 200 nến như live) gần như trùng tính một lần trên toàn chuỗi."""
    for i in np.flatnonzero(MD.is_boundary)[60::40]:
        a, b = MD.context_at(i), MD_STRICT.context_at(i)
        for k in ("RSI", "EMA_RSI", "WMA_RSI", "ATR"):
            assert abs(float(a["row_closed"][k]) - float(b["row_closed"][k])) < 1e-3


def test_full_run_ledger_consistent():
    start = MD.idx[60 * 24 * 20]
    slots = run_symbol(MD_STRICT, start, ALL_METHODS, 50.0, 20.0, 0.3, 15)
    assert {s.method for s in slots} == set(ALL_METHODS)
    for s in slots:
        bal = 50.0
        for t in s.trades:
            assert t["entry_time"] >= start and t["exit_time"] >= t["entry_time"]
            bal -= t["fee_in"]
            assert abs(t["capital_before"] - bal) < 1e-9
            bal += t["profit"]
        assert abs(bal - s.balance) < 1e-9
    assert sum(len(s.trades) for s in slots) > 0


if __name__ == "__main__":
    test_layer1_matches_exit_engine()
    test_no_lookahead_data_cut_at_t()
    test_strict_matches_fast_indicators()
    test_full_run_ledger_consistent()
    print("OK")
