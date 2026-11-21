# -*- coding: utf-8 -*-
"""[2026-11-21] "Hộp và đĩa": định dạng đĩa, kiểm tra an toàn, PP1–PP7 chạy y hệt code cũ, tham số riêng theo đĩa, paper đĩa, web."""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from config import settings
from strategy import disks as D

PP7_TEXT = (ROOT / "strategies" / "pp7.md").read_text(encoding="utf-8")


def _variant(text=PP7_TEXT, did="pp7-risk1", params="params:\n  M7_RISK_PCT: 0.01\n"):
    t = text.replace('id: "7"', f"id: {did}", 1)
    return t.replace("  risk_sizing: true\n---", "  risk_sizing: true\n" + params + "---", 1)


@pytest.fixture
def tmp_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "UPLOAD_DIR", tmp_path / "strategies")
    D._cache["disks"] = None
    D._by_id_fast.clear()
    yield tmp_path
    D._cache["disks"] = None
    D._by_id_fast.clear()


# ---------------------------------------------------------------- đĩa có sẵn
def test_builtin_disks_match_code_spec():
    disks = D.all_disks()
    assert D.load_errors() == {}
    for bid, (base, blocks) in D.BUILTIN_SPEC.items():
        d = disks[bid]
        assert d.source == "builtin" and d.base == base and d.blocks == frozenset(blocks) and d.params == {}
        assert d.text, f"thiếu file strategies/ cho đĩa {bid}"
    assert D.get_disk("6.1").daily and D.get_disk("6.1").cvd
    assert D.get_disk("unknown").id == "1"  # mã lạ → PP1 như code cũ
    assert [d.label for d in D.sorted_disks()][:8] == ["PP1", "PP2", "PP3", "PP4", "PP5", "PP6", "PP6.1", "PP7"]


def test_builtin_file_cannot_change_live_strategy(tmp_path, monkeypatch):
    """File đĩa có sẵn bị sửa khối → vẫn dùng thành phần chốt trong code (bảo vệ PP1–PP5 đang chạy)."""
    bdir = tmp_path / "b"
    bdir.mkdir()
    (bdir / "pp4.md").write_text((ROOT / "strategies" / "pp4.md").read_text(encoding="utf-8").replace(
        "regime_cut: true", "risk_sizing: true\n  stop_atr_4h: true"), encoding="utf-8")
    monkeypatch.setattr(D, "BUILTIN_DIR", bdir)
    monkeypatch.setattr(D, "UPLOAD_DIR", tmp_path / "u")
    D._cache["disks"] = None
    D._by_id_fast.clear()
    try:
        d4 = D.get_disk("4")
        assert d4.blocks == frozenset({"regime_cut"}) and "4" in D.load_errors()
        assert D.get_disk("5").daily  # file mất → bản trong code
    finally:
        D._cache["disks"] = None
        D._by_id_fast.clear()


