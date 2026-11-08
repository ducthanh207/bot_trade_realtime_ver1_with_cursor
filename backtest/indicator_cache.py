# -*- coding: utf-8 -*-
"""
[2026-11-08] Bộ nhớ chỉ báo cho backtest strict (lưu trên đĩa, dùng lại giữa các lần chạy).

Backtest strict tính lại chỉ báo trên cửa sổ 200 nến đã đóng ở mỗi mốc 4H và mỗi giờ (y như bot live)
→ chậm ~10 lần so với đọc sẵn. Giá trị đó chỉ phụ thuộc các nến đã đóng trước mốc, không bao giờ đổi,
nên lưu lại theo (cặp coin, mốc thời gian): chạy 1 năm xong, chạy lại 1 tháng bất kỳ trong năm đó chỉ việc đọc.

Chỉ lưu kết quả tính trên cửa sổ ĐỦ 199 nến (như live) → lần chạy sau có lịch sử dài/ngắn khác vẫn cho cùng số.
File: backtest/data_cache/<SYMBOL>/ind_<khoá>.pkl. Khoá đổi khi tham số chỉ báo hoặc CACHE_VERSION đổi
(file cũ bỏ qua, xoá tay được). Xoá file = tính lại từ đầu, không ảnh hưởng kết quả.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import threading
from pathlib import Path

import pandas as pd

from config import settings

CACHE_VERSION = 1
CACHE_DIR = Path(__file__).resolve().parent / "data_cache"


def cache_key() -> str:
    """Khoá theo tham số ảnh hưởng tới chỉ báo (add_indicators mặc định + add_indicators_m3)."""
    raw = f"v{CACHE_VERSION}|m3ema={getattr(settings, 'M3_EMA_TREND_LEN', 50)}|swing={getattr(settings, 'M3_SWING_LOOKBACK', 6)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


class IndicatorCache:
    """
    h4[T]  = (row_closed, prev_row_closed, row_m3 | None) của cửa sổ 4H có nến đóng cuối mở lúc T
    h1[h]  = DataFrame 2 dòng cuối của add_indicators trên cửa sổ 1H có nến đóng cuối mở lúc h
    """

    def __init__(self, symbol: str, enabled: bool = True):
        self.enabled = enabled
        self.path = CACHE_DIR / symbol.upper() / f"ind_{cache_key()}.pkl"
        self.h4: dict = {}
        self.h1: dict = {}
        self.dirty = 0
        self.hits = 0
        if enabled:
            self._load()

    def _load(self):
        try:
            with open(self.path, "rb") as f:
                data = pickle.load(f)
            if data.get("version") == CACHE_VERSION:
                self.h4 = data.get("h4") or {}
                self.h1 = data.get("h1") or {}
        except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ImportError, TypeError):
            self.h4, self.h1 = {}, {}

    def save(self):
        """Ghi (gộp với bản trên đĩa nếu job khác vừa ghi), qua file tạm rồi đổi tên."""
        if not self.enabled or not self.dirty:
            return
        try:
            disk = IndicatorCache.__new__(IndicatorCache)
            disk.path, disk.h4, disk.h1 = self.path, {}, {}
            disk._load()
            disk.h4.update(self.h4)
            disk.h1.update(self.h1)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            with open(tmp, "wb") as f:
                pickle.dump({"version": CACHE_VERSION, "h4": disk.h4, "h1": disk.h1}, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self.path)
            self.dirty = 0
        except OSError:
            pass

    # ------------------------------------------------------------ đọc / ghi trong bộ nhớ
    def get4(self, t):
        if not self.enabled:
            return None
        v = self.h4.get(pd.Timestamp(t).value)
        if v is not None:
            self.hits += 1
        return v

    def put4(self, t, value):
        if self.enabled:
            self.h4[pd.Timestamp(t).value] = value
            self.dirty += 1

    def get1(self, h):
        if not self.enabled:
            return None
        v = self.h1.get(pd.Timestamp(h).value)
        if v is not None:
            self.hits += 1
        return v

    def put1(self, h, value: pd.DataFrame):
        if self.enabled:
            self.h1[pd.Timestamp(h).value] = value
            self.dirty += 1
