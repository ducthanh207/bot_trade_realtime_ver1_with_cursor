# -*- coding: utf-8 -*-
"""Chọn cặp theo volume / market cap (giả lập API, không gọi mạng)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from backtest import universe as U

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 3, 1, tzinfo=timezone.utc)
OLD = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
NEW = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)

PERPS = pd.DataFrame([
    {"symbol": "BTCUSDT", "base": "BTC", "onboard": pd.Timestamp(OLD, unit="ms", tz="UTC")},
    {"symbol": "ETHUSDT", "base": "ETH", "onboard": pd.Timestamp(OLD, unit="ms", tz="UTC")},
    {"symbol": "1000PEPEUSDT", "base": "PEPE", "onboard": pd.Timestamp(OLD, unit="ms", tz="UTC")},
    {"symbol": "USDCUSDT", "base": "USDC", "onboard": pd.Timestamp(OLD, unit="ms", tz="UTC")},
    {"symbol": "NEWUSDT", "base": "NEW", "onboard": pd.Timestamp(NEW, unit="ms", tz="UTC")},
])


def test_norm_base():
    assert U._norm_base("1000PEPE") == "PEPE"
    assert U._norm_base("1MBABYDOGE") == "BABYDOGE"
    assert U._norm_base("1INCH") == "1INCH"


def test_rank_by_volume_cv(monkeypatch):
    rng = np.random.default_rng(0)
    idx = pd.date_range(START, END, freq="D", inclusive="left")
    vols = {
        "BTCUSDT": pd.Series(1e10 + rng.normal(0, 1e8, len(idx)), index=idx),   # lớn, ổn định
        "ETHUSDT": pd.Series(5e9 * (1 + 2 * (np.arange(len(idx)) % 7 == 0)), index=idx),  # lớn, biến động
        "1000PEPEUSDT": pd.Series(np.full(len(idx), 1e8), index=idx),
        "USDCUSDT": pd.Series(np.full(len(idx), 1e6), index=idx),
    }
    monkeypatch.setattr(U, "daily_quote_volume", lambda s, a, b, log=None: vols.get(s, pd.Series(dtype=float)))
    df = U.rank_by_volume(START, END, top=2, liquid_pool=3, perps=PERPS, log=lambda *_: None)
    assert list(df["symbol"]) == ["ETHUSDT", "BTCUSDT"]  # USDC bị loại khỏi nhóm thanh khoản; NEW niêm yết sau start
    df2 = U.rank_by_volume(START, END, top=1, liquid_pool=3, metric="total", perps=PERPS, log=lambda *_: None)
    assert list(df2["symbol"]) == ["BTCUSDT"]


def test_rank_by_market_cap_maps_and_filters():
    caps = [
        {"base": "BTC", "name": "Bitcoin", "market_cap": 2e12, "stable": False},
        {"base": "USDT", "name": "Tether", "market_cap": 1e11, "stable": True},
        {"base": "ETH", "name": "Ethereum", "market_cap": 5e11, "stable": False},
        {"base": "STETH", "name": "Lido Staked ETH", "market_cap": 3e10, "stable": False},  # không có Futures
        {"base": "USDC", "name": "USDC", "market_cap": 6e10, "stable": False},
        {"base": "NEW", "name": "New", "market_cap": 2e10, "stable": False},  # niêm yết sau start
        {"base": "PEPE", "name": "Pepe", "market_cap": 5e9, "stable": False},
    ]
    df = U.rank_by_market_cap(START, top=10, perps=PERPS, caps=caps, log=lambda *_: None)
    assert list(df["symbol"]) == ["BTCUSDT", "ETHUSDT", "1000PEPEUSDT"]
