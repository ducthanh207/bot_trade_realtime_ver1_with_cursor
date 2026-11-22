# -*- coding: utf-8 -*-
"""
[2026-11-21] Lưu mọi kết quả backtest chạy trên web để xem lại / tải Excel sau (kể cả sau khi bot khởi động lại).

data/backtests/<job_id>.json  — kết quả đầy đủ (thống kê + danh sách lệnh)
data/backtests/index.json     — danh sách ngắn để hiện lịch sử (mới nhất trước)
Giữ tối đa MAX_KEEP kết quả, cũ hơn tự xoá. data/ không đưa lên git.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "backtests"
INDEX = DIR / "index.json"
MAX_KEEP = 300
_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")
_lock = threading.Lock()


def _atomic_write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_index() -> list:
    try:
        v = json.loads(INDEX.read_text(encoding="utf-8"))
        return v if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def trade_metrics(res: dict) -> dict:
    """[2026-11-22] Profit factor + chuỗi thua dài nhất + lời/lỗ USDT, tính giống popup kết quả (lãi ròng = profit - fee_in)."""
    net = [float(t.get("profit") or 0) - float(t.get("fee_in") or 0) for t in (res.get("trades") or [])]
    win = sum(x for x in net if x > 0)
    loss = -sum(x for x in net if x <= 0)
    streak = cur = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    cap0 = float(res.get("initial_capital") or 0)
    fin = float(res.get("final_balance") or 0)
    return {"profit_factor": round(win / loss, 2) if loss > 0 else None,
            "max_loss_streak": streak, "total_pnl": round(fin - cap0, 2)}


def meta_of(job_id: str, params: dict, res: dict) -> dict:
    cap0 = float(res.get("initial_capital") or 0)
    fin = float(res.get("final_balance") or 0)
    return {
        "id": job_id, "saved_at": time.time(), "batch": str(params.get("batch") or "")[:40],
        "method": str(res.get("method") or params.get("method")), "label": res.get("label"),
        "disk_name": res.get("disk_name"), "symbol": res.get("symbol"),
        "start": res.get("start"), "end": res.get("end"),
        "initial_capital": cap0, "final_balance": fin,
        "return_pct": round((fin / cap0 - 1) * 100, 2) if cap0 else None,
        "max_drawdown_pct": res.get("max_drawdown_pct"), "total_trades": res.get("total_trades"),
        "winrate": res.get("winrate"), "overrides": res.get("overrides") or {},
        "leverage": params.get("leverage"), "wallet_pct": params.get("wallet_pct"),
        "elapsed_sec": res.get("elapsed_sec"),
        **trade_metrics(res),
    }


def save(job_id: str, params: dict, res: dict):
    if not _ID_RE.match(job_id) or not res or res.get("error"):
        return
    with _lock:
        _atomic_write(DIR / f"{job_id}.json", json.dumps(res, ensure_ascii=False, default=str))
        idx = [m for m in _read_index() if m.get("id") != job_id]
        idx.insert(0, meta_of(job_id, params, res))
        for old in idx[MAX_KEEP:]:
            try:
                (DIR / f"{old['id']}.json").unlink(missing_ok=True)
            except OSError:
                pass
        _atomic_write(INDEX, json.dumps(idx[:MAX_KEEP], ensure_ascii=False, default=str))


def load(job_id: str):
    if not _ID_RE.match(str(job_id)):
        return None
    try:
        return json.loads((DIR / f"{job_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _backfill(idx: list) -> bool:
    """Kết quả lưu trước 2026-11-22 chưa có profit factor / chuỗi thua trong index: đọc file đầy đủ một lần rồi ghi bổ sung."""
    changed = False
    for m in idx:
        if "max_loss_streak" in m:
            continue
        res = load(str(m.get("id")))
        m.update(trade_metrics(res) if res else {"profit_factor": None, "max_loss_streak": None, "total_pnl": None})
        changed = True
    return changed


def listing(limit: int = 100) -> list:
    idx = _read_index()
    if any("max_loss_streak" not in m for m in idx):
        with _lock:
            idx = _read_index()
            if _backfill(idx):
                _atomic_write(INDEX, json.dumps(idx, ensure_ascii=False, default=str))
    return idx[: max(1, min(int(limit), MAX_KEEP))]


def delete(job_id: str) -> bool:
    if not _ID_RE.match(str(job_id)):
        return False
    with _lock:
        idx = _read_index()
        new = [m for m in idx if m.get("id") != job_id]
        (DIR / f"{job_id}.json").unlink(missing_ok=True)
        _atomic_write(INDEX, json.dumps(new, ensure_ascii=False, default=str))
        return len(new) != len(idx)


def cache_overview() -> list:
    """Nến đã tải sẵn trên máy (backtest/data_cache): cặp, tháng 1m đầu/cuối, có 1D / taker 1H không."""
    from backtest.binance_data import CACHE_DIR
    out = []
    if not CACHE_DIR.is_dir():
        return out
    for d in sorted(p for p in CACHE_DIR.iterdir() if p.is_dir()):
        months = sorted(f.name[3:10] for f in d.glob("1m-*.csv.gz"))
        if not months:
            continue
        size = sum(f.stat().st_size for f in d.iterdir() if f.is_file())
        out.append({"symbol": d.name, "from": months[0], "to": months[-1], "months": len(months),
                    "daily": (d / "1d.csv.gz").exists(), "taker": (d / "1h_taker.csv.gz").exists(),
                    "mb": round(size / 1e6, 1)})
    return out
