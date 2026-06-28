# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from strategy.exit_engine import rsi_1h_reversal, touch_pct_band_in_forming_4h


def test_rsi_1h_reversal_long():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="Asia/Bangkok")
    df = pd.DataFrame({"RSI": [50.0, 55.0, 60.0, 58.0, 52.0]}, index=idx)
    assert rsi_1h_reversal("LONG", df) is True  # iloc[-2]=52 < iloc[-3]=58
    idx6 = pd.date_range("2024-01-01", periods=6, freq="h", tz="Asia/Bangkok")
    df2 = pd.DataFrame({"RSI": [50.0, 50.0, 50.0, 58.0, 58.0, 59.0]}, index=idx6)
    assert rsi_1h_reversal("LONG", df2) is False  # iloc[-2]=59 không < iloc[-3]=58


def test_rsi_1h_reversal_short():
    idx = pd.date_range("2024-01-01", periods=5, freq="h", tz="Asia/Bangkok")
    df = pd.DataFrame({"RSI": [50.0, 55.0, 54.0, 58.0, 62.0]}, index=idx)
    assert rsi_1h_reversal("SHORT", df) is True  # iloc[-2]=58 > iloc[-3]=54


def test_touch_pct_band():
    t0 = pd.Timestamp("2024-03-20 19:00", tz="Asia/Bangkok")
    ix = pd.date_range(t0, periods=10, freq="1min", tz="Asia/Bangkok")
    df_1m = pd.DataFrame({"high": [70000.0] * 10, "low": [69000.0] * 10}, index=ix)
    assert touch_pct_band_in_forming_4h("LONG", df_1m, 69900.0, 68000.0, t0) is True
    assert touch_pct_band_in_forming_4h("SHORT", df_1m, 71000.0, 69150.0, t0) is True


if __name__ == "__main__":
    test_rsi_1h_reversal_long()
    test_rsi_1h_reversal_short()
    test_touch_pct_band()
    print("tests/test_exit_engine.py OK")
