# -*- coding: utf-8 -*-
"""
[2026-11-21] Trang "Chiến lược" (/strategies) và trang "Backtest" (/backtest).

/strategies: kho đĩa chiến lược (strategy/disks.py) — xem, tải .md, NẠP đĩa mới, xoá đĩa nạp, bật paper cho đĩa
             (PP6, PP6.1, PP7, đĩa nạp). Mọi thao tác ghi cần đăng nhập admin (LIVE_ADMIN_PASSWORD, như /live) + CSRF.
/backtest:   chọn đĩa, một hoặc nhiều cặp coin, khoảng ngày, vốn, tham số thử → chạy (mỗi cặp một job, tối đa 3 job
             song song); nến đã tải được giữ trong backtest/data_cache nên chạy lại rất nhanh; mọi kết quả được lưu
             (data/backtests) để xem lại và tải Excel.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from flask import Blueprint, Response, jsonify, render_template, request, session

bp = Blueprint("disks", __name__)
_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")
MAX_SYMBOLS = 10


def _admin():
    from web.live_routes import _logged_in
    return _logged_in()


def _need_admin():
    """None nếu được phép ghi; ngược lại trả response lỗi."""
    import hmac
    if not _admin():
        return jsonify({"ok": False, "error": "Cần đăng nhập admin (mật khẩu như trang Trade thật)"}), 401
    token = request.headers.get("X-CSRF-Token", "")
    if not token or not hmac.compare_digest(token, session.get("csrf", "")):
        return jsonify({"ok": False, "error": "Phiên hết hạn, tải lại trang"}), 403
    return None


def _page(template, **kw):
    resp = Response(render_template(template, is_admin=_admin(), csrf=session.get("csrf", "") if _admin() else "", **kw))
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _err(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


# ------------------------------------------------------------------ trang
@bp.route("/strategies")
def page_strategies():
    return _page("strategies.html", nav_active="strategies")


@bp.route("/backtest")
def page_backtest():
    from config import settings
    return _page("backtest.html", nav_active="backtest", default_symbol=settings.SYMBOL,
                 default_lev=float(settings.LEVERAGE), default_wct=float(settings.WALLET_PCT) * 100)


# ------------------------------------------------------------------ đĩa
def _disk_row(d, with_paper=True):
    from bot import disk_paper
    row = d.to_public()
    row["own_page"] = {"1": "/paper", "2": "/paper2", "3": "/paper3", "4": "/paper4", "5": "/paper5"}.get(d.id)
    if with_paper and d.id not in disk_paper.OWN_PAGE_IDS:
        p = disk_paper.public(d.id)
        p.pop("trades", None)
        row["paper"] = p
    return row


@bp.route("/api/disks")
def api_disks():
    from strategy import disks
    return jsonify({
        "disks": [_disk_row(d) for d in disks.sorted_disks()],
        "errors": disks.load_errors(),
        "blocks": {k: v[0] for k, v in disks.BLOCKS.items()},
        "bases": disks.BASES,
        "is_admin": _admin(),
    })


@bp.route("/api/disks/schema")
def api_disk_schema():
    from strategy import disks
    sc = disks.param_schema()
    return jsonify({k: {"type": v["type"].__name__, "default": v["default"], "enum": v.get("enum")} for k, v in sorted(sc.items())})


@bp.route("/api/disks/<disk_id>")
def api_disk(disk_id):
    from strategy import disks
    d = disks.find_disk(disk_id)
    if d is None:
        return _err("Không có đĩa này", 404)
    row = _disk_row(d)
    row["body_html"] = disks.render_markdown_safe(d.body)
    return jsonify(row)


@bp.route("/api/disks/<disk_id>/md")
def api_disk_md(disk_id):
    from strategy import disks
    d = disks.find_disk(disk_id)
    if d is None or not d.text:
        return _err("Không có đĩa này", 404)
    safe = re.sub(r"[^a-z0-9_.-]", "_", d.id)
    resp = Response(d.text, mimetype="text/markdown; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="dia_{safe}.md"'
    return resp


def _upload_text():
    f = request.files.get("file")
    if f is not None:
        raw = f.read(70 * 1024)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("File phải là văn bản UTF-8 (.md)")
    data = request.get_json(silent=True) or {}
    return str(data.get("text") or "")


@bp.route("/api/disks/validate", methods=["POST"])
def api_disk_validate():
    """Kiểm tra đĩa (không lưu) — xem trước trước khi nạp."""
    bad = _need_admin()
    if bad:
        return bad
    from strategy import disks
    try:
        d = disks.parse_disk(_upload_text(), source="upload")
    except (ValueError, disks.DiskError) as e:
        return _err(e)
    ex = disks.find_disk(d.id)
    row = d.to_public()
    row["body_html"] = disks.render_markdown_safe(d.body)
    row["replaces"] = bool(ex and ex.source == "upload")
    row["conflict_builtin"] = bool(ex and ex.source == "builtin")
    return jsonify({"ok": True, "disk": row})


@bp.route("/api/disks/upload", methods=["POST"])
def api_disk_upload():
    bad = _need_admin()
    if bad:
        return bad
    from strategy import disks
    from bot import disk_paper
    try:
        text = _upload_text()
        d = disks.parse_disk(text, source="upload")
        ex = disks.find_disk(d.id)
        if ex is not None and ex.source == "upload" and disk_paper.slot(d.id).get("open_trade"):
            return _err("Đĩa này đang có lệnh paper mở — đóng lệnh trước rồi mới thay đĩa")
        d = disks.install_disk(text)
    except (ValueError, disks.DiskError) as e:
        return _err(e)
    return jsonify({"ok": True, "disk": _disk_row(d)})


@bp.route("/api/disks/<disk_id>/delete", methods=["POST"])
def api_disk_delete(disk_id):
    bad = _need_admin()
    if bad:
        return bad
    from strategy import disks
    from bot import disk_paper
    s = disk_paper.slot(disk_id)
    if s.get("open_trade"):
        return _err("Đĩa đang có lệnh paper mở — đóng lệnh trước")
    try:
        disks.remove_disk(disk_id)
    except disks.DiskError as e:
        return _err(e)
    disk_paper.set_status(disk_id, "stopped")
    return jsonify({"ok": True})


# ------------------------------------------------------------------ paper của đĩa
@bp.route("/api/disks/<disk_id>/paper")
def api_disk_paper(disk_id):
    from bot import disk_paper
    from strategy import disks
    if disks.find_disk(disk_id) is None or disk_id in disk_paper.OWN_PAGE_IDS:
        return _err("Không có khe paper cho đĩa này", 404)
    return jsonify(disk_paper.public(disk_id))


@bp.route("/api/disks/<disk_id>/paper/<action>", methods=["POST"])
def api_disk_paper_action(disk_id, action):
    bad = _need_admin()
    if bad:
        return bad
    from bot import disk_paper
    data = request.get_json(silent=True) or {}
    try:
        if action == "start":
            disk_paper.start(disk_id, capital=data.get("capital"), leverage=data.get("leverage"),
                             wallet_pct=data.get("wallet_pct"), symbol=data.get("symbol"))
        elif action in ("pause", "stop"):
            disk_paper.set_status(disk_id, "paused" if action == "pause" else "stopped")
        elif action == "reset":
            disk_paper.reset(disk_id, capital=data.get("capital"))
        elif action == "close":
            from exchange.binance_client import BinanceClient
            sym = disk_paper.slot(disk_id)["symbol"]
            df = BinanceClient().get_klines_1m(sym, limit=2)
            if df is None or df.empty:
                return _err("Không lấy được giá hiện tại")
            disk_paper.close_now(disk_id, float(df["close"].iloc[-1]), reason="MANUAL_WEB")
        else:
            return _err("Thao tác không hợp lệ", 404)
    except ValueError as e:
        return _err(e)
    return jsonify({"ok": True, "paper": disk_paper.public(disk_id)})


# ------------------------------------------------------------------ backtest
@bp.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    """Một đĩa × nhiều cặp: mỗi cặp một job (xếp hàng, tối đa 3 chạy cùng lúc). Trả danh sách job + mã lô."""
    from backtest import web_backtest
    from config import settings
    from strategy import disks
    data = request.get_json(silent=True) or {}
    method = str(data.get("method") or "").strip().lower()
    if disks.find_disk(method) is None:
        return _err("Chọn đĩa chiến lược")
    syms = data.get("symbols") or []
    if isinstance(syms, str):
        syms = re.split(r"[\s,;]+", syms)
    syms = [s.strip().upper() for s in syms if s and s.strip()]
    syms = list(dict.fromkeys(s if s.endswith("USDT") else s + "USDT" for s in syms)) or [settings.SYMBOL]
    if len(syms) > MAX_SYMBOLS:
        return _err(f"Tối đa {MAX_SYMBOLS} cặp mỗi lần")
    bad = [s for s in syms if not _SYMBOL_RE.match(s)]
    if bad:
        return _err(f"Cặp không hợp lệ: {', '.join(bad)}")
    start, end = str(data.get("start_date") or ""), (str(data.get("end_date") or "") or None)
    try:
        datetime.strptime(start, "%Y-%m-%d")
        if end:
            datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        return _err("Ngày không hợp lệ (dùng YYYY-MM-DD)")
    try:
        capital = float(data.get("initial_capital") or 1000)
        leverage = float(data.get("leverage") or settings.LEVERAGE)
        wct = float(data.get("wallet_pct") or settings.WALLET_PCT)
        wct = wct / 100.0 if wct > 1 else wct
        if not (1 <= capital <= 1e9 and 1 <= leverage <= 125 and 0 < wct <= 1):
            raise ValueError
    except (TypeError, ValueError):
        return _err("Vốn / đòn bẩy / % vốn không hợp lệ")
    params = data.get("params") or {}
    try:
        if isinstance(params, str):
            params = _parse_kv(params)
        params = disks.check_params(params)
    except (ValueError, disks.DiskError) as e:
        return _err(e)
    batch = uuid.uuid4().hex[:10]
    jobs = []
    for s in syms:
        jid = web_backtest.submit(
            method=method, symbol=s, start=start, end=end, initial_capital=capital, leverage=leverage,
            wallet_pct=wct, lookback_trades=int(getattr(settings, "LOOKBACK_TRADES", 15)), overrides=params, batch=batch,
        )
        jobs.append({"job_id": jid, "symbol": s})
    return jsonify({"ok": True, "batch": batch, "jobs": jobs})


def _parse_kv(text: str) -> dict:
    """'M7_RISK_PCT=0.01\\nM6_EXIT_MODE=close' → dict (số / true-false / chữ)."""
    from strategy.disks import _scalar
    out = {}
    for ln in str(text).splitlines():
        ln = ln.split("#", 1)[0].strip()
        if not ln:
            continue
        k, sep, v = ln.replace(":", "=", 1).partition("=")
        if not sep:
            raise ValueError(f"Dòng '{ln}' cần dạng TÊN=giá trị")
        out[k.strip().upper()] = _scalar(v, 0)
    return out


@bp.route("/api/backtests")
def api_backtests():
    from backtest import results_store, web_backtest
    running = []
    for jid, j in list(web_backtest._jobs.items()):
        if "result" not in j:
            p = j.get("params") or {}
            running.append({"id": jid, "method": p.get("method"), "symbol": p.get("symbol"), "batch": p.get("batch"),
                            "queued": "started" not in j})
    return jsonify({"items": results_store.listing(int(request.args.get("limit", 100))),
                    "running": running, "cache": results_store.cache_overview(), "is_admin": _admin()})


@bp.route("/api/backtests/<job_id>")
def api_backtest_saved(job_id):
    from backtest import web_backtest
    d = web_backtest.status(job_id)
    if d.get("state") == "unknown":
        return _err("Không có kết quả này", 404)
    return jsonify(d)


@bp.route("/api/backtests/<job_id>/delete", methods=["POST"])
def api_backtest_delete(job_id):
    bad = _need_admin()
    if bad:
        return bad
    from backtest import results_store
    return jsonify({"ok": results_store.delete(job_id)})
