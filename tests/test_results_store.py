# -*- coding: utf-8 -*-
"""[2026-11-22] Lịch sử backtest: index có profit factor / chuỗi thua, kết quả cũ được bổ sung khi đọc."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtest import results_store as rs

RES = {"method": "4", "symbol": "BTCUSDT", "start": "2026-01-01", "end": "2026-02-01",
       "initial_capital": 1000, "final_balance": 1030, "total_trades": 4, "winrate": 50, "max_drawdown_pct": 3.1,
       "trades": [{"profit": 30, "fee_in": 0}, {"profit": -5, "fee_in": 0}, {"profit": -4, "fee_in": 1},
                  {"profit": 15, "fee_in": 1}]}


def test_trade_metrics():
    m = rs.trade_metrics(RES)
    assert m["profit_factor"] == round(44 / 10, 2)
    assert m["max_loss_streak"] == 2
    assert m["total_pnl"] == 30
    assert rs.trade_metrics({"trades": [{"profit": 5}]})["profit_factor"] is None


def test_save_and_backfill_old_index(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DIR", tmp_path)
    monkeypatch.setattr(rs, "INDEX", tmp_path / "index.json")
    rs.save("aaaaaaaa", {"method": "4"}, RES)
    m = rs.listing()[0]
    assert m["profit_factor"] == 4.4 and m["max_loss_streak"] == 2
    # giả lập index cũ (trước khi có các cột mới)
    old = [{k: v for k, v in m.items() if k not in ("profit_factor", "max_loss_streak", "total_pnl")},
           {"id": "bbbbbbbb", "method": "4"}]  # file kết quả đã mất
    (tmp_path / "index.json").write_text(json.dumps(old), encoding="utf-8")
    got = rs.listing()
    assert got[0]["max_loss_streak"] == 2 and got[0]["total_pnl"] == 30
    assert got[1]["max_loss_streak"] is None
    assert "max_loss_streak" in json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))[0]
