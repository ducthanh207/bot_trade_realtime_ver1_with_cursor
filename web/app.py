# -*- coding: utf-8 -*-
"""Flask: trang Paper trade (giống GUI backtest) + API status / paper start-pause-stop."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from flask import Flask, jsonify, request, render_template_string
from datetime import datetime

app = Flask(__name__)


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
    return render_template_string(HTML_TEMPLATE)


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


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Paper Trade – ATR Strategy</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: 'Segoe UI', Tahoma, sans-serif; margin: 12px; background: #f5f5f5; }
    .container { max-width: 1200px; margin: 0 auto; }
    h1 { color: #333; margin-bottom: 8px; }
    .panel { background: #fff; border-radius: 8px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    .row { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; margin-bottom: 12px; }
    label { font-weight: 600; margin-right: 8px; }
    input[type="number"] { width: 120px; padding: 6px 8px; }
    .info { color: #666; font-size: 0.95em; }
    button { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; }
    button.start { background: #28a745; color: #fff; }
    button.pause { background: #ffc107; color: #000; }
    button.stop { background: #dc3545; color: #fff; }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #eee; }
    tr.profit { background: #d4edda; }
    tr.loss { background: #f8d7da; }
    .stats { font-size: 14px; margin-bottom: 12px; padding: 10px; background: #e8f4fd; border-radius: 6px; }
    .status-badge { display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 600; }
    .status-running { background: #28a745; color: #fff; }
    .status-paused { background: #ffc107; color: #000; }
    .status-stopped { background: #6c757d; color: #fff; }
    #refresh-msg { color: #666; font-size: 12px; margin-left: 12px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>Paper Trade – Chiến lược ATR</h1>
    <p class="info">Vốn ảo, giá thật từ Binance. Kích hoạt để bắt đầu tính từ hôm nay.</p>

    <div class="panel">
      <div class="row">
        <label for="initial_capital">Số vốn ban đầu (USDT):</label>
        <input type="number" id="initial_capital" value="1000" min="1" step="1">
        <span class="info">Ngày bắt đầu:</span>
        <span id="paper_started_at">—</span>
        <span id="refresh-msg">Tự động cập nhật 10s</span>
      </div>
      <div class="row">
        <button class="start" id="btnStart">Kích hoạt</button>
        <button class="pause" id="btnPause">Tạm dừng</button>
        <button class="stop" id="btnStop">Dừng</button>
        <span class="status-badge status-stopped" id="statusBadge">stopped</span>
      </div>
    </div>

    <div class="panel">
      <div class="stats" id="stats">
        Tổng số lệnh: 0 | LONG: 0 | SHORT: 0 | Winrate: 0.00% | PNL tổng: 0.00 USDT | Vốn hiện tại: 0.00 USDT
      </div>
      <table>
        <thead>
          <tr>
            <th>ID</th><th>Symbol</th><th>Side</th><th>Entry Time</th><th>Entry Price</th>
            <th>Exit Time</th><th>Exit Price</th><th>Profit</th><th>% PnL</th><th>Cap After</th><th>Reason</th>
          </tr>
        </thead>
        <tbody id="tradesBody"></tbody>
      </table>
    </div>
  </div>

  <script>
    const capitalInput = document.getElementById('initial_capital');
    const paperStartedAt = document.getElementById('paper_started_at');
    const statusBadge = document.getElementById('statusBadge');
    const statsEl = document.getElementById('stats');
    const tradesBody = document.getElementById('tradesBody');
    const btnStart = document.getElementById('btnStart');
    const btnPause = document.getElementById('btnPause');
    const btnStop = document.getElementById('btnStop');

    function setStatusBadge(s) {
      statusBadge.textContent = s;
      statusBadge.className = 'status-badge ';
      if (s === 'running') statusBadge.classList.add('status-running');
      else if (s === 'paused') statusBadge.classList.add('status-paused');
      else statusBadge.classList.add('status-stopped');
    }

    function formatDate(x) {
      if (!x) return '—';
      try { return new Date(x).toLocaleString('vi-VN'); } catch(e) { return x; }
    }

    function refresh() {
      fetch('/api/status')
        .then(r => r.json())
        .then(d => {
          paperStartedAt.textContent = d.paper_started_at ? formatDate(d.paper_started_at) : '—';
          setStatusBadge(d.paper_status || 'stopped');

          const n = d.paper_trades_count || 0;
          const longCt = d.paper_long_count || 0;
          const shortCt = d.paper_short_count || 0;
          const winrate = d.paper_winrate != null ? d.paper_winrate : 0;
          const totalPnl = d.paper_total_pnl != null ? d.paper_total_pnl : 0;
          const balance = d.paper_balance != null ? d.paper_balance : 0;
          statsEl.textContent = 'Tổng số lệnh: ' + n + ' | LONG: ' + longCt + ' | SHORT: ' + shortCt +
            ' | Winrate: ' + winrate + '% | PNL tổng: ' + totalPnl.toFixed(2) + ' USDT | Vốn hiện tại: ' + balance.toFixed(2) + ' USDT';

          const trades = d.paper_trades || [];
          tradesBody.innerHTML = trades.map((t, i) => {
            const profit = parseFloat(t.profit) || 0;
            const capBefore = parseFloat(t.capital_before) || 1;
            const pct = capBefore ? (profit / capBefore * 100).toFixed(2) : '0.00';
            const rowClass = profit >= 0 ? 'profit' : 'loss';
            return '<tr class="' + rowClass + '"><td>' + (i+1) + '</td><td>BTCUSDT</td><td>' + (t.side || '') +
              '</td><td>' + formatDate(t.entry_time) + '</td><td>' + (t.entry_price != null ? parseFloat(t.entry_price).toFixed(2) : '') +
              '</td><td>' + formatDate(t.exit_time) + '</td><td>' + (t.exit_price != null ? parseFloat(t.exit_price).toFixed(2) : '') +
              '</td><td>' + profit.toFixed(2) + '</td><td>' + (profit >= 0 ? '+' : '') + pct + '%</td>' +
              '<td>' + (t.capital_after != null ? parseFloat(t.capital_after).toFixed(2) : '') + '</td><td>' + (t.exit_reason || '') + '</td></tr>';
          }).join('');
        })
        .catch(() => {});
    }

    btnStart.addEventListener('click', () => {
      const cap = parseFloat(capitalInput.value);
      if (!(cap > 0)) { alert('Nhập số vốn > 0'); return; }
      fetch('/api/paper/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ initial_capital: cap }) })
        .then(r => r.json()).then(d => { if (d.ok) refresh(); else alert(d.error || 'Lỗi'); });
    });
    btnPause.addEventListener('click', () => {
      fetch('/api/paper/pause', { method: 'POST' }).then(r => r.json()).then(d => { if (d.ok) refresh(); });
    });
    btnStop.addEventListener('click', () => {
      fetch('/api/paper/stop', { method: 'POST' }).then(r => r.json()).then(d => { if (d.ok) refresh(); });
    });

    refresh();
    setInterval(refresh, 10000);
  </script>
</body>
</html>
"""


def run_web(host=None, port=None):
    from config import settings
    app.run(host=host or settings.WEB_HOST, port=port or settings.WEB_PORT, threaded=True, use_reloader=False)