# ---------------------------------------------------------------- kiểm tra an toàn
@pytest.mark.parametrize("bad,msg", [
    ("no front matter", "bắt đầu bằng dòng"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nfoo: 1\n---\n", "Khoá không hợp lệ"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp9\n---\n", "'base'"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nblocks:\n  magic: true\n---\n", "chưa có trong hộp"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp3\nblocks:\n  cvd: true\n---\n", "base: pp4"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nblocks:\n  risk_sizing: true\n---\n", "stop_atr_4h"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nparams:\n  BINANCE_API_KEY: x\n---\n", "không có trong danh sách"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nparams:\n  M3_EMA_TREND_LEN: 20\n---\n", "dùng chung"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nparams:\n  M7_RISK_PCT: 5\n---\n", "tỉ lệ"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nparams:\n  M6_EXIT_MODE: explode\n---\n", "chỉ nhận"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\nparams:\n  M4_REGIME_ENABLED: 1\n---\n", "true/false"),
    ("---\ndisk: 1\nid: 4\nname: x\nbase: pp4\n---\n", "bắt đầu bằng chữ"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\n---\n```python\nimport os\n```\n", "code chạy được"),
    ("---\ndisk: 1\nid: ab\nname: x\nbase: pp4\n---\n<script>alert(1)</script>", "HTML/JavaScript"),
    ("---\ndisk: 1\nid: ab\nname: !!python/object x\nbase: pp4\n---\n", "không được hỗ trợ"),
    ("---\ndisk: 2\nid: ab\nname: x\nbase: pp4\n---\n", "disk: 1"),
])
def test_rejects_bad_disks(bad, msg):
    with pytest.raises(D.DiskError) as e:
        D.parse_disk(bad, source="upload")
    assert msg in str(e.value)


def test_parse_variant_and_markdown_is_escaped():
    d = D.parse_disk(_variant(), source="upload")
    assert d.id == "pp7-risk1" and d.params == {"M7_RISK_PCT": 0.01} and d.stop4h and d.risk_sizing
    html = D.render_markdown_safe("# T\n<img src=x onerror=alert(1)> **b** `c`\n- li")
    assert "<img" not in html and "&lt;img" in html and "<b>b</b>" in html and "<li>li</li>" in html


def test_install_and_remove(tmp_upload):
    d = D.install_disk(_variant())
    assert D.get_disk("pp7-risk1").params == {"M7_RISK_PCT": 0.01} and d.source == "upload"
    with pytest.raises(D.DiskError):
        D.remove_disk("7")  # đĩa có sẵn không xoá được
    D.remove_disk("pp7-risk1")
    assert D.find_disk("pp7-risk1") is None and D.get_disk("pp7-risk1").id == "1"


# ---------------------------------------------------------------- tham số riêng theo luồng
def test_overrides_are_per_thread():
    base = settings.M7_RISK_PCT
    seen = {}
    ready, go = threading.Event(), threading.Event()

    def other():
        ready.set()
        go.wait(2)
        seen["other"] = settings.M7_RISK_PCT

    th = threading.Thread(target=other)
    th.start()
    ready.wait(2)
    with settings.overrides({"M7_RISK_PCT": 0.005}):
        assert settings.M7_RISK_PCT == 0.005 and getattr(settings, "M7_RISK_PCT") == 0.005
        go.set()
        th.join(2)
    assert seen["other"] == base and settings.M7_RISK_PCT == base


# ---------------------------------------------------------------- PP1–PP7 y hệt code cũ
from tests.test_m6_cvd import DF_1M, DF_1D, DF_TAKER  # noqa: E402
from backtest.live_replay import MarketData, run_symbol  # noqa: E402

START = DF_1M.index[60 * 24 * 25]
# Số lệnh + vốn cuối của từng PP do CODE CŨ (trước tái cấu trúc, commit c0fe3cb) chạy trên cùng dữ liệu giả lập,
# chế độ --fast, M4_RSI_SHORT_FLOOR=20 / M4_RSI_LONG_CEIL=80 cho có lệnh PP4+. Đã so thêm toàn bộ từng lệnh trên 9 bộ
# tham số (backtest) và 5 bộ (paper) khi làm PR: khớp 100%.
OLD_RESULTS = {
    "1": (24, 591.485193), "2": (24, 582.752353), "3": (12, 990.228945), "4": (9, 1060.401465),
    "5": (7, 1417.41841), "6": (7, 1013.09841), "6.1": (5, 1207.773936), "7": (8, 1012.300827),
}


def test_all_builtin_disks_reproduce_old_results(monkeypatch):
    monkeypatch.setattr(settings, "M4_RSI_SHORT_FLOOR", 20.0)
    monkeypatch.setattr(settings, "M4_RSI_LONG_CEIL", 80.0)
    slots = run_symbol(MarketData("SYN", DF_1M, strict=False, df_1d=DF_1D, df_taker=DF_TAKER), START,
                       list(OLD_RESULTS), 1000.0, 20.0, 0.3, 15)
    got = {s.method: (len(s.trades), s.balance) for s in slots}
    for m, (n, bal) in OLD_RESULTS.items():
        assert got[m][0] == n and got[m][1] == pytest.approx(bal, rel=1e-7, abs=1e-5), m


def _key(tr):
    return [(x["entry_time"], x["exit_time"], x["side"], round(x["profit"], 9)) for x in tr]


def test_disk_params_equal_global_setting(tmp_upload, monkeypatch):
    """Đĩa ghi tham số riêng = chạy đĩa gốc với tham số đó trong .env; và không làm đổi slot khác chạy cùng lúc."""
    monkeypatch.setattr(settings, "M7_TREND_FILTER", False)
    D.install_disk(_variant())
    md = lambda: MarketData("SYN", DF_1M, strict=False)  # noqa: E731
    s4a, s7v = run_symbol(md(), START, ["4", "pp7-risk1"], 1000.0, 20.0, 0.3, 15)
    assert s7v.trades and s7v.disk.label == "pp7-risk1"
    monkeypatch.setattr(settings, "M7_RISK_PCT", 0.01)
    s4b, s7 = run_symbol(md(), START, ["4", "7"], 1000.0, 20.0, 0.3, 15)
    assert _key(s7v.trades) == _key(s7.trades)
    assert _key(s4a.trades) == _key(s4b.trades)
    assert settings.M7_RISK_PCT == 0.01  # khối with đã trả lại


# ---------------------------------------------------------------- paper cho đĩa
def test_disk_paper_slot_persists(tmp_path, monkeypatch):
    from bot import disk_paper as P
    monkeypatch.setattr(P, "STATE_FILE", tmp_path / "disk_paper.json")
    monkeypatch.setattr(P, "_state", {})
    monkeypatch.setattr(P, "_loaded", False)
    with pytest.raises(ValueError):
        P.start("4")  # Paper 4 có trang riêng
    s = P.start("7", capital=500, leverage=10, wallet_pct=20, symbol="ethusdt")
    assert s["status"] == "running" and s["symbol"] == "ETHUSDT" and s["wallet_pct"] == 0.2 and s["balance"] == 500
    assert "7" in P.active_ids()
    import pandas as pd
    s["open_trade"] = {"side": "LONG", "entry_price": 100.0, "size": 1.0, "margin": 10.0, "notional": 100.0,
                       "capital_before": 500.0, "entry_time": pd.Timestamp("2026-01-01", tz="UTC"), "trading_method": "7",
                       "max_stop_capital_pct": 0.05}
    P.save()
    monkeypatch.setattr(P, "_state", {})
    monkeypatch.setattr(P, "_loaded", False)
    assert P.slot("7")["open_trade"]["entry_time"].year == 2026
    with pytest.raises(ValueError):
        P.reset("7")
    c = P.close_now("7", 110.0)
    assert c["profit"] == pytest.approx(10 - 110 * settings.TAKER_FEE) and P.slot("7")["open_trade"] is None
    P.set_status("7", "stopped")
    assert "7" not in P.active_ids()


# ---------------------------------------------------------------- web
def test_web_pages_and_admin_guard(tmp_upload, monkeypatch, tmp_path):
    from bot import disk_paper as P
    monkeypatch.setattr(P, "STATE_FILE", tmp_path / "disk_paper.json")
    monkeypatch.setattr(P, "_state", {})
    monkeypatch.setattr(P, "_loaded", True)
    from web import app as A
    c = A.app.test_client()
    for url in ("/strategies", "/backtest", "/api/disks", "/api/disks/7", "/api/disks/7/md", "/api/backtests",
                "/api/disks/schema", "/backtest7"):
        assert c.get(url).status_code == 200, url
    assert "Chiến lược" in c.get("/paper4").get_data(as_text=True)  # menu mới trên trang cũ
    assert c.post("/api/disks/upload", json={"text": _variant()}).status_code == 401
    assert c.post("/api/disks/7/paper/start", json={}).status_code == 401
    r = c.post("/api/backtest/run", json={"method": "7", "start_date": "2026-01-01", "params": "M7_RISK_PCT=3"})
    assert r.status_code == 400 and "tỉ lệ" in r.json["error"]
    assert c.post("/api/backtest/run", json={"method": "7", "start_date": "bad"}).status_code == 400
    assert c.post("/api/backtest/run", json={"method": "7", "start_date": "2026-01-01", "symbols": "BTC$"}).status_code == 400
