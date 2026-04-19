/**
 * Hai chart Paper / Paper 2: line vốn, cột profit.
 * Hover chart 1: đường dọc + nhãn ID. Click chart 1/2: gọi onOrderSelect(id).
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
  var SNAP_PX = 36;

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

  function drawLineChart(canvas, wrap, pts, hoverIx) {
    var cssW = Math.max(wrap.clientWidth || 200, 200);
    var cssH = CSS_H;
    hoverIx = hoverIx == null ? -1 : hoverIx;
    if (!pts.length) {
      var ctx0 = setupCtx(canvas, cssW, cssH);
      ctx0.fillStyle = "#2a2e39";
      ctx0.fillRect(0, 0, cssW, cssH);
      ctx0.fillStyle = "#787b86";
      ctx0.font = "12px Segoe UI,sans-serif";
      ctx0.fillText("Chưa có dữ liệu", PAD_L, cssH / 2);
      canvas.style.minWidth = cssW + "px";
      canvas._paperLineMeta = null;
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

    var screenPts = [];
    for (var pi = 0; pi < pts.length; pi++) {
      screenPts.push({
        sx: xScale(pts[pi].t),
        sy: yScale(pts[pi].y),
        rowId: pts[pi].rowId,
        label: pts[pi].label,
      });
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

    if (hoverIx >= 0 && hoverIx < screenPts.length) {
      var hp = screenPts[hoverIx];
      var sx = hp.sx;
      if (sx >= PAD_L && sx <= w - PAD_R) {
        ctx.strokeStyle = "rgba(255,255,255,0.95)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(sx, PAD_T);
        ctx.lineTo(sx, h - PAD_B);
        ctx.stroke();
        var txt =
          hp.rowId == null
            ? "Bắt đầu"
            : hp.rowId === "open"
              ? "ID: Mở"
              : "ID: " + hp.rowId;
        ctx.font = "bold 11px Segoe UI,sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        var tw = ctx.measureText(txt).width;
        var bx = Math.min(Math.max(sx - tw / 2 - 4, 2), w - tw - 10);
        var by = PAD_T + 2;
        ctx.fillStyle = "rgba(0,0,0,0.75)";
        ctx.fillRect(bx, by, tw + 8, 18);
        ctx.fillStyle = "#fff";
        ctx.fillText(txt, bx + 4 + tw / 2, by + 14);
      }
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
    canvas._paperLineMeta = {
      screenPts: screenPts,
      pts: pts,
      w: w,
      h: h,
      wrap: wrap,
      canvas: canvas,
    };
  }

  function drawBarChart(canvas, wrap, bars, highlightRowId) {
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
      canvas._paperBarMeta = null;
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

    var barRects = [];
    for (var i = 0; i < n; i++) {
      var p = bars[i].p;
      var x = PAD_L + BAR_GAP + i * slot;
      var yTop = PAD_T + (1 - (Math.max(p, 0) - vmin) / (vmax - vmin)) * (h - PAD_T - PAD_B);
      var yBot = PAD_T + (1 - (Math.min(p, 0) - vmin) / (vmax - vmin)) * (h - PAD_T - PAD_B);
      var y1 = Math.min(yTop, yBot);
      var y2 = Math.max(yTop, yBot);
      var bh = Math.max(y2 - y1, 1);
      var hl =
        highlightRowId != null && String(bars[i].rowId) === String(highlightRowId);
      ctx.fillStyle = hl
        ? p >= 0
          ? "rgba(100,200,180,1)"
          : "rgba(255,120,120,1)"
        : p >= 0
          ? "rgba(38,166,154,0.85)"
          : "rgba(239,83,80,0.85)";
      ctx.fillRect(x, y1, BAR_W, bh);
      barRects.push({ x0: x, x1: x + BAR_W, y0: PAD_T, y1: h - PAD_B, rowId: bars[i].rowId });
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
    canvas._paperBarMeta = { barRects: barRects, bars: bars, wrap: wrap, canvas: canvas };
  }

  function closedRowId(o, idx) {
    if (o.id != null) return String(o.id);
    return String((o.replay_index != null ? Number(o.replay_index) : idx) + 1);
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
    pts.push({ t: tStart, y: initial, rowId: null, label: "Bắt đầu" });
    for (var i = 0; i < closed.length; i++) {
      var o = closed[i];
      var t = parseTimeMs(o.exit_time);
      if (t == null) t = parseTimeMs(o.entry_time) || tStart + i + 1;
      var y = o.capital_after != null ? Number(o.capital_after) : null;
      if (y == null || !isFinite(y)) continue;
      pts.push({
        t: t,
        y: y,
        rowId: closedRowId(o, i),
        label: "",
      });
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
      if (isFinite(bal))
        pts.push({ t: Date.now(), y: bal, rowId: "open", label: "Mở" });
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
      out.push({
        p: Number(closed[i].pnl) || 0,
        rowId: closedRowId(closed[i], i),
      });
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

  function nearestLinePointIndex(mx, meta) {
    if (!meta || !meta.screenPts || !meta.screenPts.length) return -1;
    var best = -1;
    var bestD = SNAP_PX + 1;
    for (var i = 0; i < meta.screenPts.length; i++) {
      var d = Math.abs(meta.screenPts[i].sx - mx);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    }
    return bestD <= SNAP_PX ? best : -1;
  }

  function barHitRowId(offsetX, offsetY, meta) {
    if (!meta || !meta.barRects) return null;
    for (var i = 0; i < meta.barRects.length; i++) {
      var r = meta.barRects[i];
      if (
        offsetX >= r.x0 &&
        offsetX <= r.x1 &&
        offsetY >= r.y0 &&
        offsetY <= r.y1
      ) {
        return r.rowId;
      }
    }
    return null;
  }

  var _lineHoverIx = -1;
  var _lineRaf = null;
  var _lastLineRedraw = null;
  var _lastBarRedraw = null;
  var _highlightRowId = null;

  function scheduleLineRedraw() {
    if (_lineRaf) return;
    _lineRaf = requestAnimationFrame(function () {
      _lineRaf = null;
      if (typeof _lastLineRedraw === "function") _lastLineRedraw(_lineHoverIx);
    });
  }

  function bindLineInteractions(canvas, wrap, pts) {
    if (canvas.dataset.lineInteractionsBound) return;
    canvas.dataset.lineInteractionsBound = "1";
    canvas.addEventListener("mousemove", function (ev) {
      var meta = canvas._paperLineMeta;
      if (!meta) return;
      var mx = ev.offsetX != null ? ev.offsetX : 0;
      var ix = nearestLinePointIndex(mx, meta);
      if (ix !== _lineHoverIx) {
        _lineHoverIx = ix;
        scheduleLineRedraw();
      }
    });
    canvas.addEventListener("mouseleave", function () {
      if (_lineHoverIx !== -1) {
        _lineHoverIx = -1;
        scheduleLineRedraw();
      }
    });
    canvas.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var meta = canvas._paperLineMeta;
      if (!meta) return;
      var mx = ev.offsetX != null ? ev.offsetX : 0;
      var ix = nearestLinePointIndex(mx, meta);
      if (ix < 0 || !meta.pts[ix]) return;
      var rid = meta.pts[ix].rowId;
      if (rid == null) return;
      if (window.PaperMiniCharts._onOrderSelect)
        window.PaperMiniCharts._onOrderSelect(String(rid));
    });
  }

  function bindBarInteractions(canvas) {
    if (canvas.dataset.barInteractionsBound) return;
    canvas.dataset.barInteractionsBound = "1";
    canvas.addEventListener("click", function (ev) {
      ev.stopPropagation();
      var meta = canvas._paperBarMeta;
      if (!meta) return;
      var ox = ev.offsetX != null ? ev.offsetX : 0;
      var oy = ev.offsetY != null ? ev.offsetY : 0;
      var rid = barHitRowId(ox, oy, meta);
      if (rid == null) return;
      if (window.PaperMiniCharts._onOrderSelect)
        window.PaperMiniCharts._onOrderSelect(String(rid));
    });
  }

  window.PaperMiniCharts = {
    _lastUpdate: null,
    _onOrderSelect: null,
    setOrderSelectHandler: function (fn) {
      this._onOrderSelect = typeof fn === "function" ? fn : null;
    },
    setHighlightRowId: function (id) {
      _highlightRowId = id == null ? null : String(id);
      if (typeof _lastBarRedraw === "function") {
        try {
          _lastBarRedraw();
        } catch (e) {}
      }
    },
    clearHighlight: function () {
      _highlightRowId = null;
      if (typeof _lastBarRedraw === "function") {
        try {
          _lastBarRedraw();
        } catch (e) {}
      }
    },
    update: function (orders, st, opts) {
      opts = opts || {};
      var prefix = opts.prefix || "paper";
      var hiddenMap = opts.hiddenMap || {};
      if (typeof opts.onOrderSelect === "function")
        window.PaperMiniCharts._onOrderSelect = opts.onOrderSelect;
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

      _lastLineRedraw = function (hoverIx) {
        drawLineChart(capCanvas, capWrap, linePts, hoverIx);
        bindLineInteractions(capCanvas, capWrap, linePts);
      };
      _lastBarRedraw = function () {
        drawBarChart(barCanvas, barWrap, bars, _highlightRowId);
        bindBarInteractions(barCanvas);
      };

      _lineHoverIx = -1;
      _lastLineRedraw(-1);
      _lastBarRedraw();

      bindLineInteractions(capCanvas, capWrap, linePts);
      bindBarInteractions(barCanvas);
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
