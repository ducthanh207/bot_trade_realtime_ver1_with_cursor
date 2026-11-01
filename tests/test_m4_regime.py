# -*- coding: utf-8 -*-
"""[2026-11-01] Kiểm tra nhận diện giai đoạn + cắt lỗ sớm PP4 (strategy/regime.py)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from config import settings
from strategy import regime as R
from strategy.risk import check_atr_trailing


@pytest.fixture
def cfg(monkeypatch):
    """Đặt tạm tham số settings trong một test."""
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    return _set


def _df(closes, ema_start, ema_step, atr=100.0):
    n = len(closes)
    idx = pd.date_range("2026-10-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({
        "close": closes,
        "EMA_TREND": [ema_start + ema_step * i for i in range(n)],
        "ATR": [atr] * n,
    }, index=idx)


def test_defaults_all_off():
    assert settings.M4_REGIME_ENABLED is False
    assert settings.M4_RANGE_SKIP_ENTRY is False
    assert settings.M4_COUNTER_TREND_BLOCK is False
    assert settings.M4_INVALIDATION_EXIT is False
    assert settings.M4_TIME_STOP is False
    assert settings.M4_SMOOTH_GRACE is False


def test_efficiency_ratio():
    assert R.efficiency_ratio(pd.Series([1, 2, 3, 4, 5]), 4) == pytest.approx(1.0)
    assert R.efficiency_ratio(pd.Series([1, 2, 1, 2, 1]), 4) == pytest.approx(0.0)
    assert np.isnan(R.efficiency_ratio(pd.Series([1, 2]), 4))


def test_classify_up_down_range():
    up = _df([10000 + 50 * i for i in range(25)], 9000, 20)
    assert R.classify_regime(up, 20)["regime"] == R.REGIME_UP
    down = _df([20000 - 50 * i for i in range(25)], 21000, -20)
    assert R.classify_regime(down, 20)["regime"] == R.REGIME_DOWN
    chop = _df([10000 + (50 if i % 2 else -50) for i in range(25)], 10000, 0)
    assert R.classify_regime(chop, 20)["regime"] == R.REGIME_RANGE
    assert R.classify_regime(up.head(5), 20)["regime"] is None


def test_entry_decision(cfg):
    assert R.m4_regime_entry_decision("LONG", None) == (True, False)
    assert R.m4_regime_entry_decision("LONG", "UP") == (True, False)
    assert R.m4_regime_entry_decision("LONG", "DOWN") == (True, True)
    assert R.m4_regime_entry_decision("SHORT", "RANGE") == (True, True)
    cfg(M4_RANGE_SKIP_ENTRY=True, M4_COUNTER_TREND_BLOCK=True)
    assert R.m4_regime_entry_decision("SHORT", "RANGE") == (False, False)
    assert R.m4_regime_entry_decision("SHORT", "UP") == (False, False)


def _trade(**kw):
    t = pd.Timestamp("2026-10-29 03:00", tz="Asia/Bangkok")
    ot = {"side": "LONG", "entry_time": t, "entry_price": 100.0, "size": 1.0, "atr": 1.0,
          "trail_stop": 97.5, "trading_method": "4", "signal_low": 98.0, "signal_high": 101.0}
    ot.update(kw)
    return ot


def test_trailing_multiplier_default_matches_old(cfg):
    ot = _trade()
    t0 = ot["entry_time"]
    assert R.m4_trailing_multiplier(ot, t0 + pd.Timedelta(hours=1)) == settings.M4_ATR_MULTIPLIER_GRACE
    assert R.m4_trailing_multiplier(ot, t0 + pd.Timedelta(hours=13)) == settings.M4_ATR_MULTIPLIER
    cfg(M4_SMOOTH_GRACE=True)
    mid = R.m4_trailing_multiplier(ot, t0 + pd.Timedelta(hours=6))
    assert mid == pytest.approx((settings.M4_ATR_MULTIPLIER_GRACE + settings.M4_ATR_MULTIPLIER) / 2)
    tight = _trade(m4_tight=True, atr_multiplier_override=1.5)
    assert R.m4_trailing_multiplier(tight, t0 + pd.Timedelta(hours=1)) == 1.5


def test_check_atr_trailing_tight_uses_tight_mult():
    ot = _trade(m4_tight=True, atr_multiplier_override=1.5, trail_stop=98.5)
    bar = pd.Series({"high": 103.0, "low": 102.0}, name=ot["entry_time"] + pd.Timedelta(hours=1))
    check_atr_trailing(ot, bar)
    assert ot["trail_stop"] == pytest.approx(102.0 - 1.5)


def test_invalidation(cfg):
    ot = _trade(m4_tight=True)
    t0 = ot["entry_time"]
    assert not R.m4_invalidation_hit(ot, t0, 97.0)  # tắt mặc định
    cfg(M4_INVALIDATION_EXIT=True)
    assert R.m4_invalidation_hit(ot, t0, 97.0)          # 97 < 98 - 0.3
    assert not R.m4_invalidation_hit(ot, t0, 97.8)      # chưa qua buffer
    assert not R.m4_invalidation_hit(ot, t0 - pd.Timedelta(hours=1), 90.0)  # nến trước lúc vào
    assert not R.m4_invalidation_hit(ot, t0 + pd.Timedelta(hours=12), 90.0)  # quá 12h
    assert not R.m4_invalidation_hit(_trade(), t0, 97.0)  # lệnh không "chặt" + ONLY_TIGHT
    cfg(M4_EARLY_CUT_ONLY_TIGHT=False)
    assert R.m4_invalidation_hit(_trade(), t0, 97.0)
    short = _trade(side="SHORT", m4_tight=True)
    assert R.m4_invalidation_hit(short, t0, 101.5)
    # entry_time dạng chuỗi ISO (sau khi bot khởi động lại) vẫn chạy
    assert R.m4_invalidation_hit(_trade(entry_time=t0.isoformat(), m4_tight=True), t0, 97.0)


def test_time_stop(cfg):
    ot = _trade(m4_tight=True)
    t4 = ot["entry_time"] + pd.Timedelta(hours=3, minutes=59, seconds=55)
    assert not R.m4_time_stop_hit(ot, t4, -1.0)
    cfg(M4_TIME_STOP=True)
    assert R.m4_time_stop_hit(ot, t4, -1.0)
    assert not R.m4_time_stop_hit(ot, t4, +1.0)
    assert not R.m4_time_stop_hit(ot, ot["entry_time"] + pd.Timedelta(hours=2), -1.0)


def test_backtest_runs_with_all_options(cfg):
    from tests.test_live_replay import MD
    from backtest.live_replay import run_symbol
    from strategy.strategies.registry import METHOD_4

    base = run_symbol(MD, MD.idx[0] + pd.Timedelta(days=20), [METHOD_4], 1000.0, 20, 0.3, 15)[0]
    cfg(M4_REGIME_ENABLED=True, M4_INVALIDATION_EXIT=True, M4_TIME_STOP=True, M4_SMOOTH_GRACE=True)
    s = run_symbol(MD, MD.idx[0] + pd.Timedelta(days=20), [METHOD_4], 1000.0, 20, 0.3, 15)[0]
    assert len(base.trades) > 0 and len(s.trades) > 0
    assert s.trades[-1]["capital_after"] == pytest.approx(s.balance)
    reasons = {t["exit_reason"] for t in s.trades}
    print("PP4 gốc:", len(base.trades), "lệnh; bật tất cả:", len(s.trades), "lệnh, lý do:", reasons)


def test_backtest_invalidation_path_fires(cfg):
    """Buffer âm (chỉ để test) buộc (A) kích hoạt → kiểm tra đường xét mỗi giờ trong backtest."""
    from tests.test_live_replay import MD
    from backtest.live_replay import run_symbol

    cfg(M4_INVALIDATION_EXIT=True, M4_EARLY_CUT_ONLY_TIGHT=False, M4_INVALIDATION_BUFFER_ATR=-1.0)
    s = run_symbol(MD, MD.idx[0] + pd.Timedelta(days=20), ["4"], 1000.0, 20, 0.3, 15)[0]
    hits = [t for t in s.trades if t["exit_reason"] == "M4_INVALIDATION"]
    assert hits
    for t in hits:
        assert t["exit_time"].minute == 0  # thoát ở đầu giờ, ngay khi nến 1H đóng


def test_slot_engine_step_with_regime(cfg):
    """Chạy step_slot (paper/live) ở các mốc 4H trên dữ liệu giả lập với mọi tùy chọn bật: không lỗi, lệnh có thông tin giai đoạn."""
    from tests.test_live_replay import DF_1M, MD
    from bot.slot_engine import MarketContext, step_slot
    from strategy.indicators import add_indicators

    cfg(M4_REGIME_ENABLED=True, M4_INVALIDATION_EXIT=True, M4_TIME_STOP=True,
        M4_SMOOTH_GRACE=True, M4_EARLY_CUT_ONLY_TIGHT=False)
    st = {"open": None, "balance": 1000.0, "trades": []}
    api = {
        "get_status": lambda: "running", "lookback": lambda: 15,
        "get_balance": lambda: st["balance"], "set_balance": lambda v: st.__setitem__("balance", v),
        "get_open": lambda: st["open"], "set_open": lambda v: st.__setitem__("open", v),
        "set_last": lambda v: None, "append_trade": lambda v: st["trades"].append(v),
        "get_lev": lambda: 20.0, "get_wct": lambda: 0.3, "cb": None,
    }
    opened = []
    bounds = [i for i in range(len(MD.idx)) if MD.is_boundary[i]][150:260]
    for i in bounds:
        t = MD.idx[i]
        df_1m = DF_1M.iloc[max(0, i - 480): i + 1]
        df_4h_raw = MD.df4_raw.loc[:t].tail(200)
        df_1h = add_indicators(MD.df1h_raw.loc[:t].tail(200))
        r = step_slot(1, "4", api, MarketContext(df_4h_raw, df_1m, df_1h, True))
        if r == "opened":
            opened.append(dict(st["open"]))
    assert opened
    assert all("regime" in o and "signal_low" in o for o in opened)
    assert any(o["regime"] in ("UP", "DOWN", "RANGE") for o in opened)
