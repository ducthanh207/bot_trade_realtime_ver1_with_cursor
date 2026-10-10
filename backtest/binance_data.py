# -*- coding: utf-8 -*-
"""
Tải và cache dữ liệu nến 1m Binance USDT-M Futures cho backtest local.

Nguồn mặc định: API công khai Binance Futures fapi.binance.com/fapi/v1/klines (giống bot live).
Tuỳ chọn source="vision": file zip theo tháng trên data.binance.vision (không tính weight, nhanh hơn),
lỗi thì quay về API.

Chống lỗi request quá nhiều:
- Một bộ giới hạn weight dùng chung cho mọi luồng tải (mặc định 1200/2400 weight mỗi phút của Binance).
- Đọc header X-MBX-USED-WEIGHT-1M, tự chậm lại khi gần ngưỡng.
- 429 / 418: chờ đúng Retry-After rồi thử lại; lỗi mạng: thử lại với backoff tăng dần.
- Cache theo tháng trong backtest/data_cache/<SYMBOL>/1m-YYYY-MM.csv.gz; tháng đang chạy chỉ tải phần còn thiếu.

Chỉ lưu nến 1m ĐÃ ĐÓNG (bỏ nến đang chạy mà API trả về) để không lẫn dữ liệu chưa hoàn chỉnh.
Nến 1H / 4H được gộp (resample) từ 1m theo giờ UTC, trùng với nến 1H/4H của Binance
(4H mở lúc 00/04/08/12/16/20 UTC = 07/11/15/19/23/03 giờ VN).
"""

from __future__ import annotations

import io
import threading
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
KLINES_LIMIT = 1500
KLINES_WEIGHT = 10  # weight của /fapi/v1/klines khi limit 1000–1500
MINUTE = pd.Timedelta(minutes=1)


class WeightLimiter:
    """Giới hạn weight/phút dùng chung cho mọi luồng (cửa sổ trượt 60 giây)."""

    def __init__(self, max_weight_per_min: int = 1200):
        self.max_weight = max_weight_per_min
        self._lock = threading.Lock()
        self._events: list[tuple[float, int]] = []
        self._pause_until = 0.0

    def acquire(self, weight: int):
        while True:
            with self._lock:
                now = time.monotonic()
                self._events = [(t, w) for t, w in self._events if now - t < 60]
                used = sum(w for _, w in self._events)
                wait = self._pause_until - now
                if wait <= 0 and used + weight <= self.max_weight:
                    self._events.append((now, weight))
                    return
                if wait <= 0:
                    wait = 60 - (now - self._events[0][0]) + 0.05
            time.sleep(min(max(wait, 0.05), 60))

    def pause(self, seconds: float):
        with self._lock:
            self._pause_until = max(self._pause_until, time.monotonic() + seconds)

    def observe_used_weight(self, used: int | None, server_limit: int = 2400):
        """Server báo đã dùng gần hết weight (vd do chương trình khác cùng IP) → nghỉ tới phút sau."""
        if used is not None and used >= server_limit * 0.8:
            self.pause(61 - datetime.now().second)


LIMITER = WeightLimiter()
_session = threading.local()


def _http():
    s = getattr(_session, "s", None)
    if s is None:
        s = _session.s = requests.Session()
    return s


