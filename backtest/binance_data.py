# -*- coding: utf-8 -*-
"""
Tải và cache dữ liệu nến 1m Binance USDT-M Futures cho backtest local.

Nguồn mặc định: API công khai Binance Futures fapi.binance.com/fapi/v1/klines (giống bot live).
Tuỳ chọn source="vision": file zip theo tháng trên data.binance.vision (nhanh hơn), lỗi thì quay về API.
Cache: backtest/data_cache/<SYMBOL>/1m-YYYY-MM.csv.gz — tải một lần, chạy lại không cần mạng.

Nến 1H / 4H được gộp (resample) từ 1m theo giờ UTC, trùng với nến 1H/4H của Binance
(4H mở lúc 00/04/08/12/16/20 UTC = 07/11/15/19/23/03 giờ VN).
"""

from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

VISION_BASE = "https://data.binance.vision/data/futures/um"
FAPI_BASE = "https://fapi.binance.com"
TZ_NAME = "Asia/Bangkok"
CACHE_DIR = Path(__file__).resolve().parent / "data_cache"
COLS = ["open", "high", "low", "close", "volume"]


def _parse_kline_rows(rows) -> pd.DataFrame:
    """rows: list các dòng kline Binance [open_time, o, h, l, c, v, ...] → DataFrame index UTC."""
    if not rows:
        return pd.DataFrame(columns=COLS)
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time"] + COLS)
    df["open_time"] = pd.to_numeric(df["open_time"])
    # Một số file mới dùng micro giây
    if df["open_time"].iloc[0] > 10**14:
        df["open_time"] = df["open_time"] // 1000
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = "timestamp"
    df = df[COLS].astype(float)
    return df[~df.index.duplicated()].sort_index()


def _read_vision_zip(url: str) -> pd.DataFrame | None:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode()
    rows = []
    for line in raw.splitlines():
        parts = line.split(",")
        if not parts or not parts[0].strip().isdigit():
            continue  # dòng header
        rows.append(parts)
    return _parse_kline_rows(rows)


def _fetch_rest(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """Dự phòng: phân trang fapi klines 1m (1500 nến/lần)."""
    out = []
    cur = int(start.timestamp() * 1000)
    end_ms = int(end.timestamp() * 1000)
    while cur < end_ms:
        r = requests.get(
            f"{FAPI_BASE}/fapi/v1/klines",
            params={"symbol": symbol, "interval": "1m", "startTime": cur, "endTime": end_ms - 1, "limit": 1500},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        out.extend(data)
        cur = int(data[-1][0]) + 60_000
        time.sleep(0.15)  # tôn trọng rate limit
    return _parse_kline_rows(out)


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _load_month(symbol: str, y: int, m: int, log=print, source: str = "api") -> pd.DataFrame:
    month_start = datetime(y, m, 1, tzinfo=timezone.utc)
    month_end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    complete = month_end <= now
    cache = CACHE_DIR / symbol / f"1m-{y:04d}-{m:02d}.csv.gz"
    if complete and cache.exists():
        df = pd.read_csv(cache, index_col=0)
        df.index = pd.to_datetime(df.index, utc=True)
        return df

    df = None
    if complete and source == "vision":
        try:
            df = _read_vision_zip(f"{VISION_BASE}/monthly/klines/{symbol}/1m/{symbol}-1m-{y:04d}-{m:02d}.zip")
        except Exception as e:  # mạng chặn data.binance.vision → dùng REST
            log(f"  data.binance.vision lỗi ({e}), chuyển sang REST")
    if df is None or df.empty:
        log(f"  {symbol} {y:04d}-{m:02d}: tải qua API fapi.binance.com...")
        df = _fetch_rest(symbol, month_start, min(month_end, now))
    else:
        log(f"  {symbol} {y:04d}-{m:02d}: tải zip tháng OK ({len(df)} nến)")
    if complete and not df.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, compression="gzip")
    return df


def load_1m(symbol: str, start: datetime, end: datetime, log=print, source: str = "api") -> pd.DataFrame:
    """Nến 1m [start, end) — index tz Asia/Bangkok giống BinanceClient của bot."""
    symbol = symbol.upper()
    parts = [_load_month(symbol, y, m, log, source) for y, m in _month_iter(start.date(), (end - timedelta(minutes=1)).date())]
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated()]
    df = df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]
    df.index = df.index.tz_convert(TZ_NAME)
    return df


def resample_ohlcv(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Gộp 1m → 1h/4h, neo theo giờ UTC như Binance."""
    utc = df_1m.tz_convert("UTC") if df_1m.index.tz is not None else df_1m
    out = utc.resample(rule, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])
    out.index = out.index.tz_convert(TZ_NAME)
    out.index.name = "timestamp"
    return out
