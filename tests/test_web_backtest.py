# -*- coding: utf-8 -*-
"""[2026-11-01] Backtest trên web dùng engine live_replay: chạy được cho PP1–4, cùng khoảng ngày → cùng kết quả."""
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from backtest import binance_data as bd
from tests.test_live_replay import _synthetic_1m

SYM = "TESTWEBUSDT"


@pytest.fixture(scope="module")
def cache():
    df = _synthetic_1m(days=90, seed=3).tz_convert("UTC")  # 2025-01-01 → 2025-03-31
    d = bd.CACHE_DIR / SYM
    d.mkdir(parents=True, exist_ok=True)
    for (y, m), g in df.groupby([df.index.year, df.index.month]):
        g.to_csv(d / f"1m-{y:04d}-{m:02d}.csv.gz", compression="gzip")
    yield
    shutil.rmtree(d, ignore_errors=True)


def test_run_web_backtest_deterministic(cache):
    from backtest.web_backtest import run_web_backtest

    a = run_web_backtest("4", SYM, "2025-02-15", "2025-03-30", 1000, 20, 0.3)
    b = run_web_backtest("4", SYM, "2025-02-15", "2025-03-30", 1000, 20, 0.3)
    assert "error" not in a
    assert a["final_balance"] == b["final_balance"] and a["total_trades"] == b["total_trades"]
    assert a["trades"] and isinstance(a["trades"][0]["entry_time"], str)


def test_web_endpoint_job_does_not_touch_paper_state(cache):
    import bot.state as st
    from web import app as A

    before = (st.get_paper4_balance(), len(st.get_paper4_trades()))
    c = A.app.test_client()
    j = c.post("/api/paper4/backtest", json={"symbol": SYM, "start_date": "2025-02-15",
                                            "end_date": "2025-03-30", "initial_capital": 1000}).get_json()
    for _ in range(300):
        s = c.get("/api/backtest/job/" + j["job_id"]).get_json()
        if s["state"] != "running":
            break
        time.sleep(1)
    assert s["state"] == "done" and "error" not in s, s
    assert s["total_trades"] > 0
    assert (st.get_paper4_balance(), len(st.get_paper4_trades())) == before
