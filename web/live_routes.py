# -*- coding: utf-8 -*-
"""
Trang /live — dashboard trade thật: kết nối tài khoản sàn, Telegram, chọn chiến lược × cặp coin × tài khoản,
bật/tắt, theo dõi vị thế, đóng lệnh. Bắt buộc đăng nhập bằng LIVE_ADMIN_PASSWORD (.env).
"""

from __future__ import annotations

import csv
import hmac
import io
import os
import secrets
import time
from datetime import timedelta
from functools import wraps

from flask import Blueprint, Response, jsonify, redirect, render_template, request, session, url_for

from live import store

bp = Blueprint("live", __name__)

_fail = {}  # ip -> (count, first_ts)
MAX_FAILS = 5
LOCK_SEC = 600


def init_app(app):
    from live.secrets_box import flask_secret
    if not app.secret_key:
        app.secret_key = flask_secret()
    app.config.setdefault("SESSION_COOKIE_HTTPONLY", True)
    app.config.setdefault("SESSION_COOKIE_SAMESITE", "Lax")
    if (os.environ.get("WEB_COOKIE_SECURE") or "").lower() in ("1", "true", "yes"):
        app.config["SESSION_COOKIE_SECURE"] = True
    app.config.setdefault("PERMANENT_SESSION_LIFETIME", timedelta(days=7))
    app.register_blueprint(bp)


def _admin_password() -> str:
    return (os.environ.get("LIVE_ADMIN_PASSWORD") or "").strip()


def _client_ip():
    return (request.headers.get("X-Real-IP") or request.remote_addr or "?").split(",")[0].strip()


def _logged_in() -> bool:
    return bool(session.get("live_auth")) and bool(_admin_password())


def login_required(api: bool = False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if not _logged_in():
                if api:
                    return jsonify({"error": "Chưa đăng nhập"}), 401
                return redirect(url_for("live.login", next=request.path))
            if request.method == "POST":
                token = request.headers.get("X-CSRF-Token", "")
                if not token or not hmac.compare_digest(token, session.get("csrf", "")):
                    return jsonify({"error": "Phiên hết hạn, tải lại trang"}), 403
            return fn(*a, **kw)
        return wrapper
    return deco


def _engine():
    from live.engine import get_engine
    return get_engine()


def _ok(**kw):
    return jsonify({"ok": True, **kw})


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


# ------------------------------------------------------------------ trang
@bp.route("/live/login", methods=["GET", "POST"])
def login():
    pw_set = bool(_admin_password())
    error = None
    if request.method == "POST" and pw_set:
        ip = _client_ip()
        cnt, first = _fail.get(ip, (0, time.time()))
        if cnt >= MAX_FAILS and time.time() - first < LOCK_SEC:
            error = "Sai mật khẩu quá nhiều lần, thử lại sau 10 phút."
        elif hmac.compare_digest((request.form.get("password") or "").encode(), _admin_password().encode()):
            _fail.pop(ip, None)
            session.clear()
            session.permanent = True
            session["live_auth"] = True
            session["csrf"] = secrets.token_urlsafe(24)
            nxt = request.args.get("next") or url_for("live.page")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("live.page"))
        else:
            if time.time() - first >= LOCK_SEC:
                cnt, first = 0, time.time()
            _fail[ip] = (cnt + 1, first)
            error = "Sai mật khẩu."
    return render_template("live_login.html", pw_set=pw_set, error=error, nav_active="real")


@bp.route("/live/logout")
def logout():
    session.clear()
    return redirect(url_for("live.login"))


@bp.route("/live")
@login_required()
def page():
    from exchange.binance_futures import ENV_LABELS
    resp = Response(render_template(
        "live.html",
        nav_active="real",
        csrf=session.get("csrf", ""),
        methods=store.METHODS,
        exchanges=store.EXCHANGES,
        envs=ENV_LABELS,
    ))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --------------------------------------------------------------- dữ liệu
@bp.route("/api/live/overview")
@login_required(api=True)
def api_overview():
    try:
        ov = _engine().overview()
    except Exception as e:
        return _err(e, 500)
    return jsonify(store._to_json(ov))


@bp.route("/api/live/config")
@login_required(api=True)
def api_config():
    return jsonify({
        "real_trading_enabled": store.real_trading_enabled(),
        "accounts": store.list_accounts(),
        "telegrams": store.list_telegrams(),
        "bots": store.list_bots(),
    })


@bp.route("/api/live/events")
@login_required(api=True)
def api_events():
    return jsonify(store.events(int(request.args.get("limit", 100))))


@bp.route("/api/live/snapshots")
@login_required(api=True)
def api_snapshots():
    return jsonify(store.snapshots(int(request.args.get("limit", 168))))


def _trades(bot_id=None):
    rows = []
    for b in store.list_bots():
        if bot_id and b["id"] != bot_id:
            continue
        for t in store.bot_state(b["id"]).get("trades") or []:
            rows.append({"bot_id": b["id"], "bot": b["name"], "symbol": b["symbol"], "method": b["method"], **t})
    rows.sort(key=lambda r: str(r.get("exit_time")), reverse=True)
    return store._to_json(rows)


@bp.route("/api/live/trades")
@login_required(api=True)
def api_trades():
    return jsonify(_trades(request.args.get("bot_id"))[: int(request.args.get("limit", 300))])


