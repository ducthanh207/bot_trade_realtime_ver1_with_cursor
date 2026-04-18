/**
 * Hai biểu đồ nhỏ trên trang Paper / Paper 2: vốn theo thời gian (line), profit từng lệnh (cột).
 * Gọi PaperMiniCharts.update(orders, status, { prefix, hiddenMap }) sau mỗi lần có dữ liệu mới.
 */
(function () {
  var CSS_H = 150;
  var PAD_L = 40;
  var PAD_R = 10;
  var PAD_T = 14;
  var PAD_B = 26;
  var BAR_W = 12;
  var BAR_GAP = 6;
  var MIN_LINE_W_PER_PT = 8;

  function orderIsOpen(o) {
    return !!o && (o.is_open === true || o.is_open === 1);
  }

  function sk(st, prefix, name) {
    if (!st) return null;
    return st[prefix + "_" + name];
  }

  function parseTimeMs(v) {
    if (v == null) return null;
    if (typeof v === "number" && isFinite(v)) return v;
    try {
      var d = new Date(v);
      var t = d.getTime();
      return isNaN(t) ? null : t;
    } catch (e) {
      return null;
    }
  }

  function chronologicalVisibleClosed(orders, hiddenMap) {
    var hm = hiddenMap || {};
    var closed = [];
    for (var i = 0; i < orders.length; i++) {
      var o = orders[i];
      if (orderIsOpen(o)) continue;
      var tk = String(o.trade_key || "");
      if (tk && hm[tk]) continue;
      closed.push(o);
    }
    closed.sort(function (a, b) {
      return (Number(a.replay_index) || 0) - (Number(b.replay_index) || 0);
    });
    return closed;
  }

  function setupCtx(canvas, cssW, cssH) {
    var dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(cssW * dpr));
    canvas.height = Math.max(1, Math.floor(cssH * dpr));
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    var ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return ctx;
  }

  function drawLineChart(canvas, wrap, pts) {
    var cssW = Math.max(wrap.clientWidth || 200, 200);
    var cssH = CSS_H;
    if (!pts.length) {
      var ctx0 = setupCtx(canvas, cssW, cssH);
      ctx0.fillStyle = "#2a2e39";
      ctx0.fillRect(0, 0, cssW, cssH);
      ctx0.fillStyle = "#787b86";
      ctx0.font = "12px Segoe UI,sans-serif";
      ctx0.fillText("Chưa có dữ liệu", PAD_L, cssH / 2);
      canvas.style.minWidth = cssW + "px";
      return;
    }
    var contentW = Math.max(cssW, pts.length * MIN_LINE_W_PER_PT + PAD_L + PAD_R);
    var ctx = setupCtx(canvas, contentW, cssH);
    var w = contentW;
    var h = cssH;
    var xs = pts.map(function (p) {
      return p.t;
    });
    var ys = pts.map(function (p) {
      return p.y;
    });
    var xmin = Math.min.apply(null, xs);
    var xmax = Math.max.apply(null, xs);
    if (xmax <= xmin) xmax = xmin + 1;
    var ymin = Math.min.apply(null, ys);
    var ymax = Math.max.apply(null, ys);
    if (ymax <= ymin) {
      ymin -= 1;
      ymax += 1;
    }
    var padY = (ymax - ymin) * 0.08 || 1;
    ymin -= padY;
    ymax += padY;

    function xScale(t) {
      return PAD_L + ((t - xmin) / (xmax - xmin)) * (w - PAD_L - PAD_R);
    }
    function yScale(v) {
      return PAD_T + (1 - (v - ymin) / (ymax - ymin)) * (h - PAD_T - PAD_B);
    }

    ctx.fillStyle = "#131722";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#363a45";
    ctx.lineWidth = 1;
    for (var g = 0; g <= 4; g++) {
      var gy = PAD_T + (g / 4) * (h - PAD_T - PAD_B);
      ctx.beginPath();
      ctx.moveTo(PAD_L, gy);
      ctx.lineTo(w - PAD_R, gy);
      ctx.stroke();
    }
    ctx.fillStyle = "#787b86";
    ctx.font = "10px Segoe UI,sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var g2 = 0; g2 <= 4; g2++) {
      var vv = ymax - (g2 / 4) * (ymax - ymin);
      ctx.fillText(vv.toFixed(0), PAD_L - 4, PAD_T + (g2 / 4) * (h - PAD_T - PAD_B));
    }

    ctx.strokeStyle = "#2962ff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (var i = 0; i < pts.length; i++) {
      var px = xScale(pts[i].t);
      var py = yScale(pts[i].y);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.fillStyle = "#2962ff";
    for (var j = 0; j < pts.length; j++) {
      ctx.beginPath();
      ctx.arc(xScale(pts[j].t), yScale(pts[j].y), 3, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.fillStyle = "#787b86";
    ctx.font = "10px Segoe UI,sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var t0 = new Date(xmin).toLocaleString("vi-VN", {
      timeZone: "Asia/Bangkok",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    var t1 = new Date(xmax).toLocaleString("vi-VN", {
      timeZone: "Asia/Bangkok",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
    ctx.fillText(t0, PAD_L + 40, h - PAD_B + 2);
    ctx.fillText(t1, w - PAD_R - 40, h - PAD_B + 2);

    canvas.style.minWidth = contentW + "px";
  }

  function drawBarChart(canvas, wrap, bars) {
    var cssW = Math.max(wrap.clientWidth || 200, 200);
    var cssH = CSS_H;
    if (!bars.length) {
      var ctxE = setupCtx(canvas, cssW, cssH);
      ctxE.fillStyle = "#2a2e39";
      ctxE.fillRect(0, 0, cssW, cssH);
      ctxE.fillStyle = "#787b86";
      ctxE.font = "12px Segoe UI,sans-serif";
      ctxE.fillText("Chưa có lệnh đóng", PAD_L, cssH / 2);
      canvas.style.minWidth = cssW + "px";
      return;
    }
    var n = bars.length;
    var slot = BAR_W + BAR_GAP;
    var contentW = Math.max(cssW, PAD_L + n * slot + BAR_GAP + PAD_R);
    var ctx = setupCtx(canvas, contentW, cssH);
    var w = contentW;
    var h = cssH;
    var vals = bars.map(function (b) {
      return b.p;
    });
    var vmin = Math.min(0, Math.min.apply(null, vals));
    var vmax = Math.max(0, Math.max.apply(null, vals));
    if (vmax <= vmin) {
      vmin -= 1;
      vmax += 1;
    }
    var padV = (vmax - vmin) * 0.08 || 1;
    vmin -= padV;
    vmax += padV;
    var zeroY =
      PAD_T + (1 - (0 - vmin) / (vmax - vmin)) * (h - PAD_T - PAD_B);

    ctx.fillStyle = "#131722";
    ctx.fillRect(0, 0, w, h);
    ctx.strokeStyle = "#363a45";
    ctx.beginPath();
    ctx.moveTo(PAD_L, zeroY);
    ctx.lineTo(w - PAD_R, zeroY);
    ctx.stroke();

    for (var i = 0; i < n; i++) {
      var p = bars[i].p;
      var x = PAD_L + BAR_GAP + i * slot;
      var yTop = PAD_T + (1 - (Math.max(p, 0) - vmin) / (vmax - vmin)) * (h - PAD_T - PAD_B);
      var yBot = PAD_T + (1 - (Math.min(p, 0) - vmin) / (vmax - vmin)) * (h - PAD_T - PAD_B);
      var y1 = Math.min(yTop, yBot);
      var y2 = Math.max(yTop, yBot);
      var bh = Math.max(y2 - y1, 1);
      ctx.fillStyle = p >= 0 ? "rgba(38,166,154,0.85)" : "rgba(239,83,80,0.85)";
      ctx.fillRect(x, y1, BAR_W, bh);
    }

    ctx.fillStyle = "#787b86";
    ctx.font = "9px Segoe UI,sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var labStep = Math.max(1, Math.ceil(n / 14));
    for (var j = 0; j < n; j++) {
      if (j % labStep === 0 || j === n - 1) {
        var lx = PAD_L + BAR_GAP + j * slot + BAR_W / 2;
        ctx.fillText(String(j + 1), lx, h - PAD_B + 2);
      }
    }

    ctx.fillStyle = "#787b86";
    ctx.font = "10px Segoe UI,sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var g = 0; g <= 4; g++) {
      var vv = vmax - (g / 4) * (vmax - vmin);
      ctx.fillText(vv.toFixed(0), PAD_L - 2, PAD_T + (g / 4) * (h - PAD_T - PAD_B));
    }

    canvas.style.minWidth = contentW + "px";
  }

  function buildCapitalPoints(orders, st, prefix, hiddenMap) {
    var closed = chronologicalVisibleClosed(orders, hiddenMap);
    var pts = [];
    var ri = sk(st, prefix, "replay_initial");
    var ic = sk(st, prefix, "initial_capital");
    var initial = Number(ri);
    if (!isFinite(initial) || initial <= 0) initial = Number(ic) || 0;
    var tStart = parseTimeMs(sk(st, prefix, "started_at"));
    if (tStart == null) tStart = Date.now();
    pts.push({ t: tStart, y: initial });
    for (var i = 0; i < closed.length; i++) {
      var o = closed[i];
      var t = parseTimeMs(o.exit_time);
      if (t == null) t = parseTimeMs(o.entry_time) || tStart + i + 1;
      var y = o.capital_after != null ? Number(o.capital_after) : null;
      if (y == null || !isFinite(y)) continue;
      pts.push({ t: t, y: y });
    }
    var openRow = null;
    for (var j = 0; j < orders.length; j++) {
      if (orderIsOpen(orders[j])) {
        openRow = orders[j];
        break;
      }
    }
    if (openRow) {
      var bal = Number(sk(st, prefix, "balance"));
      if (isFinite(bal)) pts.push({ t: Date.now(), y: bal });
    }
    pts.sort(function (a, b) {
      return a.t - b.t;
    });
    return pts;
  }

  function buildProfitBars(orders, hiddenMap) {
    var closed = chronologicalVisibleClosed(orders, hiddenMap);
    var out = [];
    for (var i = 0; i < closed.length; i++) {
      out.push({ p: Number(closed[i].pnl) || 0 });
    }
    return out;
  }

  function bindWheelPan(scrollEl) {
    if (!scrollEl || scrollEl.dataset.wheelPanBound) return;
    scrollEl.dataset.wheelPanBound = "1";
    scrollEl.addEventListener(
      "wheel",
      function (ev) {
        if (Math.abs(ev.deltaY) > Math.abs(ev.deltaX)) {
          ev.preventDefault();
          scrollEl.scrollLeft += ev.deltaY;
        }
      },
      { passive: false }
    );
  }

  window.PaperMiniCharts = {
    _lastUpdate: null,
    update: function (orders, st, opts) {
      opts = opts || {};
      var prefix = opts.prefix || "paper";
      var hiddenMap = opts.hiddenMap || {};
      window.PaperMiniCharts._lastUpdate = [orders || [], st, opts];
      var capCanvas = document.getElementById("paperChartCapital");
      var barCanvas = document.getElementById("paperChartProfit");
      var capWrap = document.getElementById("paperChartCapitalScroll");
      var barWrap = document.getElementById("paperChartProfitScroll");
      if (!capCanvas || !barCanvas || !capWrap || !barWrap) return;

      bindWheelPan(capWrap);
      bindWheelPan(barWrap);

      var linePts = buildCapitalPoints(orders || [], st, prefix, hiddenMap);
      var bars = buildProfitBars(orders || [], hiddenMap);
      drawLineChart(capCanvas, capWrap, linePts);
      drawBarChart(barCanvas, barWrap, bars);
    },
  };

  var _resizeT = null;
  window.addEventListener("resize", function () {
    clearTimeout(_resizeT);
    _resizeT = setTimeout(function () {
      var u = window.PaperMiniCharts._lastUpdate;
      if (u && typeof window.PaperMiniCharts.update === "function") {
        window.PaperMiniCharts.update(u[0], u[1], u[2]);
      }
    }, 120);
  });
})();

