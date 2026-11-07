# -*- coding: utf-8 -*-
"""
[2026-11-01] Backtest cho nút "Chạy backtest" trên web (Paper 1–4), dùng CHUNG engine với backtest/live_replay.py.

Trước đây web dùng bot/paper3_backtest.py (chỉ PP3/PP4) — một vòng lặp riêng, khác live ở nhiều chỗ:
- quét stop trên nến 1H thay vì nến 1m, giá vào = giá đóng nến 4H;
- tính chỉ báo trên toàn bộ dữ liệu một lần và đọc cả nến 1H/4H chưa đóng tại thời điểm xét (nhìn trước tương lai);
- tải cả nến đang chạy → chạy lại cùng khoảng ngày ở hai thời điểm khác nhau ra kết quả khác nhau.

Giờ web gọi live_replay.run_symbol (strict, không nhìn trước): phát lại từng phút với đúng hàm chiến lược của bot
(bot/slot_engine.step_slot dùng các hàm này), mọi tham số lấy từ config/settings.py + .env giống bot đang chạy.
Chỉ dùng nến 1m ĐÃ ĐÓNG và cache theo tháng (backtest/data_cache) → cùng khoảng ngày luôn ra cùng kết quả.

Chạy trong process Python riêng (subprocess, không chiếm GIL của vòng lặp bot) và bất đồng bộ (POST tạo job, GET hỏi kết quả)
để không bị nginx cắt request dài.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

WARMUP_DAYS = 40  # live đọc 200 nến 4H (~34 ngày) → cần ít nhất chừng đó dữ liệu trước ngày bắt đầu
MAX_DAYS = 400


def _jsonable(v):
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    if isinstance(v, (float, np.floating)):
        return round(float(v), 6)
    if isinstance(v, np.integer):
        return int(v)
    return v


def run_web_backtest(method: str, symbol: str, start: str, end: str | None, initial_capital: float,
                     leverage: float, wallet_pct: float, lookback_trades: int = 15) -> dict:
    """Chạy trong process con. start/end: 'YYYY-MM-DD' theo giờ VN; end tính hết ngày đó (tối đa tới phút đã đóng gần nhất)."""
    from backtest import binance_data
    from backtest.live_replay import MarketData, run_symbol

    tz7 = timezone(timedelta(hours=7))
    start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=tz7)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    end_dt = (datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=tz7) + timedelta(days=1)) if end else now
    end_dt = min(end_dt.astimezone(timezone.utc), now)
    start_dt = start_dt.astimezone(timezone.utc)
    if end_dt <= start_dt:
        return {"error": "Khoảng thời gian không hợp lệ"}
    if (end_dt - start_dt).days > MAX_DAYS:
        return {"error": f"Tối đa {MAX_DAYS} ngày mỗi lần chạy"}

    df_1m = binance_data.load_1m(symbol, start_dt - timedelta(days=WARMUP_DAYS), end_dt, log=lambda *a: None)
    if df_1m is None or len(df_1m) < 60 * 24 * 7:
        return {"error": "Không đủ dữ liệu nến 1m từ Binance"}
    df_1d = None
    if str(method) == "5":  # [2026-11-07] PP5 cần nến ngày dài (EMA + %change trên 1D)
        from config import settings as _cfg
        try:
            binance_data.download_1d(symbol, start_dt - timedelta(days=int(_cfg.M5_DAILY_KLINES) + 30), end_dt,
                                     log=lambda *a: None)
        except Exception:
            pass
        df_1d = binance_data.load_1d(symbol, end_dt)
        if df_1d.empty:
            df_1d = binance_data.resample_ohlcv(df_1m, "24h")
    md = MarketData(symbol, df_1m, strict=True, df_1d=df_1d)
    slot = run_symbol(md, pd.Timestamp(start_dt), [str(method)], float(initial_capital),
                      float(leverage), float(wallet_pct), int(lookback_trades))[0]

    trades = [{k: _jsonable(v) for k, v in t.items()} for t in slot.trades]
    wins = sum(1 for t in slot.trades if t["profit"] > 0)
    n = len(slot.trades)
    reasons = {}
    for t in slot.trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    peak, max_dd = float(initial_capital), 0.0
    for t in slot.trades:
        peak = max(peak, t["capital_after"])
        if peak > 0:
            max_dd = max(max_dd, (peak - t["capital_after"]) / peak * 100)
    return {
        "symbol": symbol,
        "method": str(method),
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "data_last_candle": df_1m.index[-1].isoformat(),
        "total_trades": n,
        "wins": wins,
        "losses": n - wins,
        "winrate": round(wins / n * 100, 1) if n else 0.0,
        "total_pnl": round(float(slot.balance) - float(initial_capital), 4),
        "initial_capital": float(initial_capital),
        "final_balance": round(float(slot.balance), 4),
        "max_drawdown_pct": round(max_dd, 2),
        "exit_reasons": reasons,
        "trades": trades,
    }


# ---------------------------------------------------------------- job bất đồng bộ (trong process web)
# Mỗi job chạy bằng một process Python riêng (subprocess) → không chiếm CPU/GIL của vòng lặp bot,
# và không import lại run_live.py (multiprocessing "spawn" sẽ làm vậy). Mỗi lúc chỉ 1 job chạy, các job sau xếp hàng.
_jobs: dict = {}
_lock = threading.Lock()
_run_lock = threading.Lock()
JOB_TTL_SEC = 3600
JOB_TIMEOUT_SEC = 1800
ROOT = Path(__file__).resolve().parents[1]


def _run_job(job_id: str, kwargs: dict):
    job = _jobs[job_id]
    with _run_lock:
        job["started"] = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), json.dumps(kwargs)],
                cwd=str(ROOT), capture_output=True, text=True, timeout=JOB_TIMEOUT_SEC,
            )
            lines = [ln for ln in proc.stdout.splitlines() if ln.startswith(RESULT_PREFIX)]
            if lines:
                job["result"] = json.loads(lines[-1][len(RESULT_PREFIX):])
            else:
                job["result"] = {"error": "Backtest lỗi", "detail": (proc.stderr or proc.stdout)[-3000:]}
        except subprocess.TimeoutExpired:
            job["result"] = {"error": f"Quá {JOB_TIMEOUT_SEC // 60} phút, đã dừng"}
        except Exception as e:
            job["result"] = {"error": str(e), "detail": traceback.format_exc()}


def submit(**kwargs) -> str:
    with _lock:
        now = time.time()
        for k in [k for k, j in _jobs.items() if now - j["created"] > JOB_TTL_SEC and "result" in j]:
            _jobs.pop(k, None)
        job_id = uuid.uuid4().hex[:12]
        _jobs[job_id] = {"created": now, "params": kwargs}
    threading.Thread(target=_run_job, args=(job_id, kwargs), daemon=True).start()
    return job_id


def status(job_id: str) -> dict:
    j = _jobs.get(job_id)
    if j is None:
        return {"state": "unknown", "error": "Không tìm thấy job (có thể bot đã khởi động lại)"}
    if "result" not in j:
        waiting = "started" not in j
        return {"state": "running", "queued": waiting, "elapsed_sec": round(time.time() - j["created"])}
    out = dict(j["result"])
    out["state"] = "done"
    return out


RESULT_PREFIX = "@@WEB_BACKTEST_RESULT@@"

if __name__ == "__main__":
    # Process con: python backtest/web_backtest.py '<json kwargs>' → in một dòng kết quả JSON
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    try:
        res = run_web_backtest(**json.loads(sys.argv[1]))
    except Exception as e:
        res = {"error": str(e), "detail": traceback.format_exc()[-3000:]}
    print(RESULT_PREFIX + json.dumps(res, ensure_ascii=False, default=str))
