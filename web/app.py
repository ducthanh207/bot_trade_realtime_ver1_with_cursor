# -*- coding: utf-8 -*-
"""Flask: trang Paper trade (giống GUI backtest) + API status / paper start-pause-stop."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import csv
import io
from flask import Flask, jsonify, request, render_template, Response, redirect, url_for

from bot.paper_ledger_audit import (
    infer_initial_capital as _infer_initial_capital,
    paper_ledger_meta as _paper_ledger_meta,
    reconcile_trades as _reconcile_trades,
    trade_key_closed as _trade_key_closed,
)
from datetime import datetime, timezone
try:
    from config import settings as _app_settings
    _tz_app = getattr(_app_settings, "GMT7", timezone.utc)
except Exception:
    _tz_app = timezone.utc

_web_dir = Path(__file__).resolve().parent
app = Flask(
    __name__,
    template_folder=str(_web_dir / "templates"),
    static_folder=str(_web_dir / "static"),
    static_url_path="/static",
)


def _serialize(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(x) for x in obj]
    return obj


def _float_or_none_api(v):
    try:
        x = float(v)
        if x != x:
            return None
        return x
    except (TypeError, ValueError):
        return None


def _pct_change_bands_to_json(bands):
    """Chuẩn hóa kết quả build_pct_change_avg_bands cho JSON (giống idea_for_update/api_demo)."""
    trades = []
    for t in bands.get("trades", []) or []:
        trades.append(
            {
                "side": t.get("side"),
                "entry_time": _serialize(t.get("entry_time")),
                "exit_time": _serialize(t.get("exit_time")),
                "entry_open": _float_or_none_api(t.get("entry_open")),
                "exit_close": _float_or_none_api(t.get("exit_close")),
                "pct_change": _float_or_none_api(t.get("pct_change")),
            }
        )

    def _line_to_json(line):
        out = []
        for x in line or []:
            out.append(
                {
                    "time": _serialize(x.get("time")),
                    "value": _float_or_none_api(x.get("value")),
                }
            )
        return out

    lines = bands.get("lines") or {}
    return {
        "trade_count": int(bands.get("trade_count", 0)),
        "avg_signed_pct": _float_or_none_api(bands.get("avg_signed_pct")),
        "avg_abs_pct": _float_or_none_api(bands.get("avg_abs_pct")),
        "band_half_width_pct": _float_or_none_api(bands.get("band_half_width_pct")),
        "band_half_width_usdt": _float_or_none_api(bands.get("band_half_width_usdt")),
        "current_close": _float_or_none_api(bands.get("current_close")),
        "upper": _float_or_none_api(bands.get("upper")),
        "mid": _float_or_none_api(bands.get("mid")),
        "lower": _float_or_none_api(bands.get("lower")),
        "lines": {
            "upper": _line_to_json(lines.get("upper", [])),
            "mid": _line_to_json(lines.get("mid", [])),
            "lower": _line_to_json(lines.get("lower", [])),
        },
        "trades": trades,
    }


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
        d["paper2_started_at"] = str(d["paper2_started_at"]) if d.get("paper2_started_at") else None
        if d.get("paper2_last_trade"):
            d["paper2_last_trade"] = _serialize(d["paper2_last_trade"])
        if d.get("paper2_open_trade"):
            d["paper2_open_trade"] = _serialize(d["paper2_open_trade"])
        d["paper2_trades"] = _serialize(d.get("paper2_trades", []))
        if d.get("last_trade"):
            d["last_trade"] = _serialize(d["last_trade"])
        return d
    except Exception as e:
        return {"error": str(e)}


def _html_no_cache(template, **kwargs):
    """HTML không cache để sau deploy, F5 luôn lấy bản mới."""
    resp = app.make_response(render_template(template, **kwargs))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/")
def index():
    return redirect(url_for("page_paper"))


@app.route("/paper")
def page_paper():
    return _html_no_cache("paper.html", nav_active="paper")


@app.route("/paper2")
def page_paper2():
    return _html_no_cache("paper2.html", nav_active="paper2")


@app.route("/chart")
def page_chart():
    return _html_no_cache("chart.html", nav_active="chart")


@app.route("/real")
def page_real():
    return _html_no_cache("real.html", nav_active="real")


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
    # Giá trị hiển thị cho quy tắc vốn (đã khóa hoặc mặc định từ config)
    try:
        from config import settings as _cfg
        d["paper_leverage_display"] = d.get("paper_leverage") if d.get("paper_leverage") is not None else _cfg.LEVERAGE
        d["paper_wallet_pct_display"] = d.get("paper_wallet_pct") if d.get("paper_wallet_pct") is not None else _cfg.WALLET_PCT
    except Exception:
        d["paper_leverage_display"] = d.get("paper_leverage") or 20.0
        d["paper_wallet_pct_display"] = d.get("paper_wallet_pct") or 0.30

    open2 = d.get("paper2_open_trade")
    if open2:
        try:
            from config import settings
            client = _get_client()
            df = client.get_klines(settings.SYMBOL, "1m", 1)
            current_price = float(df["close"].iloc[-1]) if not df.empty else None
        except Exception:
            current_price = None
        if current_price is not None:
            entry = float(open2.get("entry_price") or 0)
            size = float(open2.get("size") or 0)
            side = str(open2.get("side", "")).upper()
            if side == "LONG":
                pnl_open2 = (current_price - entry) * size
            else:
                pnl_open2 = (entry - current_price) * size
            balance2 = float(d.get("paper2_balance") or 0)
            d["paper2_pnl_open"] = round(pnl_open2, 2)
            d["paper2_capital_open"] = round(balance2 + pnl_open2, 2)
        else:
            d["paper2_pnl_open"] = 0.0
            d["paper2_capital_open"] = float(d.get("paper2_balance") or 0)
        d["paper2_orders_open_count"] = 1
    else:
        d["paper2_pnl_open"] = 0.0
        d["paper2_capital_open"] = float(d.get("paper2_balance") or 0)
        d["paper2_orders_open_count"] = 0
    try:
        from config import settings as _cfg
        d["paper2_leverage_display"] = d.get("paper2_leverage") if d.get("paper2_leverage") is not None else _cfg.LEVERAGE
        d["paper2_wallet_pct_display"] = d.get("paper2_wallet_pct") if d.get("paper2_wallet_pct") is not None else _cfg.WALLET_PCT
    except Exception:
        d["paper2_leverage_display"] = d.get("paper2_leverage") or 20.0
        d["paper2_wallet_pct_display"] = d.get("paper2_wallet_pct") or 0.30
    try:
        from config import settings as _cfg
        _lb = d.get("paper2_lookback_trades")
        if _lb is not None:
            d["paper2_lookback_display"] = int(_lb)
        else:
            d["paper2_lookback_display"] = int(getattr(_cfg, "LOOKBACK_TRADES", 15))
    except Exception:
        d["paper2_lookback_display"] = 15
    try:
        from config import settings as _cfg2
        d["taker_fee"] = float(getattr(_cfg2, "TAKER_FEE", 0.0004))
    except Exception:
        d["taker_fee"] = 0.0004
    try:
        from config import settings as _ctf
        _tfee = float(getattr(_ctf, "TAKER_FEE", 0.0004))
        _lt1 = list(d.get("paper_trades") or [])
        _lt2 = list(d.get("paper2_trades") or [])
        d["paper_replay_initial"] = _infer_initial_capital(
            _lt1, float(d.get("paper_initial_capital") or 0), _tfee
        )
        d["paper2_replay_initial"] = _infer_initial_capital(
            _lt2, float(d.get("paper2_initial_capital") or 0), _tfee
        )
    except Exception:
        d["paper_replay_initial"] = float(d.get("paper_initial_capital") or 0)
        d["paper2_replay_initial"] = float(d.get("paper2_initial_capital") or 0)
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


@app.route("/api/paper/set-initial-capital", methods=["POST"])
def api_paper_set_initial_capital():
    """
    Chỉ cập nhật mốc vốn USDT (paper_initial_capital). UI/CSV/chart tính lại replay từ mốc này + lịch sử.
    Không đổi paper_balance hay profit từng lệnh.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
        capital = float(data.get("initial_capital", 0))
        if capital <= 0:
            return jsonify({"ok": False, "error": "initial_capital phải > 0"}), 400
        from bot import state
        state.set_paper_initial_capital(capital)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "message": "Đã lưu mốc vốn Paper 1. Bảng / biểu đồ / CSV dùng mốc này để tính lại Cap After & %PnL vốn.",
            "paper_initial_capital": capital,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper/clear-history", methods=["POST"])