def _get_json(url: str, params: dict, log=print, max_retries: int = 8):
    backoff = 2.0
    for attempt in range(1, max_retries + 1):
        LIMITER.acquire(KLINES_WEIGHT)
        try:
            r = _http().get(url, params=params, timeout=30)
        except requests.RequestException as e:
            log(f"    lỗi mạng ({e}), thử lại sau {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        used = r.headers.get("X-MBX-USED-WEIGHT-1M")
        LIMITER.observe_used_weight(int(used) if used and used.isdigit() else None)
        if r.status_code in (429, 418):
            retry = int(r.headers.get("Retry-After", "60") or 60)
            log(f"    Binance báo {r.status_code} (quá nhiều request) → nghỉ {retry}s")
            LIMITER.pause(retry)
            continue
        if r.status_code >= 500:
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Không tải được {url} {params} sau {max_retries} lần")


def _parse_kline_rows(rows) -> pd.DataFrame:
    """rows: list các dòng kline Binance [open_time, o, h, l, c, v, ...] → DataFrame index UTC."""
    if not rows:
        return pd.DataFrame(columns=COLS, index=pd.DatetimeIndex([], tz="UTC", name="timestamp"))
    df = pd.DataFrame([r[:6] for r in rows], columns=["open_time"] + COLS)
    df["open_time"] = pd.to_numeric(df["open_time"])
    if df["open_time"].iloc[0] > 10**14:  # một số file mới dùng micro giây
        df["open_time"] = df["open_time"] // 1000
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df.index.name = "timestamp"
    df = df[COLS].astype(float)
    return df[~df.index.duplicated()].sort_index()


def _read_vision_zip(url: str) -> pd.DataFrame | None:
    r = _http().get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        raw = z.read(z.namelist()[0]).decode()
    rows = [line.split(",") for line in raw.splitlines() if line[:1].isdigit()]  # bỏ dòng header
    return _parse_kline_rows(rows)


def _fetch_rest(symbol: str, start: pd.Timestamp, end: pd.Timestamp, log=print) -> pd.DataFrame:
    """Phân trang fapi klines 1m trong [start, end)."""
    out = []
    cur, end_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    while cur < end_ms:
        data = _get_json(
            f"{FAPI_BASE}/fapi/v1/klines",
            {"symbol": symbol, "interval": "1m", "startTime": cur, "endTime": end_ms - 1, "limit": KLINES_LIMIT},
            log,
        )
        if not data:
            break
        out.extend(data)
        cur = int(data[-1][0]) + 60_000
    return _parse_kline_rows(out)


def _month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _read_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    return df


def _load_month(symbol: str, y: int, m: int, log=print, source: str = "api") -> pd.DataFrame:
    month_start = pd.Timestamp(datetime(y, m, 1, tzinfo=timezone.utc))
    month_end = pd.Timestamp(datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc))
    # Chỉ nến đã đóng: nến mở lúc t đóng lúc t+1m
    last_closed_open = pd.Timestamp.now(tz="UTC").floor("min") - MINUTE
    until = min(month_end, last_closed_open + MINUTE)
    if until <= month_start:
        return pd.DataFrame(columns=COLS)
    cache = CACHE_DIR / symbol / f"1m-{y:04d}-{m:02d}.csv.gz"

    df = _read_cache(cache)
    if df is not None and not df.empty and df.index[-1] >= until - MINUTE:
        return df  # cache đã đủ

    if df is None or df.empty:
        df = None
        if source == "vision" and month_end <= until:
            try:
                df = _read_vision_zip(f"{VISION_BASE}/monthly/klines/{symbol}/1m/{symbol}-1m-{y:04d}-{m:02d}.zip")
                if df is not None:
                    log(f"  {symbol} {y:04d}-{m:02d}: tải zip tháng OK ({len(df):,} nến)")
            except Exception as e:
                log(f"  {symbol} {y:04d}-{m:02d}: data.binance.vision lỗi ({e}), chuyển sang API")
        fetch_from = month_start
    else:
        fetch_from = df.index[-1] + MINUTE  # chỉ tải phần còn thiếu

    if df is None or df.empty or df.index[-1] < until - MINUTE:
        log(f"  {symbol} {y:04d}-{m:02d}: tải qua API fapi.binance.com từ {fetch_from:%Y-%m-%d %H:%M} UTC...")
        new = _fetch_rest(symbol, fetch_from, until, log)
        df = new if df is None or df.empty else pd.concat([df, new])

    df = df[(df.index >= month_start) & (df.index < until)]
    df = df[~df.index.duplicated()].sort_index()
    if not df.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache, compression="gzip")
    return df


def download(symbol: str, start: datetime, end: datetime, log=print, source: str = "api") -> None:
    """Tải trước về cache (để chạy nhiều luồng tải; backtest đọc lại từ cache)."""
    for y, m in _month_iter(start.date(), (end - timedelta(minutes=1)).date()):
        _load_month(symbol.upper(), y, m, log, source)


def load_1m(symbol: str, start: datetime, end: datetime, log=print, source: str = "api", offline: bool = False) -> pd.DataFrame:
    """Nến 1m đã đóng trong [start, end) — index tz Asia/Bangkok giống BinanceClient của bot.
    offline=True: chỉ đọc cache (dùng sau bước download, không gửi request nào)."""
    symbol = symbol.upper()
    months = list(_month_iter(start.date(), (end - timedelta(minutes=1)).date()))
    if offline:
        parts = [_read_cache(CACHE_DIR / symbol / f"1m-{y:04d}-{m:02d}.csv.gz") for y, m in months]
    else:
        parts = [_load_month(symbol, y, m, log, source) for y, m in months]
    parts = [p for p in parts if p is not None and not p.empty]
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat(parts).sort_index()
    df = df[~df.index.duplicated()]
    df = df[(df.index >= pd.Timestamp(start)) & (df.index < pd.Timestamp(end))]
    df.index = df.index.tz_convert(TZ_NAME)
    return df


def resample_ohlcv(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Gộp 1m → 1h/4h, neo theo giờ UTC như Binance. Nến cuối có thể chưa đủ phút: chỉ dùng nến đã đóng."""
    utc = df_1m.tz_convert("UTC") if df_1m.index.tz is not None else df_1m
    out = utc.resample(rule, origin="epoch", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna(subset=["open"])
    out.index = out.index.tz_convert(TZ_NAME)
    out.index.name = "timestamp"
    return out
