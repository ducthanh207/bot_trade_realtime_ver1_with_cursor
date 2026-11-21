# -*- coding: utf-8 -*-
"""[2026-11-07] Kiểm tra PP5: chu kỳ nến ngày (strategy/daily_cycle.py) + chạy trong backtest live_replay."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from config import settings
from strategy import daily_cycle as C
from strategy.risk import check_atr_trailing
from strategy.strategies.registry import METHOD_4, METHOD_5, get_trading_method


@pytest.fixture
def cfg(monkeypatch):
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    return _set


def _cycles(closes, ema=100.0, x=3.0, h=0.0):
    n = len(closes)
    t = pd.date_range("2026-01-01", periods=n, freq="1D", tz="UTC")
    tab = C.classify_cycles(t, closes, [ema] * n, [x] * n, [h] * n)
    return list(tab["cycle"])


def test_defaults():
    assert settings.M5_DAILY_EMA_LEN == 20
    assert settings.M5_SIDEWAYS_MODE == "atr" and settings.M5_SIDEWAYS_ATR_K == 1.0
    assert settings.M5_SIDEWAYS_MIXED == "latest"
    # PP5 không lọt vào bot live qua TRADING_METHOD
    assert get_trading_method() != METHOD_5


def test_trend_needs_two_closes_and_ends_with_two():
    # Giá cách EMA xa (> X) để không bị xếp đi ngang
    c = _cycles([90, 110, 110, 95, 110, 95, 94, 110])
    assert c[0] == C.CYCLE_NEUTRAL          # 1 nến dưới EMA: chưa đủ
    assert c[1] == C.CYCLE_NEUTRAL          # 1 nến trên: chưa đủ
    assert c[2] == C.CYCLE_UP               # 2 nến đóng trên EMA → TĂNG
    assert c[3] == C.CYCLE_UP               # 1 nến lẻ dưới EMA: vẫn TĂNG
    assert c[4] == C.CYCLE_UP
    assert c[5] == C.CYCLE_UP
    assert c[6] == C.CYCLE_DOWN             # 2 nến liên tiếp dưới EMA → hết TĂNG, sang GIẢM
    assert c[7] == C.CYCLE_DOWN


def test_spike_enters_immediately():
    # h = 5%: nến đóng +10% → đường lower %change (close×0.95 = 104.5) nằm trên EMA → TĂNG ngay
    c = _cycles([90, 90, 110], h=5.0)
    assert c[1] == C.CYCLE_DOWN and c[2] == C.CYCLE_UP
    # +4% < h: không phải đột biến
    assert _cycles([90, 90, 104], h=5.0)[2] == C.CYCLE_DOWN


def test_sideways_long_short_and_end():
    # Ví dụ của anh: +2%, +2.3%, +3% so với EMA, X = 3% → đi ngang thiên LONG
    c = _cycles([110, 110, 102, 102.3, 103, 110])
    assert c[3] == C.CYCLE_UP               # mới 2 nến sát EMA
    assert c[4] == C.CYCLE_SIDE_LONG        # đủ 3 nến |d| <= X, đều trên EMA
    assert c[5] == C.CYCLE_UP               # đột biến (|d| > X) → hết đi ngang, về xu hướng
    c = _cycles([90, 90, 98, 97.5, 98.5])
    assert c[4] == C.CYCLE_SIDE_SHORT


def test_sideways_mixed_modes(cfg):
    closes = [110, 110, 101, 99, 101]       # lẫn hai phía EMA, nến cuối trên
    assert _cycles(closes)[4] == C.CYCLE_SIDE_LONG          # latest
    assert _cycles(closes[:4])[3] == C.CYCLE_UP              # chưa đủ 3 nến sát EMA
    assert _cycles([110, 110, 101, 101, 99])[4] == C.CYCLE_SIDE_SHORT
    cfg(M5_SIDEWAYS_MIXED="both")
    assert _cycles(closes)[4] == C.CYCLE_SIDE_MIXED
    assert C.m5_entry_decision("SHORT", C.CYCLE_SIDE_MIXED) == (True, True)
    cfg(M5_SIDEWAYS_MIXED="skip")
    assert C.m5_entry_decision("LONG", C.CYCLE_SIDE_MIXED) == (False, False)


def test_entry_decision_table():
    D = C.m5_entry_decision
    assert D("LONG", None) == (False, False)
    assert D("LONG", C.CYCLE_NEUTRAL) == (True, False) and D("SHORT", C.CYCLE_NEUTRAL) == (True, False)
    assert D("LONG", C.CYCLE_UP) == (True, False) and D("SHORT", C.CYCLE_UP)[0] is False
    assert D("SHORT", C.CYCLE_DOWN) == (True, False) and D("LONG", C.CYCLE_DOWN)[0] is False
    assert D("LONG", C.CYCLE_SIDE_LONG) == (True, True) and D("SHORT", C.CYCLE_SIDE_LONG)[0] is False
    assert D("SHORT", C.CYCLE_SIDE_SHORT) == (True, True) and D("LONG", C.CYCLE_SIDE_SHORT)[0] is False


def test_wide_trade_trailing_and_payload():
    t0 = pd.Timestamp("2026-11-01 07:00", tz="Asia/Bangkok")
    p = {"side": "LONG", "entry_price": 100.0, "atr": 1.0, "trading_method": METHOD_5, "entry_time": t0,
         "size": 1.0, "trail_stop": 97.5, "atr_multiplier_override": 2.5}
    C.m5_apply_cycle_to_payload(p, "LONG", {"cycle": C.CYCLE_SIDE_LONG, "d": 1.0, "x": 3.0, "h": 8.0}, True)
    assert p["m5_wide"] and p["trail_stop"] == pytest.approx(96.5)
    # nới cố định 3.5 kể cả sau 12h
    late = pd.Series({"high": 100.0, "low": 99.0}, name=t0 + pd.Timedelta(hours=20))
    check_atr_trailing(p, late)
    assert p["trail_stop"] == pytest.approx(96.5)
    # lệnh PP5 không đi ngang: y hệt PP4 gốc (2.5 trong 12h rồi 2.2)
    q = {"m5_wide": False, "entry_time": t0}
    assert C.m5_trailing_multiplier(q, t0 + pd.Timedelta(hours=1)) == settings.M4_ATR_MULTIPLIER_GRACE
    assert C.m5_trailing_multiplier(q, t0 + pd.Timedelta(hours=13)) == settings.M4_ATR_MULTIPLIER


# ---------------- Backtest ----------------
from backtest.binance_data import resample_ohlcv  # noqa: E402
from backtest.live_replay import MarketData, run_symbol  # noqa: E402
from tests.test_live_replay import DF_1M  # noqa: E402

DF_1D = resample_ohlcv(DF_1M, "24h")


def test_daily_at_uses_only_closed_days():
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D)
    t = DF_1M.index[60 * 24 * 30 + 5]
    info = md.daily_at(t)
    assert info.get("day") is not None and info["day"] + pd.Timedelta(days=1) <= t
    # cắt bỏ mọi dữ liệu sau t → cùng kết quả
    cut = MarketData("SYN", DF_1M.loc[:t], strict=False, df_1d=resample_ohlcv(DF_1M.loc[:t], "24h"))
    assert cut.daily_at(t) == info


def test_pp5_runs_and_does_not_change_pp4():
    start = DF_1M.index[60 * 24 * 25]
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D)
    only4 = run_symbol(md, start, [METHOD_4], 50.0, 20.0, 0.3, 15)[0]
    s4, s5 = run_symbol(MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D), start, [METHOD_4, METHOD_5], 50.0, 20.0, 0.3, 15)
    key = lambda tr: [(x["entry_time"], x["exit_time"], x["side"], round(x["profit"], 9)) for x in tr]
    assert key(only4.trades) == key(s4.trades)
    for tr in s5.trades:
        assert tr["method"] == METHOD_5
        if tr["exit_reason"] != "END_OF_DATA":
            assert tr["cycle"] is not None
            allow, wide = C.m5_entry_decision(tr["side"], tr["cycle"])
            assert allow and wide == tr["cycle_wide"]


def test_pp5_wide_path_strict(cfg):
    """Ép mọi ngày là đi ngang → mọi lệnh PP5 dùng gói thoát nới (size nhỏ, trailing 3.5, TP %change, Exit B sửa)."""
    cfg(M5_SIDEWAYS_MODE="pct", M5_SIDEWAYS_PCT=100.0, M5_EXIT_B="all")
    start = DF_1M.index[60 * 24 * 25]
    md = MarketData("SYN", DF_1M, strict=True, df_1d=DF_1D)
    s4, s5 = run_symbol(md, start, [METHOD_4, METHOD_5], 50.0, 20.0, 0.3, 15)
    real = [t for t in s5.trades if t["exit_reason"] != "END_OF_DATA"]
    assert real, "cần ít nhất 1 lệnh PP5 để kiểm tra"
    for tr in real:
        assert tr["cycle"] in C.SIDEWAYS and tr["cycle_wide"] is True


def test_m5_entry_plan_counter_trend(monkeypatch):
    """[2026-11-08] Lệnh ngược chu kỳ: mặc định chặn; hệ số > 0 thì cho vào với size nhỏ."""
    from config import settings
    from strategy.daily_cycle import (CYCLE_DOWN, CYCLE_NEUTRAL, CYCLE_SIDE_LONG, CYCLE_SIDE_SHORT, CYCLE_UP,
                                      m5_entry_plan)

    monkeypatch.setattr(settings, "M5_COUNTER_LONG_SIZE", 0.0)
    monkeypatch.setattr(settings, "M5_COUNTER_SHORT_SIZE", 0.0)
    assert m5_entry_plan("LONG", CYCLE_DOWN) == (False, False, 1.0, False)
    assert m5_entry_plan("LONG", CYCLE_UP) == (True, False, 1.0, False)
    assert m5_entry_plan("SHORT", CYCLE_SIDE_SHORT) == (True, True, 1.0, False)
    assert m5_entry_plan("SHORT", CYCLE_NEUTRAL) == (True, False, 1.0, False)
    assert m5_entry_plan("LONG", None) == (False, False, 1.0, False)

    monkeypatch.setattr(settings, "M5_COUNTER_LONG_SIZE", 0.5)
    assert m5_entry_plan("LONG", CYCLE_DOWN) == (True, False, 0.5, True)
    assert m5_entry_plan("LONG", CYCLE_SIDE_SHORT) == (True, True, 0.5, True)
    assert m5_entry_plan("SHORT", CYCLE_UP) == (False, False, 1.0, False)  # SHORT vẫn chặn
    monkeypatch.setattr(settings, "M5_COUNTER_SHORT_SIZE", 1.0)
    assert m5_entry_plan("SHORT", CYCLE_SIDE_LONG) == (True, True, 1.0, True)