def api_paper_clear_history():
    """Xóa toàn bộ lịch sử lệnh (UI + state), reset về trạng thái ban đầu. Dữ liệu đã xuất CSV vẫn giữ ở file đã tải."""
    try:
        from bot import state
        state.paper_clear_history()
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({"ok": True, "message": "Đã xóa toàn bộ lịch sử lệnh."})
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


@app.route("/api/paper/capital-rules", methods=["POST"])
def api_paper_capital_rules():
    """Cập nhật và khóa quy tắc vốn: đòn bẩy, % vốn vào lệnh. Các lệnh sau áp dụng theo."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        leverage = data.get("leverage")
        wallet_pct = data.get("wallet_pct")
        if leverage is not None:
            leverage = float(leverage)
            if leverage < 1 or leverage > 125:
                return jsonify({"ok": False, "error": "Đòn bẩy phải từ 1 đến 125"}), 400
        if wallet_pct is not None:
            wallet_pct = float(wallet_pct)
            if wallet_pct < 0.01 or wallet_pct > 1.0:
                return jsonify({"ok": False, "error": "% vốn vào lệnh phải từ 1% đến 100%"}), 400
        from bot import state
        if leverage is not None:
            state.set_paper_leverage(leverage)
        if wallet_pct is not None:
            state.set_paper_wallet_pct(wallet_pct)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "message": "Đã cập nhật quy tắc vốn.",
            "paper_leverage": state.get_paper_leverage(),
            "paper_wallet_pct": state.get_paper_wallet_pct(),
        })
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": "Giá trị không hợp lệ: " + str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/start", methods=["POST"])
def api_paper2_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
        capital = float(data.get("initial_capital", 0))
        if capital <= 0:
            return jsonify({"ok": False, "error": "initial_capital phải > 0"}), 400
        from bot import state
        state.paper2_start(capital)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({"ok": True, "message": "Đã kích hoạt Paper trade 2 (phương pháp 2)."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/set-initial-capital", methods=["POST"])
def api_paper2_set_initial_capital():
    """Cập nhật paper2_initial_capital; replay UI/CSV/chart theo mốc mới + lịch sử (không đổi balance thực tế)."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        capital = float(data.get("initial_capital", 0))
        if capital <= 0:
            return jsonify({"ok": False, "error": "initial_capital phải > 0"}), 400
        from bot import state
        state.set_paper2_initial_capital(capital)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "message": "Đã lưu mốc vốn Paper 2. Bảng / biểu đồ / CSV tính lại theo mốc này.",
            "paper2_initial_capital": capital,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/clear-history", methods=["POST"])
