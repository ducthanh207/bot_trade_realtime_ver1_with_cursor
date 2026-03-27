# -*- coding: utf-8 -*-
"""
Standalone demo API for "% change avg" bands.

This file lives in idea_for_update and does not touch production web/app.py.
"""

import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

# Make project root importable: config/, exchange/, strategy/
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from config import settings  # noqa: E402
from exchange.binance_client import BinanceClient  # noqa: E402
from strategy.indicators import add_indicators  # noqa: E402

from pct_change_avg_logic import build_pct_change_avg_bands  # noqa: E402

app = Flask(__name__)

ALLOWED_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d", "3d"}


def _time_to_str(ts):
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def _float_or_none(v):
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


@app.route("/api/pct-change-avg")
def api_pct_change_avg():
    """
    Returns:
    - OHLC + indicators (same style as current dashboard API)
    - pct_change_avg bands result for chart overlay
    """
    interval = (request.args.get("interval", "5m") or "5m").strip().lower()
    if interval not in ALLOWED_INTERVALS:
        interval = "5m"

    try:
        limit = int(request.args.get("limit", 500))
    except (TypeError, ValueError):
        limit = 500
    limit = min(max(limit, 120), 1000)

    try:
        lookback_trades = int(request.args.get("lookback_trades", 15))
    except (TypeError, ValueError):
        lookback_trades = 15
    lookback_trades = min(max(lookback_trades, 1), 200)

    symbol = (request.args.get("symbol") or settings.SYMBOL or "BTCUSDT").upper()

    client = BinanceClient()
    raw = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    if raw.empty:
        return jsonify(
            {
                "symbol": symbol,
                "interval": interval,
                "lookback_trades": lookback_trades,
                "ohlc": [],
                "indicators": {},
                "pct_change_avg": {
                    "trade_count": 0,
                    "avg_signed_pct": 0.0,
                    "avg_abs_pct": 0.0,
                    "current_close": None,
                    "upper": None,
                    "mid": None,
                    "lower": None,
                    "lines": {"upper": [], "mid": [], "lower": []},
                },
            }
        )

    df = add_indicators(raw)
    if df.empty:
        return jsonify(
            {
                "symbol": symbol,
                "interval": interval,
                "lookback_trades": lookback_trades,
                "ohlc": [],
                "indicators": {},
                "pct_change_avg": {
                    "trade_count": 0,
                    "avg_signed_pct": 0.0,
                    "avg_abs_pct": 0.0,
                    "current_close": None,
                    "upper": None,
                    "mid": None,
                    "lower": None,
                    "lines": {"upper": [], "mid": [], "lower": []},
                },
            }
        )

    ohlc = []
    for ts, row in df.iterrows():
        ohlc.append(
            {
                "time": _time_to_str(ts),
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
                "volume": round(float(row.get("volume", 0.0)), 0),
            }
        )

    indicators = {
        "RSI": [round(float(row["RSI"]), 2) for _, row in df.iterrows()],
        "EMA_RSI": [round(float(row["EMA_RSI"]), 2) for _, row in df.iterrows()],
        "WMA_RSI": [round(float(row["WMA_RSI"]), 2) for _, row in df.iterrows()],
        "EMA": [round(float(row["EMA"]), 4) for _, row in df.iterrows()],
        "times": [_time_to_str(ts) for ts in df.index],
    }

    bands = build_pct_change_avg_bands(df[["open", "high", "low", "close", "volume"]], lookback_trades=lookback_trades)

    # JSON-safe conversion for timestamps in trades + line series
    trades = []
    for t in bands.get("trades", []):
        trades.append(
            {
                "side": t.get("side"),
                "entry_time": _time_to_str(t.get("entry_time")),
                "exit_time": _time_to_str(t.get("exit_time")),
                "entry_open": _float_or_none(t.get("entry_open")),
                "exit_close": _float_or_none(t.get("exit_close")),
                "pct_change": _float_or_none(t.get("pct_change")),
            }
        )

    def _line_to_json(line):
        return [{"time": _time_to_str(x.get("time")), "value": _float_or_none(x.get("value"))} for x in line]

    pct_block = {
        "trade_count": int(bands.get("trade_count", 0)),
        "avg_signed_pct": _float_or_none(bands.get("avg_signed_pct")),
        "avg_abs_pct": _float_or_none(bands.get("avg_abs_pct")),
        "current_close": _float_or_none(bands.get("current_close")),
        "upper": _float_or_none(bands.get("upper")),
        "mid": _float_or_none(bands.get("mid")),
        "lower": _float_or_none(bands.get("lower")),
        "lines": {
            "upper": _line_to_json((bands.get("lines") or {}).get("upper", [])),
            "mid": _line_to_json((bands.get("lines") or {}).get("mid", [])),
            "lower": _line_to_json((bands.get("lines") or {}).get("lower", [])),
        },
        "trades": trades,
    }

    return jsonify(
        {
            "symbol": symbol,
            "interval": interval,
            "lookback_trades": lookback_trades,
            "ohlc": ohlc,
            "indicators": indicators,
            "pct_change_avg": pct_block,
        }
    )


@app.route("/api/health")
def api_health():
    return jsonify({"status": "ok"})


@app.route("/")
def index():
    return send_from_directory(Path(__file__).resolve().parent, "dashboard_demo.html")


@app.route("/overlay_pct_change_avg_demo.js")
def js_overlay():
    return send_from_directory(Path(__file__).resolve().parent, "overlay_pct_change_avg_demo.js")


if __name__ == "__main__":
    # Demo server only
    app.run(host="127.0.0.1", port=5055, debug=False)
