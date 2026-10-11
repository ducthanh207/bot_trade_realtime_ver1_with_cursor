# -*- coding: utf-8 -*-
"""Tải dữ liệu: tôn trọng 429/418 (Retry-After) và giới hạn weight, chỉ giữ nến đã đóng."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import binance_data as bd


class _Resp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code, self._payload, self.headers = status, payload, headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_retry_after_429(monkeypatch):
    sess = _Session([_Resp(429, headers={"Retry-After": "1"}), _Resp(200, [[1, "1", "1", "1", "1", "1"]])])
    monkeypatch.setattr(bd, "_http", lambda: sess)
    monkeypatch.setattr(bd, "LIMITER", bd.WeightLimiter(1200))
    t0 = time.monotonic()
    assert bd._get_json("u", {}, log=lambda *_: None) == [[1, "1", "1", "1", "1", "1"]]
    assert sess.calls == 2 and time.monotonic() - t0 >= 0.9  # đã nghỉ đúng Retry-After


def test_weight_limiter_blocks_over_budget(monkeypatch):
    lim = bd.WeightLimiter(20)
    lim.acquire(10)
    lim.acquire(10)
    slept = []
    monkeypatch.setattr(bd.time, "sleep", lambda s: (slept.append(s), lim._events.clear()))
    lim.acquire(10)  # vượt ngân sách → phải chờ trước khi gửi
    assert slept and slept[0] > 50


def test_parse_skips_header_and_microseconds():
    rows = [["1735689600000000", "1", "2", "0.5", "1.5", "10"]]
    df = bd._parse_kline_rows(rows)
    assert str(df.index[0]) == "2025-01-01 00:00:00+00:00"