def api_paper2_clear_history():
    try:
        from bot import state
        state.paper2_clear_history()
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({"ok": True, "message": "Đã xóa toàn bộ lịch sử Paper 2."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/pause", methods=["POST"])
def api_paper2_pause():
    try:
        from bot import state
        state.paper2_pause()
        return jsonify({"ok": True, "message": "Đã tạm dừng Paper 2."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/stop", methods=["POST"])
def api_paper2_stop():
    try:
        from bot import state
        state.paper2_stop()
        return jsonify({"ok": True, "message": "Đã dừng Paper 2."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/capital-rules", methods=["POST"])
def api_paper2_capital_rules():
    try:
        data = request.get_json(force=True, silent=True) or {}
        leverage = data.get("leverage")
        wallet_pct = data.get("wallet_pct")
        if leverage is not None:
            leverage = float(leverage)
            if leverage < 1 or leverage > 125:
                return jsonify({"ok": False, "error": "Đòn bẩy phải từ 1 đến 125"}), 400
        if wallet_pct is not None:
            wallet_pct = float(wallet_pct)
            if wallet_pct < 0.01 or wallet_pct > 1.0:
                return jsonify({"ok": False, "error": "% vốn vào lệnh phải từ 1% đến 100%"}), 400
        from bot import state
        if leverage is not None:
            state.set_paper2_leverage(leverage)
        if wallet_pct is not None:
            state.set_paper2_wallet_pct(wallet_pct)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "message": "Đã cập nhật quy tắc vốn Paper 2.",
            "paper2_leverage": state.get_paper2_leverage(),
            "paper2_wallet_pct": state.get_paper2_wallet_pct(),
        })
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": "Giá trị không hợp lệ: " + str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/strategy", methods=["POST"])
def api_paper2_strategy():
    """Lưu lookback %change (số lệnh đã đóng trong cửa sổ — không phải số nến)."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        lb = data.get("lookback_trades")
        if lb is None:
            return jsonify({"ok": False, "error": "Thiếu lookback_trades"}), 400
        lb = int(lb)
        lb = min(max(lb, 1), 200)
        from bot import state
        state.set_paper2_lookback_trades(lb)
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "message": "Đã lưu chiến lược Paper 2 (lookback %change).",
            "paper2_lookback_trades": lb,
        })
    except (TypeError, ValueError) as e:
        return jsonify({"ok": False, "error": "lookback_trades phải là số từ 1 đến 200: " + str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper2/close", methods=["POST"])
def api_paper2_close():
    try:
        result = _close_paper_slot(2)
        ok, msg, extra, closed = result[0], result[1], result[2], result[3] if len(result) > 3 else None
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        if closed:
            try:
                from telegram.notifier import notify_trade_closed
                notify_trade_closed(closed, source="web", paper_slot=2)
            except Exception as e:
                try:
                    from telegram.notifier import send_message
                    send_message(f"[PAPER2] 🔴 Đóng lệnh từ Web\nPnL: {extra.get('pnl', 0):+.2f} USDT")
                except Exception:
                    pass
        return jsonify({"ok": True, "message": msg, **(extra or {})})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/paper/close", methods=["POST"])
def api_paper_close():
    """Chốt lệnh paper đang mở từ web. Luôn gửi Telegram thông báo đóng lệnh."""
    try:
        result = _close_paper_position()
        ok, msg, extra, closed = result[0], result[1], result[2], result[3] if len(result) > 3 else None
        if not ok:
            return jsonify({"ok": False, "error": msg}), 400
        try:
            from bot.paper_persistence import save_paper_state
            save_paper_state()
        except Exception:
            pass
        # Luôn gửi Telegram khi chốt lệnh từ web
        if closed:
            try:
                from telegram.notifier import notify_trade_closed
                notify_trade_closed(closed, source="web", paper_slot=1)
            except Exception as e:
                try:
                    from telegram.notifier import send_message
                    send_message(
                        f"[PAPER] 🔴 Đóng lệnh từ Web\n"
                        f"PnL: {extra.get('pnl', 0):+.2f} USDT | Vốn sau: {extra.get('capital_after', 0):.2f} USDT"
                    )
                except Exception:
                    pass
        return jsonify({"ok": True, "message": msg, **(extra or {})})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/restore-pending")
def api_restore_pending():
    """Sau khi pull/deploy, nếu đã load state có lệnh mở thì frontend hiện popup hỏi giữ/đóng."""
    try:
        from bot.paper_persistence import get_restore_pending, get_restore_pending_paper2
        return jsonify({
            "pending": get_restore_pending(),
            "pending_paper2": get_restore_pending_paper2(),
        })
    except Exception:
        return jsonify({"pending": False, "pending_paper2": False})


def _close_paper_slot(slot: int):
    """Đóng lệnh paper slot 1 hoặc 2. Trả (ok, msg, extra, closed|None)."""
    from bot import state
    from config import settings
    from datetime import datetime
    if int(slot) == 2:
        open_trade = state.get_paper2_open_trade()
        get_balance = state.get_paper2_balance
        set_open = state.set_paper2_open_trade
        set_last = state.set_paper2_last_trade
        append_trade = state.append_paper2_trade
        set_balance = state.set_paper2_balance
    else:
        open_trade = state.get_paper_open_trade()
        get_balance = state.get_paper_balance
        set_open = state.set_paper_open_trade
        set_last = state.set_paper_last_trade
        append_trade = state.append_paper_trade
        set_balance = state.set_paper_balance
    if not open_trade:
        return False, "Không có lệnh nào đang mở.", None, None
    balance = get_balance()
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
        "exit_time": datetime.now(_tz_app),
        "entry_price": entry,
        "exit_price": exit_px,
        "side": side,
        "size": open_trade.get("size"),
        "margin": open_trade.get("margin"),
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
        "paper_slot": int(slot),
    }
    set_open(None)
    set_last(closed)
    append_trade(closed)
    set_balance(capital_after)
    extra = {"pnl": round(pnl_net, 2), "capital_after": round(capital_after, 2)}
    return True, "Đã chốt lệnh.", extra, closed


def _close_paper_position():
    """Đóng paper slot 1 (tương thích tên cũ)."""
    return _close_paper_slot(1)


@app.route("/api/restore-choice", methods=["POST"])
def api_restore_choice():
    """User chọn: giữ vị thế cũ (keep=true) hoặc đóng lệnh (keep=false). slot=1 paper, slot=2 paper2."""
    try:
        from bot.paper_persistence import (
            get_restore_pending,
            get_restore_pending_paper2,
            clear_restore_pending_paper,
            clear_restore_pending_paper2,
        )
        data = request.get_json(force=True, silent=True) or {}
        keep = data.get("keep", True)
        slot = int(data.get("slot", 1))
        if slot == 2:
            if not get_restore_pending_paper2():
                return jsonify({"ok": True, "message": "Không có lựa chọn đang chờ."})
            if keep:
                clear_restore_pending_paper2()
                return jsonify({"ok": True, "message": "Đã giữ vị thế paper trade 2."})
            result = _close_paper_slot(2)
            ok, msg, extra = result[0], result[1], result[2]
            clear_restore_pending_paper2()
            if ok:
                try:
                    from bot.paper_persistence import save_paper_state
                    save_paper_state()
                except Exception:
                    pass
                closed = result[3] if len(result) > 3 else None
                if closed:
                    try:
                        from telegram.notifier import notify_trade_closed
                        notify_trade_closed(closed, source="web", paper_slot=2)
                    except Exception:
                        pass
                return jsonify({"ok": True, "message": msg, **(extra or {})})
            return jsonify({"ok": False, "error": msg}), 400
        if not get_restore_pending():
            return jsonify({"ok": True, "message": "Không có lựa chọn đang chờ."})
        if keep:
            clear_restore_pending_paper()
            return jsonify({"ok": True, "message": "Đã giữ vị thế paper trade."})
        result = _close_paper_position()
        ok, msg, extra = result[0], result[1], result[2]
        clear_restore_pending_paper()
        if ok:
            try:
                from bot.paper_persistence import save_paper_state
                save_paper_state()
            except Exception:
                pass
            closed = result[3] if len(result) > 3 else None
            if closed:
                try:
                    from telegram.notifier import notify_trade_closed
                    notify_trade_closed(closed, source="web", paper_slot=1)
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
    """Klines + indicators theo interval. interval: 1m, 5m, 15m, 1h, 4h, 1d, 3d. Thêm pct_change (%change)."""
    try:
        from config import settings
        from strategy.indicators import add_indicators
        from strategy.pct_change_avg import build_pct_change_avg_bands

        interval = request.args.get("interval", "5m").strip().lower()
        limit = min(int(request.args.get("limit", 500)), 1000)
        if interval not in ("1m", "5m", "15m", "1h", "4h", "1d", "3d"):
            interval = "5m"
        try:
            lookback_trades = int(request.args.get("lookback_trades", 15))
        except (TypeError, ValueError):
            lookback_trades = 15
        lookback_trades = min(max(lookback_trades, 1), 200)

        client = _get_client()
        df = client.get_klines(settings.SYMBOL, interval, limit)
        if df.empty:
            return jsonify(
                {
                    "ohlc": [],
                    "indicators": {},
                    "interval": interval,
                    "symbol": settings.SYMBOL,
                    "lookback_trades": lookback_trades,
                    "pct_change": _pct_change_bands_to_json({}),
                }
            )
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
        bands = build_pct_change_avg_bands(
            df[["open", "high", "low", "close", "volume"]],
            lookback_trades=lookback_trades,
        )
        pct_json = _pct_change_bands_to_json(bands)
        return jsonify(
            {
                "ohlc": ohlc,
                "indicators": indicators,
                "interval": interval,
                "symbol": settings.SYMBOL,
                "lookback_trades": lookback_trades,
                "pct_change": pct_json,
            }
        )
    except Exception as e:
        sym = ""
        try:
            from config import settings as _s

            sym = _s.SYMBOL
        except Exception:
            pass
        return jsonify(
            {
                "ohlc": [],
                "indicators": {},
                "symbol": sym,
                "error": str(e),
                "pct_change": _pct_change_bands_to_json({}),
            }
        )


def _pct_pnl(profit: float, margin: float) -> float:
    """% PnL = profit / vốn vào lệnh (margin) * 100. VD: 40u lời, 300u margin → 13.33%."""
    return round((profit / margin * 100), 2) if margin and margin != 0 else 0.0


def _pct_pnl_capital(profit: float, capital_before: float) -> float:
    """% PnL vốn = profit / capital_before * 100 (theo tổng vốn tài khoản lúc vào lệnh)."""
    return round((profit / capital_before * 100), 2) if capital_before and capital_before != 0 else 0.0


def _effective_margin(entry: float, size: float, leverage: float, stored_margin=None, capital_before=None):
    """Vốn vào lệnh (margin) = notional/leverage. Nếu stored sai (vd > capital) thì dùng margin_calc."""
    margin_calc = (entry * size) / float(leverage) if (entry and size and leverage) else None
    margin = stored_margin
    if margin is None or margin <= 0:
        margin = margin_calc
    if capital_before and margin and margin > capital_before:
        margin = margin_calc
    return margin


def _paper_entry_fee_usdt(entry_px: float, size: float, taker_fee: float) -> float:
    if entry_px and size:
        return float(entry_px) * float(size) * float(taker_fee)
    return 0.0


def _capital_after_closed_trade(t: dict, replay_cap_after) -> float | None:
    """
    Cap After hiển thị/CSV: ưu tiên replay theo paper*_initial_capital (đổi mốc = tính lại đồng bộ).
    Fallback capital_after lưu trong trade nếu thiếu meta.
    """
    if replay_cap_after is not None:
        try:
            return round(float(replay_cap_after), 2)
        except (TypeError, ValueError):
            pass
    raw = t.get("capital_after")
    if raw is not None:
        try:
            x = float(raw)
            if x == x:
                return round(x, 2)
        except (TypeError, ValueError):
            pass
    return None


def _orders_json_for_slot(slot: int):
    """Danh sách lệnh JSON cho paper (1) hoặc paper2 (2)."""
    from bot import state
    from config import settings
    status = get_status()
    if status.get("error"):
        return None, status["error"]
    slot = int(slot)
    if slot == 2:
        open_trade = status.get("paper2_open_trade")
        trades = list(status.get("paper2_trades") or [])
        leverage = state.get_paper2_leverage() or getattr(settings, "LEVERAGE", 20.0)
    else:
        open_trade = status.get("paper_open_trade")
        trades = list(status.get("paper_trades") or [])
        leverage = state.get_paper_leverage() or getattr(settings, "LEVERAGE", 20.0)
    chronological = list(trades)
    taker_fee = float(getattr(settings, "TAKER_FEE", 0.0004))
    if slot == 2:
        init_cap = float(status.get("paper2_initial_capital") or 0)
    else:
        init_cap = float(status.get("paper_initial_capital") or 0)
    initial = _infer_initial_capital(chronological, init_cap, taker_fee)
    meta = _paper_ledger_meta(chronological, initial, taker_fee)

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
        cap_before_open = float(open_trade.get("capital_before") or 0)
        margin_open = _effective_margin(entry, size, leverage, open_trade.get("margin"), cap_before_open)
        if current_price and entry and size:
            if side == "LONG":
                pnl = (current_price - entry) * size
            else:
                pnl = (entry - current_price) * size
        else:
            pnl = 0.0
        pct_pnl_open = _pct_pnl(pnl, margin_open) if margin_open else 0.0
        pct_pnl_capital_open = _pct_pnl_capital(pnl, cap_before_open)
        orders.append({
            "id": "open",
            "side": side,
            "entry_time": open_trade.get("entry_time"),
            "entry_price": entry,
            "exit_time": None,
            "exit_price": None,
            "pnl": round(pnl, 2),
            "entry_fee": None,
            "wallet_change": None,
            "pct_pnl": pct_pnl_open,
            "pct_pnl_capital": pct_pnl_capital_open,
            "capital_after": None,
            "is_open": True,
            "symbol": settings.SYMBOL,
            "exit_reason": None,
            "trade_key": "open",
            "replay_index": -1,
            "size": size,
        })
    n = len(trades)
    for i, t in enumerate(reversed(trades)):
        idx = n - 1 - i
        lm = meta[idx] if idx < len(meta) else {}
        profit = float(t.get("profit", 0))
        cap_before_stored = float(t.get("capital_before") or 0)
        replay_ca = lm.get("capital_after_close")
        cap_after = _capital_after_closed_trade(t, replay_ca)
        entry_px = float(t.get("entry_price") or 0)
        size = float(t.get("size") or 0)
        fee_in = _paper_entry_fee_usdt(entry_px, size, taker_fee)
        wallet_change = round(profit - fee_in, 2)
        margin_t = _effective_margin(entry_px, size, leverage, t.get("margin"), cap_before_stored)
        pct_pnl = _pct_pnl(profit, margin_t) if margin_t else None
        cap_eq = float(lm.get("capital_equity_before_open") or 0)
        pct_pnl_capital = _pct_pnl_capital(profit, cap_eq) if cap_eq else None
        orders.append({
            "id": len(orders) + 1,
            "side": str(t.get("side", "")).upper(),
            "entry_time": t.get("entry_time"),
            "entry_price": t.get("entry_price"),
            "exit_time": t.get("exit_time"),
            "exit_price": t.get("exit_price"),
            "pnl": round(profit, 2),
            "entry_fee": round(fee_in, 6),
            "wallet_change": wallet_change,
            "pct_pnl": pct_pnl,
            "pct_pnl_capital": pct_pnl_capital,
            "capital_after": cap_after,
            "is_open": False,
            "symbol": settings.SYMBOL,
            "exit_reason": t.get("exit_reason"),
            "trade_key": lm.get("trade_key") or _trade_key_closed(t),
            "replay_index": int(lm.get("replay_index", idx)),
            "size": size,
        })
    return orders, None


@app.route("/api/orders")
def api_orders():
    """Danh sách lệnh (mở + đã đóng), mới nhất lên đầu; slot=1 paper, slot=2 paper2."""
    try:
        slot = int(request.args.get("slot", "1") or "1")
        orders, err = _orders_json_for_slot(slot)
        if err:
            return jsonify({"orders": [], "error": err})
        return jsonify({"orders": orders})
    except Exception as e:
        return jsonify({"orders": [], "error": str(e)})


def _orders_for_csv(slot: int = 1):
    """Danh sách lệnh đầy đủ (kể cả 3 đường lúc vào/thoát) để xuất CSV."""
    from bot import state
    from config import settings
    status = get_status()
    if status.get("error"):
        return [], None
    slot = int(slot)
    if slot == 2:
        open_trade = status.get("paper2_open_trade")
        trades = list(status.get("paper2_trades") or [])
        leverage = state.get_paper2_leverage() or getattr(settings, "LEVERAGE", 20.0)
    else:
        open_trade = status.get("paper_open_trade")
        trades = list(status.get("paper_trades") or [])
        leverage = state.get_paper_leverage() or getattr(settings, "LEVERAGE", 20.0)
    symbol = getattr(settings, "SYMBOL", "BTCUSDT")
    chronological = list(trades)
    taker_fee = float(getattr(settings, "TAKER_FEE", 0.0004))
    if slot == 2:
        init_cap = float(status.get("paper2_initial_capital") or 0)
    else:
        init_cap = float(status.get("paper_initial_capital") or 0)
    initial = _infer_initial_capital(chronological, init_cap, taker_fee)
    meta = _paper_ledger_meta(chronological, initial, taker_fee)
    n_csv = len(trades)

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
            "entry_fee": "",
            "wallet_change": "",
            "pct_pnl": "",
            "pct_pnl_capital": "",
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
        idx = n_csv - 1 - i
        lm = meta[idx] if idx < len(meta) else {}
        profit = float(t.get("profit", 0))
        cap_before = float(t.get("capital_before") or 0)
        replay_ca = lm.get("capital_after_close")
        cap_after = _capital_after_closed_trade(t, replay_ca)
        entry_px = float(t.get("entry_price") or 0)
        size = float(t.get("size") or 0)
        fee_in = _paper_entry_fee_usdt(entry_px, size, taker_fee)
        wallet_change = round(profit - fee_in, 2)
        margin_t = _effective_margin(entry_px, size, leverage, t.get("margin"), cap_before)
        pct_pnl = _pct_pnl(profit, margin_t) if margin_t else ""
        cap_eq = float(lm.get("capital_equity_before_open") or 0)
        pct_pnl_capital = _pct_pnl_capital(profit, cap_eq) if cap_eq else ""
        rows.append({
            "id": len(rows) + 1,
            "symbol": symbol,
            "side": str(t.get("side", "")).upper(),
            "entry_time": _ts(t.get("entry_time")),
            "entry_price": t.get("entry_price"),
            "exit_time": _ts(t.get("exit_time")),
            "exit_price": t.get("exit_price"),
            "profit": round(profit, 2),
            "entry_fee": round(fee_in, 6),
            "wallet_change": wallet_change,
            "pct_pnl": pct_pnl,
            "pct_pnl_capital": pct_pnl_capital,
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


@app.route("/api/paper/reconcile")
def api_paper_reconcile():
    """
    Double-check vốn / PnL so với CSV và state.
    slot=1: Paper trade; slot=2: Paper trade 2 (khác ví với slot=1).
    """
    try:
        from config import settings

        slot = int(request.args.get("slot", "1") or "1")
        status = get_status()
        if status.get("error"):
            return jsonify({"error": status["error"]})
        taker = float(getattr(settings, "TAKER_FEE", 0.0004))
        if slot == 2:
            trades = list(status.get("paper2_trades") or [])
            init_cap = float(status.get("paper2_initial_capital") or 0)
            bal = status.get("paper2_balance")
            has_open = bool(status.get("paper2_open_trade"))
        else:
            trades = list(status.get("paper_trades") or [])
            init_cap = float(status.get("paper_initial_capital") or 0)
            bal = status.get("paper_balance")
            has_open = bool(status.get("paper_open_trade"))
        rep = _reconcile_trades(
            trades,
            init_cap,
            taker,
            float(bal) if bal is not None else None,
            has_open,
        )
        rep["slot"] = slot
        return jsonify(rep)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/export/csv")
def api_export_csv():
    """Xuất CSV: capital_after = số bot đã ghi; entry_fee + wallet_change để cộng dồn ví (≠ chỉ SUM profit)."""
    try:
        slot = int(request.args.get("slot", "1") or "1")
        rows, symbol = _orders_for_csv(slot)
        buf = io.StringIO()
        if not rows:
            buf.write(
                "id,symbol,side,entry_time,entry_price,exit_time,exit_price,profit,entry_fee,wallet_change,"
                "pct_pnl,pct_pnl_capital,capital_after,exit_reason,entry_rsi,entry_ema_rsi,entry_wma_rsi,"
                "exit_rsi,exit_ema_rsi,exit_wma_rsi\n"
            )
        else:
            cols = list(rows[0].keys())
            w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        now = datetime.now(_tz_app)
        suffix = f"_p{slot}" if slot == 2 else ""
        filename = f"orders_{symbol}{suffix}_{now.strftime('%Y%m%d_%H%M')}.csv"
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
