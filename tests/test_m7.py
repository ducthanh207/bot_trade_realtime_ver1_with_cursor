# -*- coding: utf-8 -*-
"""[2026-11-20] Kiểm tra PP7 = PP4 + size theo rủi ro + lọc trend EMA50 luôn bật + stop/trailing theo ATR 4H."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import pytest

from config import settings
from strategy import pp7 as P
from strategy.risk import check_atr_trailing
from strategy.strategies.registry import METHOD_4, METHOD_7, get_trading_method, get_method_label


@pytest.fixture
def cfg(monkeypatch):
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    return _set


def test_defaults_and_not_live():
    assert settings.M7_RISK_PCT == 0.02 and settings.M7_ATR4H_MULT == 1.5
    assert settings.M7_TREND_FILTER is True and settings.M7_TREND_SLOPE_BARS == 0
    assert settings.M7_EXIT_B == "off"
    assert get_trading_method() != METHOD_7  # bot live không chạy PP7
    assert "Phương pháp 7" in get_method_label(METHOD_7)


def test_trend_filter(cfg):
    assert P.m7_trend_allows("LONG", 105, 100) and not P.m7_trend_allows("LONG", 95, 100)
    assert P.m7_trend_allows("SHORT", 95, 100) and not P.m7_trend_allows("SHORT", 105, 100)
    assert P.m7_trend_allows("LONG", 105, None)  # thiếu EMA → không chặn
    cfg(M7_TREND_SLOPE_BARS=3)
    assert P.m7_trend_allows("LONG", 105, 100, ema_ref=99) and not P.m7_trend_allows("LONG", 105, 100, ema_ref=101)
    assert P.m7_trend_allows("SHORT", 95, 100, ema_ref=101) and not P.m7_trend_allows("SHORT", 95, 100, ema_ref=99)
    cfg(M7_TREND_FILTER=False)
    assert P.m7_trend_allows("LONG", 95, 100)


def test_risk_sizing():
    # vốn 1000, rủi ro 2% = 20 USDT, stop cách 2 USDT → size 10; notional 1000 < trần 1000×0.3×20 = 6000
    size, margin, notional = P.m7_size_and_margin(1000, 100, 2.0, 1.0, 20, 0.3)
    assert size == pytest.approx(10) and notional == pytest.approx(1000) and margin == pytest.approx(50)
    # size_mult 0.5 → rủi ro 10 USDT
    size, _, _ = P.m7_size_and_margin(1000, 100, 2.0, 0.5, 20, 0.3)
    assert size == pytest.approx(5)
    # stop rất hẹp → bị chặn ở trần notional PP4 (rủi ro thực < 2%)
    size, margin, notional = P.m7_size_and_margin(1000, 100, 0.1, 1.0, 20, 0.3)
    assert notional == pytest.approx(6000) and margin == pytest.approx(300) and size * 0.1 < 20
    assert P.m7_size_and_margin(1000, 100, 0, 1.0, 20, 0.3) == (0.0, 0.0, 0.0)
    assert P.m7_stop_distance(4.0) == pytest.approx(6.0) and P.m7_stop_distance(float("nan")) is None


def test_trailing_uses_fixed_4h_multiplier():
    t0 = pd.Timestamp("2026-01-01 00:00", tz="UTC")
    ot = {"side": "LONG", "entry_price": 100.0, "size": 1.0, "atr": 2.0, "trail_stop": 97.0,
          "trading_method": METHOD_7, "entry_time": t0}
    # 20h sau vẫn 1.5 × ATR (không siết như PP4)
    check_atr_trailing(ot, pd.Series({"high": 104.0, "low": 103.0}, name=t0 + pd.Timedelta(hours=20)))
    assert ot["trail_stop"] == pytest.approx(103.0 - 3.0)


# ---------------- Backtest ----------------
from backtest.live_replay import MarketData, run_symbol  # noqa: E402
from tests.test_live_replay import DF_1M  # noqa: E402

START = DF_1M.index[60 * 24 * 25]


def _key(tr):
    return [(x["entry_time"], x["exit_time"], x["side"], round(x["profit"], 9)) for x in tr]


def test_pp7_runs_and_does_not_change_pp4():
    only4 = run_symbol(MarketData("SYN", DF_1M, strict=False), START, [METHOD_4], 1000.0, 20.0, 0.3, 15)[0]
    s4, s7 = run_symbol(MarketData("SYN", DF_1M, strict=False), START, [METHOD_4, METHOD_7], 1000.0, 20.0, 0.3, 15)
    assert _key(only4.trades) == _key(s4.trades)
    assert all(t["method"] == METHOD_7 for t in s7.trades)


def test_pp7_losses_capped_by_risk(cfg):
    """Tắt lọc trend để có nhiều lệnh: mỗi lệnh thua (trước phí) không mất quá M7_RISK_PCT vốn."""
    cfg(M7_TREND_FILTER=False)
    s7 = run_symbol(MarketData("SYN", DF_1M, strict=True), START, [METHOD_7], 1000.0, 20.0, 0.3, 15)[0]
    real = [t for t in s7.trades if t["exit_reason"] != "END_OF_DATA"]
    assert real, "cần ít nhất 1 lệnh PP7"
    bal = 1000.0
    for t in s7.trades:
        assert t["capital_before"] == pytest.approx(bal - t["fee_in"])
        bal = t["capital_after"]
        fee_out = t["size"] * t["exit_price"] * settings.TAKER_FEE
        gross = t["profit"] + fee_out
        assert gross >= -settings.M7_RISK_PCT * (t["capital_before"] + t["fee_in"]) - 1e-6
        assert t["exit_reason"] in ("ATR_TRAIL", "4H_EXIT", "HARD_STOP")
    assert s7.balance == pytest.approx(bal)


def test_pp7_trend_filter_blocks_counter_trend(cfg):
    """Với lọc trend: mọi lệnh PP7 cùng phía với EMA50 4H của nến tín hiệu."""
    md = MarketData("SYN", DF_1M, strict=False)
    s7 = run_symbol(md, START, [METHOD_7], 1000.0, 20.0, 0.3, 15)[0]
    for t in s7.trades:
        sig = pd.Timestamp(t["entry_time"]) - pd.Timedelta(hours=4)
        row = md.ind4_m3.loc[sig]
        assert P.m7_trend_allows(t["side"], row["close"], row["EMA_TREND"])


def test_web_page_and_route():
    from web import app as A

    c = A.app.test_client()
    r = c.get("/backtest7")
    assert r.status_code == 200 and "/api/pp7" in r.get_data(as_text=True)
    assert c.post("/api/pp7/backtest", json={"start_date": "bad"}).status_code == 400
