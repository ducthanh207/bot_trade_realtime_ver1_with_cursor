# -*- coding: utf-8 -*-
"""[2026-11-07] File Excel kết quả backtest web: mở được, đủ sheet/cột, endpoint tải về."""
import io
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest.xlsx_export import TRADE_COLUMNS, backtest_result_xlsx, backtest_stats

RESULT = {
    "symbol": "BTCUSDT", "method": "4", "start": "2026-09-30T17:00:00+00:00", "end": "2026-11-07T00:00:00+00:00",
    "initial_capital": 1000.0, "final_balance": 1009.4, "total_pnl": 9.4, "winrate": 50.0, "wins": 1, "losses": 1,
    "max_drawdown_pct": 1.2, "exit_reasons": {"ATR_TRAIL": 1, "HARD_STOP": 1},
    "trades": [
        {"side": "LONG", "entry_time": "2026-10-02T07:00:00+07:00", "exit_time": "2026-10-02T15:00:00+07:00",
         "entry_price": 60000.0, "exit_price": 61000.0, "size": 0.01, "margin": 30.0, "fee_in": 0.3, "profit": 21.7,
         "capital_before": 1000.0, "capital_after": 1021.4, "exit_reason": "ATR_TRAIL", "entry_rsi": 55.1, "exit_rsi": None},
        {"side": "SHORT", "entry_time": "2026-10-03T07:00:00+07:00", "exit_time": "2026-10-03T11:00:00+07:00",
         "entry_price": 61000.0, "exit_price": 62000.0, "size": 0.01, "margin": 30.0, "fee_in": 0.3, "profit": -11.7,
         "capital_before": 1021.4, "capital_after": 1009.4, "exit_reason": "HARD_STOP", "cycle": "UP", "cycle_wide": False},
    ],
}


def test_xlsx_structure():
    data = backtest_result_xlsx(RESULT)
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/styles.xml"} <= names
    wb = z.read("xl/workbook.xml").decode()
    assert "Thống kê" in wb and "Lệnh" in wb
    trades = z.read("xl/worksheets/sheet2.xml").decode()
    assert trades.count("<row ") == 3  # tiêu đề + 2 lệnh
    assert "2026-10-02 07:00" in trades and "HARD_STOP" in trades
    try:
        import openpyxl  # có trên máy dev; VPS không cần
    except ImportError:
        return
    ws = openpyxl.load_workbook(io.BytesIO(data))["Lệnh"]
    assert [c.value for c in ws[1]] == [c for c, _ in TRADE_COLUMNS]
    assert ws.cell(row=3, column=11).value == -12.0  # profit ròng = profit − phí vào


def test_stats():
    st = dict(backtest_stats(RESULT))
    assert st["Lời/lỗ (USDT)"] == 9.4 and st["Lời/lỗ (%)"] == 0.94
    assert st["Từ"] == "2026-10-01 00:00"  # giờ VN
    assert st["Chuỗi thua dài nhất"] == 1 and st["Profit factor"] == round(21.4 / 12.0, 2)


def test_xlsx_endpoint():
    from backtest import web_backtest as wb
    from web.app import app

    wb._jobs["t_xlsx"] = {"created": time.time(), "params": {}, "result": dict(RESULT)}
    c = app.test_client()
    r = c.get("/api/backtest/job/t_xlsx/xlsx")
    assert r.status_code == 200 and r.data[:2] == b"PK"
    assert "backtest_PP4_BTCUSDT" in r.headers["Content-Disposition"]
    assert c.get("/api/backtest/job/khong_co/xlsx").status_code == 404
