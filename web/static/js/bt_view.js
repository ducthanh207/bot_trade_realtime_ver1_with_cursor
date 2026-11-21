/* [2026-11-21] Xem kết quả backtest: thống kê + biểu đồ vốn + bảng lệnh. Dùng ở trang Backtest và Chiến lược. */
(function (w) {
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]; }); }
  function num(v, d) { return (v === null || v === undefined || v === "") ? "—" : Number(v).toFixed(d); }
  function money(v) { v = Number(v || 0); return (v >= 0 ? "+" : "") + v.toFixed(2); }
  function tsOf(v) { return new Date(String(v).replace(" ", "T")).getTime(); }
  function vn(t, n) { return new Date(t + 7 * 3600e3).toISOString().slice(0, n).replace("T", " "); }
  function tshort(v) { return v ? vn(tsOf(v), 16) : ""; }

  function stats(d) {
    var tr = d.trades || [], cap0 = Number(d.initial_capital || 0);
    var net = tr.map(function (t) { return Number(t.profit || 0) - Number(t.fee_in || 0); });
    var wn = net.filter(function (x) { return x > 0; }), ls = net.filter(function (x) { return x <= 0; });
    var sum = function (a) { return a.reduce(function (s, x) { return s + x; }, 0); };
    var streak = 0, cur = 0;
    net.forEach(function (x) { cur = x <= 0 ? cur + 1 : 0; streak = Math.max(streak, cur); });
    var longs = tr.filter(function (t) { return t.side === "LONG"; }).length;
    var ret = cap0 ? (Number(d.final_balance) / cap0 - 1) * 100 : 0;
    return [
      ["Lời / lỗ", money(d.total_pnl) + " (" + money(ret) + "%)", ret],
      ["Vốn đầu → cuối", cap0.toFixed(2) + " → " + Number(d.final_balance).toFixed(2), null],
      ["Drawdown lớn nhất", num(d.max_drawdown_pct, 2) + "%", -1],
      ["Số lệnh", tr.length + " (L " + longs + " / S " + (tr.length - longs) + ")", null],
      ["Thắng / thua", (d.wins || 0) + " / " + (d.losses || 0) + " — " + num(d.winrate, 1) + "%", null],
      ["Profit factor", ls.length && sum(ls) < 0 ? (sum(wn) / -sum(ls)).toFixed(2) : "—", null],
      ["Lãi TB lệnh thắng", wn.length ? money(sum(wn) / wn.length) : "—", 1],
      ["Lỗ TB lệnh thua", ls.length ? money(sum(ls) / ls.length) : "—", -1],
      ["Chuỗi thua dài nhất", streak + " lệnh", null]
    ];
  }

  function statsHtml(d) {
    return stats(d).map(function (s) {
      var c = s[2] == null ? "" : (s[2] >= 0 ? "pos" : "neg");
      return "<div class='s'><div class='k'>" + esc(s[0]) + "</div><div class='v " + c + "'>" + esc(s[1]) + "</div></div>";
    }).join("");
  }

  function drawChart(cv, tip, d) {
    var dpr = w.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return;
    cv.width = W * dpr; cv.height = H * dpr;
    var g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
    var cap0 = Number(d.initial_capital || 0);
    var pts = [{t: tsOf(d.start), v: cap0, label: "Bắt đầu"}].concat((d.trades || []).map(function (x) {
      return {t: tsOf(x.exit_time), v: Number(x.capital_after), label: x.side + " " + x.exit_reason + " " + money(Number(x.profit) - Number(x.fee_in || 0))};
    }));
    var padL = 56, padR = 10, padT = 12, padB = 26;
    var t0 = pts[0].t, t1 = Math.max(tsOf(d.end), pts[pts.length - 1].t);
    var vs = pts.map(function (p) { return p.v; });
    var vmin = Math.min.apply(null, vs), vmax = Math.max.apply(null, vs);
    if (vmax - vmin < 1e-9) { vmax += 1; vmin -= 1; }
    var pad = (vmax - vmin) * 0.08; vmin -= pad; vmax += pad;
    var X = function (t) { return padL + (t - t0) / Math.max(1, t1 - t0) * (W - padL - padR); };
    var Y = function (v) { return padT + (vmax - v) / (vmax - vmin) * (H - padT - padB); };
    g.font = "11px sans-serif"; g.fillStyle = "#8a8fa0"; g.strokeStyle = "#242836"; g.lineWidth = 1;
    for (var i = 0; i <= 4; i++) {
      var v = vmin + (vmax - vmin) * i / 4, y = Y(v);
      g.beginPath(); g.moveTo(padL, y); g.lineTo(W - padR, y); g.stroke();
      g.textAlign = "right"; g.fillText(v.toFixed(0), padL - 6, y + 4);
    }
    g.textAlign = "center";
    var nx = W < 520 ? 2 : 4;
    for (var j = 0; j <= nx; j++) {
      var tt = t0 + (t1 - t0) * j / nx;
      g.fillText(vn(tt, 10), Math.min(Math.max(X(tt), padL + 30), W - padR - 30), H - 8);
    }
    g.setLineDash([4, 4]); g.strokeStyle = "#4a4f60"; g.beginPath(); g.moveTo(padL, Y(cap0)); g.lineTo(W - padR, Y(cap0)); g.stroke(); g.setLineDash([]);
    var up = pts[pts.length - 1].v >= cap0;
    g.strokeStyle = up ? "#26a69a" : "#ef5350"; g.lineWidth = 2; g.beginPath();
    pts.forEach(function (p, k) {
      if (k === 0) g.moveTo(X(p.t), Y(p.v));
      else { g.lineTo(X(p.t), Y(pts[k - 1].v)); g.lineTo(X(p.t), Y(p.v)); }
    });
    g.lineTo(X(t1), Y(pts[pts.length - 1].v)); g.stroke();
    function near(clientX) {
      var r = cv.getBoundingClientRect(), mx = clientX - r.left, best = null, bd = 1e9;
      pts.forEach(function (p) { var dd = Math.abs(X(p.t) - mx); if (dd < bd) { bd = dd; best = p; } });
      if (!best || bd > 30) { tip.style.display = "none"; return; }
      tip.textContent = vn(best.t, 16) + " — vốn " + best.v.toFixed(2) + " — " + best.label;
      tip.style.display = "block";
      tip.style.left = Math.max(2, Math.min(mx + 12, W - tip.offsetWidth - 4)) + "px";
      tip.style.top = Math.max(Y(best.v) - 30, 2) + "px";
    }
    cv.onmousemove = function (e) { near(e.clientX); };
    cv.ontouchstart = cv.ontouchmove = function (e) { if (e.touches[0]) near(e.touches[0].clientX); };
    cv.onmouseleave = function () { tip.style.display = "none"; };
  }

  function tradesHtml(d) {
    var tr = (d.trades || []).slice().reverse();
    if (!tr.length) return "<p class='muted'>Không có lệnh nào trong khoảng này.</p>";
    return "<div class='tbl-wrap' style='max-height:360px'><table class='tbl'><tr><th>Side</th><th>Vào</th><th>Giá vào</th><th>Ra</th><th>Giá ra</th>" +
      "<th>Lời/lỗ</th><th>Vốn sau</th><th>Lý do</th></tr>" + tr.map(function (x) {
        var p = Number(x.profit || 0) - Number(x.fee_in || 0);
        return "<tr><td>" + esc(x.side) + "</td><td>" + tshort(x.entry_time) + "</td><td>" + num(x.entry_price, 4) +
          "</td><td>" + tshort(x.exit_time) + "</td><td>" + num(x.exit_price, 4) + "</td><td class='" + (p >= 0 ? "pos" : "neg") + "'>" +
          money(p) + "</td><td>" + num(x.capital_after, 2) + "</td><td>" + esc(x.exit_reason) +
          (x.cycle ? " · " + esc(x.cycle) + (x.cycle_wide ? " (nới)" : "") : "") + "</td></tr>";
      }).join("") + "</table></div>";
  }

  w.BTView = {esc: esc, num: num, money: money, stats: stats, statsHtml: statsHtml, drawChart: drawChart, tradesHtml: tradesHtml, tshort: tshort};
})(window);