@bp.route("/api/live/trades.csv")
@login_required(api=True)
def api_trades_csv():
    rows = _trades(request.args.get("bot_id"))
    cols = ["bot", "symbol", "method", "side", "entry_time", "entry_price", "exit_time", "exit_price", "size", "margin",
            "entry_fee", "exit_fee", "profit", "capital_before", "capital_after", "exit_reason", "signal_exit_price"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="live_trades.csv"'})


# ---------------------------------------------------------- công tắc tổng
@bp.route("/api/live/switch", methods=["POST"])
@login_required(api=True)
def api_switch():
    on = bool((request.get_json(silent=True) or {}).get("on"))
    store.set_real_trading_enabled(on, by="web")
    return _ok(real_trading_enabled=on)


@bp.route("/api/live/closeall", methods=["POST"])
@login_required(api=True)
def api_closeall():
    _engine().request_close_all(by="web")
    return _ok(message="Đã tắt trade thật và gửi lệnh đóng mọi vị thế.")


# -------------------------------------------------------------- tài khoản
@bp.route("/api/live/accounts", methods=["POST"])
@login_required(api=True)
def api_account_upsert():
    try:
        acc = store.upsert_account(request.get_json(silent=True) or {})
    except ValueError as e:
        return _err(e)
    store.add_event("config", f"Lưu tài khoản sàn: {acc['name']} ({acc['env']})")
    return _ok(account=acc)


@bp.route("/api/live/accounts/<acc_id>/test", methods=["POST"])
@login_required(api=True)
def api_account_test(acc_id):
    tr = _engine().trader_for(acc_id)
    if tr is None:
        return _err("Tài khoản chưa có API key / secret")
    try:
        info = tr.test_connection()
    except Exception as e:
        store.set_account_field(acc_id, last_test={"ok": False, "error": str(e)[:300], "t": store.now_iso()})
        return _err(f"Kết nối thất bại: {e}")
    store.set_account_field(acc_id, last_test={"ok": True, "t": store.now_iso(), "wallet": info.get("wallet"),
                                               "dual_side": info.get("dual_side")})
    return _ok(info=info)


@bp.route("/api/live/accounts/<acc_id>/enable", methods=["POST"])
@login_required(api=True)
def api_account_enable(acc_id):
    on = bool((request.get_json(silent=True) or {}).get("enabled"))
    acc = store.get_account(acc_id)
    if not acc:
        return _err("Không tìm thấy tài khoản", 404)
    if on and not acc.get("has_keys"):
        return _err("Nhập API key + secret trước khi bật")
    store.set_account_field(acc_id, enabled=on)
    store.add_event("config", f"Tài khoản {acc['name']}: {'BẬT' if on else 'TẮT'}")
    return _ok()


@bp.route("/api/live/accounts/<acc_id>/delete", methods=["POST"])
@login_required(api=True)
def api_account_delete(acc_id):
    try:
        store.delete_account(acc_id)
    except ValueError as e:
        return _err(e)
    return _ok()


# --------------------------------------------------------------- Telegram
@bp.route("/api/live/telegrams", methods=["POST"])
@login_required(api=True)
def api_tg_upsert():
    try:
        t = store.upsert_telegram(request.get_json(silent=True) or {})
    except ValueError as e:
        return _err(e)
    try:
        from live.telegram_ctl import sync_pollers
        sync_pollers()
    except Exception:
        pass
    return _ok(telegram=t)


@bp.route("/api/live/telegrams/<tg_id>/test", methods=["POST"])
@login_required(api=True)
def api_tg_test(tg_id):
    from live.telegram_ctl import send_test
    err = send_test(tg_id)
    return _err(f"Gửi thất bại: {err}") if err else _ok()


@bp.route("/api/live/telegrams/<tg_id>/delete", methods=["POST"])
@login_required(api=True)
def api_tg_delete(tg_id):
    store.delete_telegram(tg_id)
    try:
        from live.telegram_ctl import sync_pollers
        sync_pollers()
    except Exception:
        pass
    return _ok()


# -------------------------------------------------------------------- bot
@bp.route("/api/live/bots", methods=["POST"])
@login_required(api=True)
def api_bot_upsert():
    try:
        b = store.upsert_bot(request.get_json(silent=True) or {})
    except ValueError as e:
        return _err(e)
    store.add_event("config", f"Lưu bot {b['name']}: {b['symbol']} PP{b['method']} vốn {b['capital']} x{b['leverage']}", b["id"])
    return _ok(bot=b)


@bp.route("/api/live/bots/<bot_id>/status", methods=["POST"])
@login_required(api=True)
def api_bot_status(bot_id):
    status = (request.get_json(silent=True) or {}).get("status")
    try:
        store.set_bot_status(bot_id, status)
    except ValueError as e:
        return _err(e)
    b = store.get_bot(bot_id) or {}
    store.add_event("bot", f"Bot {b.get('name')}: {status} (bởi web)", bot_id)
    return _ok()


@bp.route("/api/live/bots/<bot_id>/close", methods=["POST"])
@login_required(api=True)
def api_bot_close(bot_id):
    if not store.bot_state(bot_id).get("open_trade"):
        return _err("Bot không có lệnh đang mở")
    _engine().request_close(bot_id, by="web")
    return _ok(message="Đã gửi lệnh đóng — kết quả hiện sau vài giây.")


@bp.route("/api/live/bots/<bot_id>/delete", methods=["POST"])
@login_required(api=True)
def api_bot_delete(bot_id):
    try:
        store.delete_bot(bot_id)
    except ValueError as e:
        return _err(e)
    return _ok()
