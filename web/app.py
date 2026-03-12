# -*- coding: utf-8 -*-
"""Flask: trang Paper trade (giống GUI backtest) + API status / paper start-pause-stop."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import csv
import io
from flask import Flask, jsonify, request, render_template, Response
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
    d = get_status()
    # PNL_Open, Capital_Open, Lệnh_Open (real-time khi có lệnh mở)
    open_trade = d.get("paper_open_trade")
    if open_trade:
        try:
            from config import settings
            client = _get_client()
            df = client.get_klines(settings.SYMBOL, "1m", 1)
            current_price = float(df["close"].iloc[-1]) if not df.empty else None
        except Exception:
            current_price = None
        if current_price is not None:
            entry = float(open_trade.get("entry_price") or 0)
            size = float(open_trade.get("size") or 0)
            side = str(open_trade.get("side", "")).upper()
            if side == "LONG":
                pnl_open = (current_price - entry) * size
            else:
                pnl_open = (entry - current_price) * size
            balance = float(d.get("paper_balance") or 0)
            d["paper_pnl_open"] = round(pnl_open, 2)
            d["paper_capital_open"] = round(balance + pnl_open, 2)
        else:
            d["paper_pnl_open"] = 0.0
            d["paper_capital_open"] = float(d.get("paper_balance") or 0)
        d["paper_orders_open_count"] = 1
    else:
        d["paper_pnl_open"] = 0.0
        d["paper_capital_open"] = float(d.get("paper_balance") or 0)
        d["paper_orders_open_count"] = 0
    return jsonify(d)


@app.route("/api/paper/start", methods=["POST"])
def api_paper_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
        capital = float(data.get("initial_capital", 0))
        if capital <= 0:
            return jsonify({"ok": False, "error": "initial_capital phải > 0"}), 400
        from bot import state
        state.paper_start(capital)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
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


@app.route("/api/paper/close", methods=["POST"])
def api_paper_close():
    """Chốt lệnh paper đang mở từ web."""
    try:
        ok, msg, extra = _close_paper_position()
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({"ok": True, "message": msg, **(extra or {})})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/restore-pending")
def api_restore_pending():
    """Sau khi pull/deploy, nếu đã load state có lệnh mở thì frontend hiện popup hỏi giữ/đóng."""
    try:
        from bot.paper_persistence import get_restore_pending
        return jsonify({"pending": get_restore_pending()})
    except Exception:
        return jsonify({"pending": False})


def _close_paper_position():
    """Đóng lệnh paper đang mở (dùng cho api_paper_close và restore-choice). Trả (ok, msg, err)."""
    from bot import state
    from config import settings
    from datetime import datetime, timezone
    open_trade = state.get_paper_open_trade()
    if not open_trade:
        return False, "Không có lệnh nào đang mở.", None
    balance = state.get_paper_balance()
    entry = float(open_trade["entry_price"])
    side = str(open_trade["side"]).upper()
    size = float(open_trade["size"])
    try:
        client = _get_client()
        df = client.get_klines(settings.SYMBOL, "1m", 1)
        exit_px = float(df["close"].iloc[-1]) if not df.empty else entry
    except Exception:
        exit_px = entry
    if side == "LONG":
        pnl = (exit_px - entry) * size
    else:
        pnl = (entry - exit_px) * size
    fee_out = size * exit_px * getattr(settings, "TAKER_FEE", 0.0004)
    pnl_net = pnl - fee_out
    capital_after = balance + pnl_net
    exit_rsi = exit_ema_rsi = exit_wma_rsi = None
    try:
        from strategy.indicators import add_indicators
        df_4h = _get_client().get_klines(settings.SYMBOL, "4h", 5)
        if not df_4h.empty:
            df_4h = add_indicators(df_4h)
            r = df_4h.iloc[-1]
            def _f(v):
                try:
                    x = float(v)
                    return x if (x == x) else None
                except (TypeError, ValueError):
                    return None
            exit_rsi, exit_ema_rsi, exit_wma_rsi = _f(r.get("RSI")), _f(r.get("EMA_RSI")), _f(r.get("WMA_RSI"))
    except Exception:
        pass
    closed = {
        "entry_time": open_trade.get("entry_time"),
        "exit_time": datetime.now(timezone.utc),
        "entry_price": entry,
        "exit_price": exit_px,
        "side": side,
        "profit": pnl_net,
        "capital_before": balance,
        "capital_after": capital_after,
        "exit_reason": "MANUAL_WEB",
        "entry_rsi": open_trade.get("entry_rsi"),
        "entry_ema_rsi": open_trade.get("entry_ema_rsi"),
        "entry_wma_rsi": open_trade.get("entry_wma_rsi"),
        "exit_rsi": exit_rsi,
        "exit_ema_rsi": exit_ema_rsi,
        "exit_wma_rsi": exit_wma_rsi,
    }
    state.set_paper_open_trade(None)
    state.set_paper_last_trade(closed)
    state.append_paper_trade(closed)
    state.set_paper_balance(capital_after)
    return True, "Đã chốt lệnh.", {"pnl": round(pnl_net, 2), "capital_after": round(capital_after, 2)}


@app.route("/api/restore-choice", methods=["POST"])
def api_restore_choice():
    """User chọn: giữ vị thế cũ (keep=true) hoặc đóng lệnh (keep=false)."""
    try:
        from bot.paper_persistence import get_restore_pending, clear_restore_pending
        data = request.get_json(force=True, silent=True) or {}
        keep = data.get("keep", True)
        if not get_restore_pending():
            return jsonify({"ok": True, "message": "Không có lựa chọn đang chờ."})
        if keep:
            clear_restore_pending()
            return jsonify({"ok": True, "message": "Đã giữ vị thế paper trade."})
        ok, msg, extra = _close_paper_position()
        clear_restore_pending()
        if ok:
            try:
                from bot.paper_persistence import save_paper_state
                save_paper_state()
            except Exception:
                pass
            return jsonify({"ok": True, "message": msg, **(extra or {})})
        return jsonify({"ok": False, "error": msg}), 400
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
                "volume": round(float(row.get("volume", 0)), 0),
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
            notional = entry * size if entry and size else 1
            pct_pnl_open = round((pnl / notional * 100), 2) if notional else 0
            orders.append({
                "id": "open",
                "side": side,
                "entry_time": open_trade.get("entry_time"),
                "entry_price": entry,
                "exit_time": None,
                "exit_price": None,
                "pnl": round(pnl, 2),
                "pct_pnl": pct_pnl_open,
                "capital_after": None,
                "is_open": True,
                "symbol": settings.SYMBOL,
                "exit_reason": None,
            })
        for i, t in enumerate(reversed(trades)):
            profit = float(t.get("profit", 0))
            cap_before = float(t.get("capital_before") or 0)
            cap_after = t.get("capital_after")
            if cap_after is not None:
                cap_after = round(float(cap_after), 2)
            pct_pnl = round((profit / cap_before * 100), 2) if cap_before else 0
            orders.append({
                "id": len(orders) + 1,
                "side": str(t.get("side", "")).upper(),
                "entry_time": t.get("entry_time"),
                "entry_price": t.get("entry_price"),
                "exit_time": t.get("exit_time"),
                "exit_price": t.get("exit_price"),
                "pnl": round(profit, 2),
                "pct_pnl": pct_pnl,
                "capital_after": cap_after,
                "is_open": False,
                "symbol": settings.SYMBOL,
                "exit_reason": t.get("exit_reason"),
            })
        return jsonify({"orders": orders})
    except Exception as e:
        return jsonify({"orders": [], "error": str(e)})


def _orders_for_csv():
    """Danh sách lệnh đầy đủ (kể cả 3 đường lúc vào/thoát) để xuất CSV."""
    from bot import state
    from config import settings
    status = get_status()
    if status.get("error"):
        return [], None
    open_trade = status.get("paper_open_trade")
    trades = list(status.get("paper_trades") or [])
    symbol = getattr(settings, "SYMBOL", "BTCUSDT")

    def _ts(v):
        if v is None:
            return ""
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    def _n(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        return v

    rows = []
    if open_trade:
        entry = float(open_trade.get("entry_price") or 0)
        side = str(open_trade.get("side", "")).upper()
        rows.append({
            "id": "open",
            "symbol": symbol,
            "side": side,
            "entry_time": _ts(open_trade.get("entry_time")),
            "entry_price": entry,
            "exit_time": "",
            "exit_price": "",
            "profit": "",
            "pct_pnl": "",
            "capital_after": "",
            "exit_reason": "",
            "entry_rsi": _n(open_trade.get("entry_rsi")),
            "entry_ema_rsi": _n(open_trade.get("entry_ema_rsi")),
            "entry_wma_rsi": _n(open_trade.get("entry_wma_rsi")),
            "exit_rsi": "",
            "exit_ema_rsi": "",
            "exit_wma_rsi": "",
        })
    for i, t in enumerate(reversed(trades)):
        profit = float(t.get("profit", 0))
        cap_before = float(t.get("capital_before") or 0)
        cap_after = t.get("capital_after")
        if cap_after is not None:
            cap_after = round(float(cap_after), 2)
        pct_pnl = round((profit / cap_before * 100), 2) if cap_before else 0
        rows.append({
            "id": len(rows) + 1,
            "symbol": symbol,
            "side": str(t.get("side", "")).upper(),
            "entry_time": _ts(t.get("entry_time")),
            "entry_price": t.get("entry_price"),
            "exit_time": _ts(t.get("exit_time")),
            "exit_price": t.get("exit_price"),
            "profit": round(profit, 2),
            "pct_pnl": pct_pnl,
            "capital_after": cap_after if cap_after is not None else "",
            "exit_reason": t.get("exit_reason") or "",
            "entry_rsi": _n(t.get("entry_rsi")),
            "entry_ema_rsi": _n(t.get("entry_ema_rsi")),
            "entry_wma_rsi": _n(t.get("entry_wma_rsi")),
            "exit_rsi": _n(t.get("exit_rsi")),
            "exit_ema_rsi": _n(t.get("exit_ema_rsi")),
            "exit_wma_rsi": _n(t.get("exit_wma_rsi")),
        })
    return rows, symbol


@app.route("/api/export/csv")
def api_export_csv():
    """Xuất toàn bộ list lệnh + 3 đường (RSI, EMA_RSI, WMA_RSI) lúc vào và thoát dạng CSV."""
    try:
        rows, symbol = _orders_for_csv()
        buf = io.StringIO()
        if not rows:
            buf.write("id,symbol,side,entry_time,entry_price,exit_time,exit_price,profit,pct_pnl,capital_after,exit_reason,entry_rsi,entry_ema_rsi,entry_wma_rsi,exit_rsi,exit_ema_rsi,exit_wma_rsi\n")
        else:
            cols = list(rows[0].keys())
            w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        filename = f"orders_{symbol}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        return Response(f"Lỗi: {e}", status=500, mimetype="text/plain")


def run_web(host=None, port=None):
    from config import settings
    app.run(host=host or settings.WEB_HOST, port=port or settings.WEB_PORT, threaded=True, use_reloader=False)
