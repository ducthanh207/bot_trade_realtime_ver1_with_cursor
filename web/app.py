# -*- coding: utf-8 -*-
"""Flask: trang Paper trade (giống GUI backtest) + API status / paper start-pause-stop."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flask import Flask, jsonify, request, render_template
from datetime import datetime

_web_dir = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(_web_dir / "templates"))


def _serialize(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def get_status():
    try:
        from bot import state
        d = state.to_status_dict()
        d["bot_started_at"] = str(d["bot_started_at"]) if d.get("bot_started_at") else None
        d["paper_started_at"] = str(d["paper_started_at"]) if d.get("paper_started_at") else None
        if d.get("paper_last_trade"):
            d["paper_last_trade"] = _serialize(d["paper_last_trade"])
        if d.get("paper_open_trade"):
            d["paper_open_trade"] = _serialize(d["paper_open_trade"])
        d["paper_trades"] = _serialize(d.get("paper_trades", []))
        if d.get("last_trade"):
            d["last_trade"] = _serialize(d["last_trade"])
        return d
    except Exception as e:
        return {"error": str(e)}


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(get_status())


@app.route("/api/paper/start", methods=["POST"])
def api_paper_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
        capital = float(data.get("initial_capital", 0))
        if capital <= 0:
            return jsonify({"ok": False, "error": "initial_capital phải > 0"}), 400
        from bot import state
        state.paper_start(capital)
        return jsonify({"ok": True, "message": "Đã kích hoạt paper trade."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper/pause", methods=["POST"])
def api_paper_pause():
    try:
        from bot import state
        state.paper_pause()
        return jsonify({"ok": True, "message": "Đã tạm dừng."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper/stop", methods=["POST"])
def api_paper_stop():
    try:
        from bot import state
        state.paper_stop()
        return jsonify({"ok": True, "message": "Đã dừng paper trade."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


def _get_client():
    from exchange.binance_client import BinanceClient
    return BinanceClient()


@app.route("/api/price")
def api_price():
    """Giá đóng cửa mới nhất (để tính unrealized PnL)."""
    try:
        from config import settings
        client = _get_client()
        df = client.get_klines(settings.SYMBOL, "1m", 1)
        if df.empty:
            return jsonify({"price": 0.0})
        price = float(df["close"].iloc[-1])
        return jsonify({"price": price, "symbol": settings.SYMBOL})
    except Exception as e:
        return jsonify({"price": 0.0, "error": str(e)})


@app.route("/api/klines")
def api_klines():
    """Klines + indicators theo interval. interval: 1m, 5m, 15m, 1h, 4h, 1d, 3d."""
    try:
        from config import settings
        from strategy.indicators import add_indicators
        interval = request.args.get("interval", "5m").strip().lower()
        limit = min(int(request.args.get("limit", 500)), 1000)
        if interval not in ("1m", "5m", "15m", "1h", "4h", "1d", "3d"):
            interval = "5m"
        client = _get_client()
        df = client.get_klines(settings.SYMBOL, interval, limit)
        if df.empty:
            return jsonify({"ohlc": [], "indicators": {}, "interval": interval})
        df = add_indicators(df)
        ohlc = []
        for ts, row in df.iterrows():
            t = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            ohlc.append({
                "time": t,
                "open": round(float(row["open"]), 4),
                "high": round(float(row["high"]), 4),
                "low": round(float(row["low"]), 4),
                "close": round(float(row["close"]), 4),
            })
        indicators = {
            "RSI": [round(float(row["RSI"]), 2) for _, row in df.iterrows()],
            "EMA_RSI": [round(float(row["EMA_RSI"]), 2) for _, row in df.iterrows()],
            "WMA_RSI": [round(float(row["WMA_RSI"]), 2) for _, row in df.iterrows()],
            "ATR": [round(float(row["ATR"]), 4) for _, row in df.iterrows()],
            "EMA": [round(float(row["EMA"]), 4) for _, row in df.iterrows()],
            "WMA": [round(float(row["WMA"]), 4) for _, row in df.iterrows()],
            "times": [ts.isoformat() if hasattr(ts, "isoformat") else str(ts) for ts in df.index],
        }
        return jsonify({"ohlc": ohlc, "indicators": indicators, "interval": interval, "symbol": settings.SYMBOL})
    except Exception as e:
        return jsonify({"ohlc": [], "indicators": {}, "error": str(e)})


@app.route("/api/orders")
def api_orders():
    """Danh sách lệnh (mở + đã đóng), mới nhất lên đầu; mỗi lệnh có pnl (realized hoặc unrealized)."""
    try:
        from bot import state
        from config import settings
        status = get_status()
        if status.get("error"):
            return jsonify({"orders": [], "error": status["error"]})
        open_trade = status.get("paper_open_trade")
        trades = list(status.get("paper_trades") or [])
        current_price = None
        if open_trade:
            try:
                client = _get_client()
                df = client.get_klines(settings.SYMBOL, "1m", 1)
                if not df.empty:
                    current_price = float(df["close"].iloc[-1])
            except Exception:
                pass
        orders = []
        if open_trade:
            entry = float(open_trade.get("entry_price") or 0)
            side = str(open_trade.get("side", "")).upper()
            size = float(open_trade.get("size") or 0)
            if current_price and entry and size:
                if side == "LONG":
                    pnl = (current_price - entry) * size
                else:
                    pnl = (entry - current_price) * size
            else:
                pnl = 0.0
            orders.append({
                "id": "open",
                "side": side,
                "entry_time": open_trade.get("entry_time"),
                "entry_price": entry,
                "exit_time": None,
                "exit_price": None,
                "pnl": round(pnl, 2),
                "is_open": True,
                "symbol": settings.SYMBOL,
            })
        for t in reversed(trades):
            profit = float(t.get("profit", 0))
            orders.append({
                "id": len(orders),
                "side": str(t.get("side", "")).upper(),
                "entry_time": t.get("entry_time"),
                "entry_price": t.get("entry_price"),
                "exit_time": t.get("exit_time"),
                "exit_price": t.get("exit_price"),
                "pnl": round(profit, 2),
                "is_open": False,
                "symbol": settings.SYMBOL,
                "exit_reason": t.get("exit_reason"),
            })
        return jsonify({"orders": orders})
    except Exception as e:
        return jsonify({"orders": [], "error": str(e)})


def run_web(host=None, port=None):
    from config import settings
    app.run(host=host or settings.WEB_HOST, port=port or settings.WEB_PORT, threaded=True, use_reloader=False)
