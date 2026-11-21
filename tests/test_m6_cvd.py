# -*- coding: utf-8 -*-
"""[2026-11-14] Kiểm tra PP6 (PP4 + CVD) và PP6.1 (PP5 + CVD): strategy/cvd.py + chạy trong backtest live_replay."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest

from config import settings
from strategy import cvd as V
from strategy.daily_cycle import CYCLE_DOWN, CYCLE_SIDE_LONG, CYCLE_SIDE_SHORT, CYCLE_UP
from strategy.risk import check_atr_trailing
from strategy.strategies.registry import METHOD_4, METHOD_5, METHOD_6, METHOD_61, get_trading_method


@pytest.fixture
def cfg(monkeypatch):
    def _set(**kw):
        for k, v in kw.items():
            monkeypatch.setattr(settings, k, v)
    return _set


def _taker(vol, buy, start="2026-01-01", freq="1h"):
    idx = pd.date_range(start, periods=len(vol), freq=freq, tz="UTC").tz_convert("Asia/Bangkok")
    return pd.DataFrame({"volume": vol, "taker_buy": buy}, index=idx)


def test_defaults_and_not_live():
    assert settings.M6_4H_BARS == 6 and settings.M6_1H_BARS == 8
    assert settings.M6_EXIT_MODE == "tighten" and settings.M61_SIDEWAYS_BIAS == "cvd"
    assert get_trading_method() not in (METHOD_6, METHOD_61)


def test_ratio_and_resample():
    df = _taker([10, 10, 10, 10, 20, 20, 20, 20], [6, 6, 6, 6, 5, 5, 5, 5])
    # delta = 2*buy - vol: +2 x4, -10 x4
    r2 = V.ratio_series(df, 2)
    assert np.isnan(r2.iloc[0]) and r2.iloc[1] == pytest.approx(0.2) and r2.iloc[-1] == pytest.approx(-0.5)
    assert V.last_ratio(df, 8) == pytest.approx((8 - 40) / 120)
    assert V.last_ratio(df.drop(columns=["taker_buy"]), 2) is None
    d4 = V.resample_4h(df)
    assert list(d4["volume"]) == [40, 80] and list(d4["taker_buy"]) == [24, 20]
    # nến 4H thiếu giờ bị bỏ
    assert len(V.resample_4h(df.iloc[:7])) == 1


def test_entry_ok(cfg):
    assert V.cvd_entry_ok("LONG", 0.01) and not V.cvd_entry_ok("LONG", -0.01)
    assert V.cvd_entry_ok("SHORT", -0.01) and not V.cvd_entry_ok("SHORT", 0.0)
    assert not V.cvd_entry_ok("LONG", None)
    cfg(M6_4H_MIN_RATIO=0.02)
    assert not V.cvd_entry_ok("LONG", 0.01) and V.cvd_entry_ok("LONG", 0.03)
    cfg(M6_4H_MIN_RATIO=0.0, M6_1H_ENTRY_CONFIRM=True)
    assert not V.cvd_entry_ok("LONG", 0.05, -0.01) and V.cvd_entry_ok("LONG", 0.05, 0.01)


def test_m61_sideways_bias(cfg):
    P = V.m61_entry_plan
    # cvd: đi ngang thiên LONG nhưng CVD âm → chỉ SHORT, vẫn là lệnh "nới"
    assert P("SHORT", CYCLE_SIDE_LONG, -0.03) == (True, True, 1.0, False)
    assert P("LONG", CYCLE_SIDE_LONG, -0.03)[0] is False
    assert P("LONG", CYCLE_SIDE_SHORT, None)[0] is False
    # chu kỳ xu hướng: y hệt PP5
    assert P("LONG", CYCLE_UP, -0.5) == (True, False, 1.0, False)
    assert P("SHORT", CYCLE_UP, -0.5)[0] is False
    cfg(M61_SIDEWAYS_BIAS="both")
    assert P("LONG", CYCLE_SIDE_LONG, 0.02) == (True, True, 1.0, False)
    assert P("LONG", CYCLE_SIDE_LONG, -0.02)[0] is False
    assert P("SHORT", CYCLE_SIDE_LONG, -0.02)[0] is False
    cfg(M61_SIDEWAYS_BIAS="close")
    assert P("LONG", CYCLE_SIDE_LONG, -0.02) == (True, True, 1.0, False)
    assert P("SHORT", CYCLE_DOWN, 0.9)[0] is True


def _trade(side="LONG", method=METHOD_6):
    t0 = pd.Timestamp("2026-11-01 07:00", tz="Asia/Bangkok")
    ot = {"side": side, "entry_price": 100.0, "atr": 1.0, "trading_method": method, "entry_time": t0,
          "size": 1.0, "trail_stop": 97.5, "atr_multiplier_override": 2.5}
    V.apply_cvd_to_payload(ot, 0.02, 0.01, 0.03)
    return ot, t0


def test_exit_step_tighten_and_close(cfg):
    H = pd.Timedelta(hours=1)
    ot, t0 = _trade()
    assert not V.cvd_exit_step(ot, t0, -0.05) and ot["cvd_against_n"] == 1 and not ot["cvd_tight"]
    assert not V.cvd_exit_step(ot, t0, -0.05) and ot["cvd_against_n"] == 1  # cùng nến: không đếm lại
    assert not V.cvd_exit_step(ot, t0 + H, -0.05)                            # 2 nến ngược, giữ 2h → siết
    assert ot["cvd_tight"] and ot["cvd_tight_at"] == t0 + 2 * H
    # nến trước lúc vào lệnh không tính
    ot2, _ = _trade()
    V.cvd_exit_step(ot2, t0 - H, -0.05)
    assert ot2["cvd_against_n"] == 0
    # một nến cùng chiều → đếm lại từ đầu
    ot3, _ = _trade(side="SHORT")
    V.cvd_exit_step(ot3, t0, 0.05)
    V.cvd_exit_step(ot3, t0 + H, -0.01)
    V.cvd_exit_step(ot3, t0 + 2 * H, 0.05)
    assert ot3["cvd_against_n"] == 1 and not ot3["cvd_tight"]
    cfg(M6_EXIT_MODE="close")
    ot4, _ = _trade()
    assert not V.cvd_exit_step(ot4, t0, -0.05)
    assert V.cvd_exit_step(ot4, t0 + H, -0.05)
    cfg(M6_EXIT_MODE="off")
    ot5, _ = _trade()
    assert not V.cvd_exit_step(ot5, t0, -0.05) and ot5["cvd_against_n"] == 0


def test_trailing_tightened():
    ot, t0 = _trade()
    bar = pd.Series({"high": 101.0, "low": 100.0}, name=t0 + pd.Timedelta(hours=1))
    check_atr_trailing(ot, bar)
    assert ot["trail_stop"] == pytest.approx(100.0 - 2.5)  # PP4 gốc trong 12h đầu
    ot["cvd_tight"] = True
    check_atr_trailing(ot, bar)
    assert ot["trail_stop"] == pytest.approx(100.0 - settings.M6_TIGHT_ATR_MULT)
    # PP6.1 lệnh đi ngang (nới 3.5) cũng bị siết
    w, _ = _trade(method=METHOD_61)
    w["m5_wide"] = True
    w["trail_stop"] = 96.5
    check_atr_trailing(w, bar)
    assert w["trail_stop"] == pytest.approx(96.5)
    w["cvd_tight"] = True
    check_atr_trailing(w, bar)
    assert w["trail_stop"] == pytest.approx(100.0 - settings.M6_TIGHT_ATR_MULT)


# ---------------- Backtest ----------------
from backtest.binance_data import resample_ohlcv  # noqa: E402
from backtest.live_replay import MarketData, run_symbol  # noqa: E402
from tests.test_live_replay import DF_1M  # noqa: E402

DF_1D = resample_ohlcv(DF_1M, "24h")


def _synthetic_taker(df_1m):
    """Taker buy nghiêng theo chiều nến 1H (giống thực tế: nến tăng thường do bên mua chủ động) + nhiễu."""
    h = resample_ohlcv(df_1m, "1h")
    rng = np.random.default_rng(3)
    move = np.sign(h["close"] - h["open"]).to_numpy()
    share = np.clip(0.5 + 0.08 * move + rng.normal(0, 0.05, len(h)), 0.05, 0.95)
    vol = h["volume"].to_numpy(float) * 10
    return pd.DataFrame({"volume": vol, "taker_buy": vol * share}, index=h.index)


DF_TAKER = _synthetic_taker(DF_1M)
START = DF_1M.index[60 * 24 * 25]


def _key(tr):
    return [(x["entry_time"], x["exit_time"], x["side"], round(x["profit"], 9)) for x in tr]


def test_cvd_at_uses_only_closed_bars():
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D, df_taker=DF_TAKER)
    t = DF_1M.index[60 * 24 * 30]  # đầu một nến 4H
    full = md.cvd_at(t)
    assert full["r4"] is not None and full["r1"] is not None
    cut = MarketData("SYN", DF_1M.loc[:t], strict=False, df_taker=DF_TAKER.loc[: t - pd.Timedelta(hours=1)])
    assert cut.cvd_at(t) == full


def test_pp6_runs_without_changing_pp4_and_pp5():
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D, df_taker=DF_TAKER)
    s4, s5, s6, s61 = run_symbol(md, START, [METHOD_4, METHOD_5, METHOD_6, METHOD_61], 50.0, 20.0, 0.3, 15)
    only = run_symbol(MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D), START, [METHOD_4, METHOD_5], 50.0, 20.0, 0.3, 15)
    assert _key(only[0].trades) == _key(s4.trades) and _key(only[1].trades) == _key(s5.trades)
    assert s6.trades, "cần ít nhất 1 lệnh PP6"
    for tr in s6.trades:
        assert tr["method"] == METHOD_6
        assert V.cvd_entry_ok(tr["side"], tr["cvd4_ratio"])
    for tr in s61.trades:
        assert tr["cycle"] is not None and V.cvd_entry_ok(tr["side"], tr["cvd4_ratio"])
    assert any(tr["cvd_tight"] for tr in s6.trades), "dữ liệu giả lập phải có lệnh bị siết theo CVD 1H"


def test_pp6_without_taker_data_never_trades():
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D)
    s6, s61 = run_symbol(md, START, [METHOD_6, METHOD_61], 50.0, 20.0, 0.3, 15)
    assert not s6.trades and not s61.trades


def test_pp6_filter_only_matches_pp4_entries(cfg):
    """Ngưỡng −1 (luôn đạt) + tắt thoát CVD → PP6 phải trùng hệt PP4 (kiểm tra luồng PP6 không lệch PP4)."""
    cfg(M6_4H_MIN_RATIO=-1.0, M6_EXIT_MODE="off")
    md = MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D, df_taker=DF_TAKER)
    s4, s6 = run_symbol(md, START, [METHOD_4, METHOD_6], 50.0, 20.0, 0.3, 15)
    assert _key(s4.trades) == _key(s6.trades)
    cfg(M61_SIDEWAYS_BIAS="close")
    s5b, s61b = run_symbol(MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D, df_taker=DF_TAKER), START,
                           [METHOD_5, METHOD_61], 50.0, 20.0, 0.3, 15)
    assert _key(s5b.trades) == _key(s61b.trades)


def test_pp6_strict_equals_fast():
    a = run_symbol(MarketData("SYN", DF_1M, strict=False, df_taker=DF_TAKER), START, [METHOD_6], 50.0, 20.0, 0.3, 15)[0]
    b = run_symbol(MarketData("SYN", DF_1M, strict=True, df_taker=DF_TAKER), START, [METHOD_6], 50.0, 20.0, 0.3, 15)[0]
    # ATR strict (cửa sổ 200 nến) lệch fast ở số lẻ thứ 9 → so lệnh và lời/lỗ làm tròn
    k = lambda tr: [(x["entry_time"], x["exit_time"], x["side"], x["exit_reason"], round(x["profit"], 4)) for x in tr]
    assert a.trades and k(a.trades) == k(b.trades)


def test_slot_engine_cvd_info_from_frames():
    """Bot (slot_engine) tính cùng độ dốc với backtest khi nến 4H/1H có cột taker_buy."""
    from bot.slot_engine import MarketContext

    t = DF_1M.index[60 * 24 * 30]
    h = resample_ohlcv(DF_1M.loc[: t - pd.Timedelta(minutes=1)], "1h").join(DF_TAKER[["taker_buy"]])
    h = h.drop(columns=["volume"]).join(DF_TAKER[["volume"]])
    h1 = pd.concat([h.tail(199), h.tail(1).set_axis([t])])  # + nến đang chạy
    raw4 = resample_ohlcv(DF_1M.loc[: t - pd.Timedelta(minutes=1)], "4h")
    mkt = MarketContext(raw4.assign(volume=1.0), DF_1M.loc[:t].tail(5), h1, True)
    got = mkt.cvd_info()
    exp = MarketData("SYN", DF_1M, strict=False, df_taker=DF_TAKER).cvd_at(t)
    assert got["r1"] == pytest.approx(exp["r1"]) and got["r4"] == pytest.approx(exp["r4"])
    assert got["r_side"] == pytest.approx(exp["r_side"])


def test_exit_engine_cvd_exit_live_path(cfg):
    """Bot: compute_exit_candidates xét CVD 1H trên nến 1H vừa đóng (df_1h có taker_buy), M6_EXIT_MODE=close → CVD_EXIT."""
    from strategy.exit_engine import compute_exit_candidates

    cfg(M6_EXIT_MODE="close", M6_EXIT_CONFIRM_BARS=1, M6_EXIT_MIN_HOURS=0)
    ot, t0 = _trade()
    ot.update(margin=5.0, notional=100.0, capital_before=50.0, max_stop_capital_pct=0.1, last_sl_check=None)
    idx = pd.date_range(t0 - pd.Timedelta(hours=10), periods=13, freq="1h")
    df_1h = pd.DataFrame({"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "RSI": 50.0, "ATR": 1.0,
                          "volume": 10.0, "taker_buy": 2.0}, index=idx)  # bên bán áp đảo, nến cuối = đang chạy
    row = pd.Series({"RSI": 50.0, "EMA_RSI": 50.0, "WMA_RSI": 50.0, "close": 100.0})
    c = compute_exit_candidates(ot, pd.DataFrame(), df_1h, None, row, row, 100.0, idx[-1],
                                paper_use_4h_window=True, in_4h_window=False, method=METHOD_6,
                                lookback_trades=15, allow_early_exit=True)
    assert [x[3] for x in c] == ["CVD_EXIT"]
    # cùng nến 1H: không báo lại
    c2 = compute_exit_candidates(ot, pd.DataFrame(), df_1h, None, row, row, 100.0, idx[-1],
                                 paper_use_4h_window=True, in_4h_window=False, method=METHOD_6,
                                 lookback_trades=15, allow_early_exit=True)
    assert c2 == []


def test_download_1h_taker_parses_and_fills_gaps(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from backtest import binance_data as B

    monkeypatch.setattr(B, "CACHE_DIR", tmp_path)
    calls = []

    def fake(url, params, log=print, **kw):
        calls.append(params["startTime"])
        s, e = params["startTime"], params["endTime"]
        rows = []
        t = s
        while t <= e and len(rows) < 1500:
            rows.append([t, "1", "1", "1", "1", "10.0", t + 3599999, "0", 1, "6.0", "0", "0"])
            t += B.HOUR_MS
        return rows

    monkeypatch.setattr(B, "_get_json", fake)
    s = datetime(2026, 1, 1, tzinfo=timezone.utc)
    df = B.download_1h_taker("TESTUSDT", s, datetime(2026, 1, 3, tzinfo=timezone.utc), log=lambda *a: None)
    assert len(df) == 48 and set(df["taker_buy"]) == {6.0} and set(df["volume"]) == {10.0}
    n = len(calls)
    B.download_1h_taker("TESTUSDT", s, datetime(2026, 1, 3, tzinfo=timezone.utc), log=lambda *a: None)
    assert len(calls) == n  # đủ cache → không gọi API
    B.download_1h_taker("TESTUSDT", datetime(2025, 12, 31, tzinfo=timezone.utc), datetime(2026, 1, 4, tzinfo=timezone.utc),
                        log=lambda *a: None)
    got = B.load_1h_taker("TESTUSDT", datetime(2026, 1, 4, tzinfo=timezone.utc))
    assert len(got) == 96 and got.index.is_monotonic_increasing and str(got.index.tz) == "Asia/Bangkok"
