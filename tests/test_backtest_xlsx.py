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
    assert {"xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/worksheets/sheet3.xml", "xl/styles.xml",
            "xl/media/image1.png", "xl/drawings/drawing1.xml", "xl/worksheets/_rels/sheet2.xml.rels"} <= names
    wb = z.read("xl/workbook.xml").decode()
    assert "Tổng quan" in wb and "Biểu đồ PnL" in wb and "Lệnh" in wb  # [2026-11-22] 3 sheet
    assert z.read("xl/media/image1.png")[:8] == b"\x89PNG\r\n\x1a\n"
    trades = z.read("xl/worksheets/sheet3.xml").decode()
    assert trades.count("<row ") == 3  # tiêu đề + 2 lệnh
    assert "2026-10-02 07:00" in trades and "HARD_STOP" in trades
    try:
        import openpyxl  # có trên máy dev; VPS không cần
    except ImportError:
        return
    wbk = openpyxl.load_workbook(io.BytesIO(data))
    assert wbk.sheetnames == ["Tổng quan", "Biểu đồ PnL", "Lệnh"]
    ov = {r[0]: r[1] for r in wbk["Tổng quan"].iter_rows(values_only=True) if r and r[0]}
    assert ov["Cặp"] == "BTCUSDT" and ov["Lời/lỗ (USDT)"] == 9.4 and ov["HARD_STOP"] == 1
    assert len(wbk["Biểu đồ PnL"]._images) == 1
    ws = wbk["Lệnh"]
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
    assert "PP4_BTCUSDT_2026-10-01_den_2026-11-07_chay-" in r.headers["Content-Disposition"]
    assert c.get("/api/backtest/job/khong_co/xlsx").status_code == 404


def test_filename_rule():
    from backtest.xlsx_export import backtest_filename

    meta = {"saved_at": 1795334340}  # 2026-11-22 07:59 UTC = 14:59 giờ VN
    assert backtest_filename(RESULT, meta, "ab12cd3456") == "PP4_BTCUSDT_2026-10-01_den_2026-11-07_chay-20261122-1459_ab12cd.xlsx"
    r = dict(RESULT, label="PP6.1 / CVD", overrides={"M6_EXIT_MODE": "close"})
    assert backtest_filename(r, {}, None) == "PP6.1-CVD_BTCUSDT_2026-10-01_den_2026-11-07_thamso.xlsx"


def test_zip_endpoint(tmp_path, monkeypatch):
    """[2026-11-22] Tải nhiều kết quả: ZIP = 1 thư mục gồm các file Excel + TONG_HOP.xlsx."""
    from backtest import results_store as rs
    from web.app import app

    monkeypatch.setattr(rs, "DIR", tmp_path)
    monkeypatch.setattr(rs, "INDEX", tmp_path / "index.json")
    rs.save("aaaaaaaa11", {"method": "4"}, dict(RESULT))
    rs.save("bbbbbbbb22", {"method": "4"}, dict(RESULT, symbol="ETHUSDT"))
    c = app.test_client()
    r = c.get("/api/backtests/zip?ids=aaaaaaaa11,bbbbbbbb22,cccccccc33")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = z.namelist()
    folder = names[0].split("/")[0]
    assert folder.startswith("backtest_") and all(n.startswith(folder + "/") for n in names)
    assert len(names) == 3 and any("ETHUSDT" in n for n in names) and names[-1].endswith("/TONG_HOP.xlsx")
    assert zipfile.ZipFile(io.BytesIO(z.read(names[0]))).read("xl/media/image1.png")[:4] == b"\x89PNG"
    assert c.get("/api/backtests/zip?ids=").status_code == 400
    assert c.get("/api/backtests/zip?ids=cccccccc33").status_code == 404


def test_web_jobs_run_in_parallel(monkeypatch):
    """[2026-11-07] Backtest ở các tab chạy song song (tới MAX_PARALLEL), không xếp hàng từng cái một."""
    import subprocess
    import threading
    from backtest import web_backtest as wb

    active, peak, lock = [0], [0], threading.Lock()

    def fake_run(*a, **k):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.5)
        with lock:
            active[0] -= 1
        return subprocess.CompletedProcess(a, 0, stdout=wb.RESULT_PREFIX + '{"ok": 1}', stderr="")

    monkeypatch.setattr(wb.subprocess, "run", fake_run)
    ids = [wb.submit(method=str(m)) for m in (1, 2, 3, 4)]
    deadline = time.time() + 5
    while time.time() < deadline and any(wb.status(i)["state"] == "running" for i in ids):
        time.sleep(0.05)
    assert all(wb.status(i)["state"] == "done" for i in ids)
    assert peak[0] == wb.MAX_PARALLEL
