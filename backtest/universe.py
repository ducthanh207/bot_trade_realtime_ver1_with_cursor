# -*- coding: utf-8 -*-
"""
Chọn danh sách cặp coin để backtest (chỉ cặp USDT-M Perpetual đang có trên Binance Futures):

- volume: top N cặp có volume (USDT) biến động mạnh nhất trong khoảng thời gian backtest.
  Biến động = độ lệch chuẩn / trung bình của volume ngày (hệ số biến thiên). Chỉ xét trong
  nhóm `liquid_pool` cặp có volume trung bình lớn nhất để tránh coin quá ít thanh khoản.
  metric="total" → chọn theo tổng volume thay vì độ biến động.
- marketcap: top N coin vốn hoá lớn nhất theo CoinMarketCap (cần CMC_API_KEY miễn phí trong .env),
  không có key thì dùng CoinGecko. Bỏ stablecoin và coin không có hợp đồng Futures USDT trên Binance.
  Lưu ý: API miễn phí chỉ cho vốn hoá HIỆN TẠI, không phải vốn hoá tại ngày bắt đầu backtest.

Chỉ giữ cặp đã niêm yết trên Binance Futures trước ngày bắt đầu (đủ dữ liệu cho cả khoảng).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backtest import binance_data as bd

CMC_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
STABLECOINS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "USDS", "PYUSD", "USDD", "BUSD", "USD1", "FRAX",
    "USDP", "GUSD", "LUSD", "EURC", "EURT", "USDX", "RLUSD", "USDG", "USDTB", "USD0", "SUSDE", "BFUSD",
    "USDF", "CRVUSD", "GHO", "USTC", "XAUT", "PAXG",
}


def _norm_base(base: str) -> str:
    """1000PEPE → PEPE, 1MBABYDOGE → BABYDOGE, 1000000MOG → MOG."""
    return re.sub(r"^(1000000|1000|1M)(?=[A-Z])", "", base.upper())


def binance_usdt_perps(log=print) -> pd.DataFrame:
    """Các hợp đồng USDT-M Perpetual đang giao dịch: symbol, base (đã chuẩn hoá), onboard (ngày niêm yết)."""
    info = bd._get_json(f"{bd.FAPI_BASE}/fapi/v1/exchangeInfo", {}, log, weight=1)
    rows = []
    for s in info.get("symbols", []):
        if s.get("contractType") != "PERPETUAL" or s.get("quoteAsset") != "USDT" or s.get("status") != "TRADING":
            continue
        rows.append({
            "symbol": s["symbol"],
            "base": _norm_base(s.get("baseAsset", "")),
            "onboard": pd.Timestamp(int(s.get("onboardDate", 0)), unit="ms", tz="UTC"),
        })
    return pd.DataFrame(rows)


def _kline_weight(limit: int) -> int:
    return 1 if limit < 100 else 2 if limit < 500 else 5 if limit <= 1000 else 10


def daily_quote_volume(symbol: str, start: datetime, end: datetime, log=print) -> pd.Series:
    """Volume ngày tính bằng USDT (cột quote volume của kline 1d) trong [start, end)."""
    out, cur = [], int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    while cur < end_ms:
        limit = min(1000, max(1, (end_ms - cur) // 86_400_000 + 1))
        data = bd._get_json(
            f"{bd.FAPI_BASE}/fapi/v1/klines",
            {"symbol": symbol, "interval": "1d", "startTime": cur, "endTime": end_ms - 1, "limit": limit},
            log, weight=_kline_weight(limit),
        )
        if not data:
            break
        out += [(int(k[0]), float(k[7])) for k in data]
        cur = int(data[-1][0]) + 86_400_000
    if not out:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(t, unit="ms", tz="UTC"): v for t, v in out})
    return s[~s.index.duplicated()].sort_index()


def rank_by_volume(start, end, top=10, liquid_pool=50, metric="cv", log=print, perps=None) -> pd.DataFrame:
    perps = binance_usdt_perps(log) if perps is None else perps
    perps = perps[perps["onboard"] <= pd.Timestamp(start)]
    days = max(1, (pd.Timestamp(end) - pd.Timestamp(start)).days)
    log(f"Xếp hạng volume: tải volume ngày của {len(perps)} cặp Futures USDT ({days} ngày)...")
    rows = []
    for sym in perps["symbol"]:
        v = daily_quote_volume(sym, start, end, log)
        if len(v) < 0.9 * days or v.mean() <= 0:
            continue
        rows.append({"symbol": sym, "avg_daily_volume_usdt": v.mean(), "total_volume_usdt": v.sum(),
                     "volume_cv": v.std() / v.mean()})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.sort_values("avg_daily_volume_usdt", ascending=False).head(liquid_pool)
    key = "volume_cv" if metric == "cv" else "total_volume_usdt"
    df = df.sort_values(key, ascending=False).head(top).reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, len(df) + 1))
    return df


def _market_caps(log=print) -> list[dict]:
    """[{base, name, market_cap, stable}] theo thứ tự vốn hoá giảm dần."""
    key = os.environ.get("CMC_API_KEY", "").strip()
    sess = bd._http()
    if key:
        r = sess.get(CMC_URL, params={"limit": 300, "sort": "market_cap", "convert": "USD"},
                     headers={"X-CMC_PRO_API_KEY": key, "Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        log("Market cap: lấy từ CoinMarketCap")
        return [{"base": c["symbol"].upper(), "name": c["name"],
                 "market_cap": c["quote"]["USD"]["market_cap"], "stable": "stablecoin" in (c.get("tags") or [])}
                for c in r.json()["data"]]
    log("Market cap: chưa có CMC_API_KEY trong .env → dùng CoinGecko")
    r = sess.get(COINGECKO_URL, params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": 1},
                 timeout=30)
    r.raise_for_status()
    return [{"base": c["symbol"].upper(), "name": c["name"], "market_cap": c.get("market_cap") or 0,
             "stable": abs((c.get("current_price") or 0) - 1) < 0.02 and "USD" in c["symbol"].upper()}
            for c in r.json()]


def rank_by_market_cap(start, top=10, log=print, perps=None, caps=None) -> pd.DataFrame:
    perps = binance_usdt_perps(log) if perps is None else perps
    perps = perps[perps["onboard"] <= pd.Timestamp(start)]
    by_base = {}
    for _, p in perps.iterrows():
        # ưu tiên hợp đồng đúng tên (BTCUSDT) hơn bản nhân 1000
        if p["base"] not in by_base or p["symbol"] == p["base"] + "USDT":
            by_base[p["base"]] = p["symbol"]
    caps = _market_caps(log) if caps is None else caps
    rows, seen = [], set()
    for c in caps:
        if c["stable"] or c["base"] in STABLECOINS or c["base"] in seen or c["base"] not in by_base:
            continue
        seen.add(c["base"])
        rows.append({"symbol": by_base[c["base"]], "name": c["name"], "market_cap_usd": c["market_cap"]})
        if len(rows) >= top:
            break
    df = pd.DataFrame(rows)
    if not df.empty:
        df.insert(0, "rank", np.arange(1, len(df) + 1))
    return df


def select_universe(kind: str, start, end, top=10, liquid_pool=50, volume_metric="cv", log=print) -> dict:
    """Trả {tên nhóm: DataFrame xếp hạng}. kind: volume | marketcap | both."""
    perps = binance_usdt_perps(log)
    groups = {}
    if kind in ("volume", "both"):
        groups["volume"] = rank_by_volume(start, end, top, liquid_pool, volume_metric, log, perps)
    if kind in ("marketcap", "both"):
        groups["marketcap"] = rank_by_market_cap(start, top, log, perps)
    return groups
