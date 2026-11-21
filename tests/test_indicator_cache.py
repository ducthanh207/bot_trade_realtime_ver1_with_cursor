# -*- coding: utf-8 -*-
"""[2026-11-08] Bộ nhớ chỉ báo trên đĩa (backtest/indicator_cache.py) không được làm đổi kết quả backtest strict."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from backtest import indicator_cache
from backtest.indicator_cache import IndicatorCache
from backtest.live_replay import MarketData, run_symbol
from tests.test_live_replay import _synthetic_1m

DF = _synthetic_1m(days=45, seed=11)
METHODS = ["1", "2", "3", "4"]


def _run(df, start, cache=None):
    md = MarketData("SYN", df, strict=True, ind_cache=cache)
    slots = run_symbol(md, start, METHODS, 1000.0, 20.0, 0.3, 15)
    if cache is not None:
        cache.save()
    return [[(t["entry_time"], t["exit_time"], t["side"], round(t["profit"], 9), t["exit_reason"]) for t in s.trades]
            for s in slots]


def test_cache_gives_same_trades(tmp_path, monkeypatch):
    monkeypatch.setattr(indicator_cache, "CACHE_DIR", tmp_path)
    start = DF.index[60 * 24 * 30]
    ref = _run(DF, start)
    assert sum(len(x) for x in ref) > 0

    cold = IndicatorCache("SYN")
    assert _run(DF, start, cold) == ref
    assert cold.path.exists()

    warm = IndicatorCache("SYN")
    assert warm.h4 and warm.h1
    assert _run(DF, start, warm) == ref
    assert warm.hits > 0 and warm.dirty == 0  # mọi giá trị đều đọc từ đĩa

    # chạy 1 đoạn con (ít lịch sử hơn, kết thúc sớm hơn) sau khi đã chạy cả khoảng dài
    sub = DF.loc[DF.index[60 * 24 * 5]: DF.index[60 * 24 * 40]]
    sub_start = DF.index[60 * 24 * 34]
    ref_sub = _run(sub, sub_start)
    c = IndicatorCache("SYN")
    assert _run(sub, sub_start, c) == ref_sub
    assert c.hits > 0


def test_cache_disabled_or_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr(indicator_cache, "CACHE_DIR", tmp_path)
    off = IndicatorCache("SYN", enabled=False)
    off.put4(pd.Timestamp("2025-01-01", tz="UTC"), (1, 2, None))
    assert off.get4(pd.Timestamp("2025-01-01", tz="UTC")) is None
    off.save()
    assert not off.path.exists()

    bad = IndicatorCache("SYN")
    bad.path.parent.mkdir(parents=True, exist_ok=True)
    bad.path.write_bytes(b"not a pickle")
    again = IndicatorCache("SYN")  # file hỏng → coi như rỗng, không lỗi
    assert again.h4 == {} and again.h1 == {}
