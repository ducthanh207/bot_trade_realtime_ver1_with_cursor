(function () {
  const INTERVAL_MS = 5000;
  const ORDERS_REFRESH_MS = 1000;

  let playbackIndex = null;

  let klinesTick = null;
  function startKlinesTicker() {
    if (klinesTick) return;
    klinesTick = setInterval(function () {
      if (playbackIndex === null && typeof fetchKlinesTv === "function") {
        fetchKlinesTv(false);
      }
    }, INTERVAL_MS);
  }
  function stopKlinesTicker() {
    if (klinesTick) {
      clearInterval(klinesTick);
      klinesTick = null;
    }
  }

  var lastOrdersBySlot = { 1: [], 2: [], 3: [] };
  var lastOrdersJsonBySlot = { 1: "", 2: "", 3: "" };
  function fetchOrdersForSlot(slot) {
    fetch("/api/orders?slot=" + slot)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var orders = data.orders || [];
        var j = "";
        try { j = JSON.stringify(orders); } catch (e) { j = String(Math.random()); }
        if (j === lastOrdersJsonBySlot[slot]) return;
        lastOrdersJsonBySlot[slot] = j;
        lastOrdersBySlot[slot] = orders;
        if (typeof applyMarkersTv === "function") applyMarkersTv();
      })
      .catch(function () {});
  }
  function fetchOrdersForMarkers() {
    fetchOrdersForSlot(1); fetchOrdersForSlot(2); fetchOrdersForSlot(3);
  }
  var lastOrders = [];

  const GMT7_OFFSET_SEC = 7 * 3600;
  const isBrowserUTC = (function () {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone !== "Asia/Bangkok";
    } catch (e) {
      return true;
    }
  })();

  function toChartTime(isoStr) {
    if (!isoStr) return null;
    const d = new Date(isoStr);
    let sec = Math.floor(d.getTime() / 1000);
    if (isBrowserUTC) sec += GMT7_OFFSET_SEC;
    return sec;
  }

  function toUnixSeconds(t) {
    if (t == null) return null;
    if (typeof t === "number" && Number.isFinite(t)) return t;
    if (typeof t === "object" && t.year != null && t.month != null && t.day != null) {
      return Math.floor(Date.UTC(t.year, t.month - 1, t.day, 0, 0, 0) / 1000);
    }
    return null;
  }

  /** Đếm cập nhật time scale từ code (không phải user): chặn subscribe ping-pong. */
  let timeSyncSuppress = 0;

  function runWithTimeSyncSuppressed(fn) {
    timeSyncSuppress++;
    try {
      fn();
    } catch (e) {}
    queueMicrotask(function () {
      timeSyncSuppress--;
      if (timeSyncSuppress < 0) timeSyncSuppress = 0;
    });
  }

  /**
   * Đồng bộ khung nhìn giữa chart giá và chart indicator theo chỉ số nến (logical range).
   * Cùng dữ liệu → kéo chart nào chart kia bám đúng (không lệch như đồng bộ theo time float).
   */
  function logicalRangeNearlyEqual(a, b) {
    if (!a || !b || a.from == null || a.to == null || b.from == null || b.to == null) return false;
    var eps = 0.0005;
    return Math.abs(a.from - b.from) <= eps && Math.abs(a.to - b.to) <= eps;
  }

  function syncPeerLogicalRange(sourceChart, targetChart) {
    if (!sourceChart || !targetChart) return;
    var lr = sourceChart.timeScale().getVisibleLogicalRange();
    if (!lr || lr.from == null || lr.to == null) return;
    var peer = null;
    try {
      peer = targetChart.timeScale().getVisibleLogicalRange();
    } catch (e1) {}
    if (peer && logicalRangeNearlyEqual(peer, lr)) return;
    timeSyncSuppress++;
    try {
      targetChart.timeScale().setVisibleLogicalRange({ from: lr.from, to: lr.to });
    } catch (e2) {}
    queueMicrotask(function () {
      timeSyncSuppress--;
      if (timeSyncSuppress < 0) timeSyncSuppress = 0;
    });
  }

  function estimateAvgBarSec(ohlc) {
    if (!ohlc || ohlc.length < 2) return 300;
    var sum = 0;
    var n = 0;
    for (var i = 1; i < Math.min(ohlc.length, 50); i++) {
      var d = Math.abs(toChartTime(ohlc[i].time) - toChartTime(ohlc[i - 1].time));
      if (d > 0) {
        sum += d;
        n++;
      }
    }
    return n ? sum / n : 300;
  }

  function computeRightOffsetBars() {
    var el = document.getElementById("chartPriceTv");
    var w = el ? el.clientWidth : 900;
    var barW = 6;
    var target = Math.floor((w * 0.42) / barW);
    return Math.max(40, Math.min(120, target));
  }

  /** Chỉ gọi khi: lần đầu, đổi khung, bấm Live — KHÔNG gọi khi poll API. */
  function applyDefaultEndView() {
    if (!chartPrice) return;
    var ro = computeRightOffsetBars();
    runWithTimeSyncSuppressed(function () {
      try {
        var tsPoll = {
          rightOffset: ro,
          barSpacing: 6,
          shiftVisibleRangeOnNewBar: false,
          rightBarStaysOnScroll: false,
        };
        chartPrice.timeScale().applyOptions(tsPoll);
        chartPrice.timeScale().scrollToRealTime();
        if (chartIndicator) {
          chartIndicator.timeScale().applyOptions(tsPoll);
          chartIndicator.timeScale().scrollToRealTime();
        }
      } catch (e) {}
    });
  }

  function captureViewSnapshot() {
    if (!chartPrice || !fullKlinePayload || !fullKlinePayload.ohlc || !fullKlinePayload.ohlc.length) return null;
    try {
      var vr = chartPrice.timeScale().getVisibleRange();
      var lr = chartPrice.timeScale().getVisibleLogicalRange();
      var ohlc = fullKlinePayload.ohlc;
      var n = ohlc.length;
      var lastBarTime = toChartTime(ohlc[n - 1].time);
      if (vr) {
        var from = toUnixSeconds(vr.from);
        var to = toUnixSeconds(vr.to);
        if (from == null || to == null || from >= to) return null;
        return {
          from: from,
          to: to,
          lastBarTime: lastBarTime,
          logicalFrom: lr && lr.from != null ? lr.from : null,
          logicalTo: lr && lr.to != null ? lr.to : null,
          barCount: n,
        };
      }
      if (lr && lr.from != null && lr.to != null && lr.from < lr.to) {
        return {
          from: null,
          to: null,
          lastBarTime: lastBarTime,
          logicalFrom: lr.from,
          logicalTo: lr.to,
          barCount: n,
        };
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  function restoreAfterPoll(ohlc) {
    if (!chartPrice || !ohlc || !ohlc.length) return;
    var snap = pendingViewSnapshot;
    pendingViewSnapshot = null;
    var n = ohlc.length;
    var ro = computeRightOffsetBars();

    function applyRestore() {
      try {
        if (playbackIndex !== null) return;
        runWithTimeSyncSuppressed(function () {
          try {
            var safeOpts = { shiftVisibleRangeOnNewBar: false, rightBarStaysOnScroll: false };
            chartPrice.timeScale().applyOptions(safeOpts);
            if (chartIndicator) chartIndicator.timeScale().applyOptions(safeOpts);
            if (!snap) return;
            if (snap.logicalFrom != null && snap.logicalTo != null) {
              var lf = snap.logicalFrom;
              var lt = snap.logicalTo;
              if (lf < lt) {
                chartPrice.timeScale().setVisibleLogicalRange({ from: lf, to: lt });
                if (chartIndicator) chartIndicator.timeScale().setVisibleLogicalRange({ from: lf, to: lt });
                return;
              }
            }
            if (snap.from != null && snap.to != null) {
              var t0 = toChartTime(ohlc[0].time);
              var t1 = toChartTime(ohlc[ohlc.length - 1].time);
              var from = Math.max(t0, Math.min(t1, snap.from));
              var to = Math.max(from + 1, Math.min(t1, snap.to));
              if (from < to) {
                chartPrice.timeScale().setVisibleRange({ from: from, to: to });
                if (chartIndicator) chartIndicator.timeScale().setVisibleRange({ from: from, to: to });
              }
            }
          } catch (e1) {}
        });
      } catch (e) {}
    }

    applyRestore();
  }

  /** Giữ zoom khi playback: chỉ canh ~N nến cuối slice, không fit toàn bộ. */
  function anchorPlaybackLogicalRange(barCount) {
    if (!chartPrice || !barCount || barCount < 1) return;
    var ro = computeRightOffsetBars();
    var n = barCount;
    var want = 72;
    var from = Math.max(0, n - 1 - want);
    runWithTimeSyncSuppressed(function () {
      try {
        var tsPb = {
          rightOffset: ro,
          barSpacing: 6,
          shiftVisibleRangeOnNewBar: false,
          rightBarStaysOnScroll: false,
        };
        chartPrice.timeScale().applyOptions(tsPb);
        chartPrice.timeScale().setVisibleLogicalRange({ from: from, to: n - 1 });
        if (chartIndicator) {
          chartIndicator.timeScale().applyOptions(tsPb);
          chartIndicator.timeScale().setVisibleLogicalRange({ from: from, to: n - 1 });
        }
      } catch (e) {}
    });
  }

  let chartPrice = null;
  let chartIndicator = null;
  let seriesCandle = null;
  let seriesEma = null;
  let seriesVolume = null;
  let seriesAtr = null;
  let seriesRsi = null;
  let seriesEmaRsi = null;
  let seriesWmaRsi = null;
  let seriesPctUpper = null;
  let seriesPctMid = null;
  let seriesPctLower = null;
  let currentTimeframeTv = "5m";
  let tvChartsInited = false;
  let hasInitialFit = false;
  let pendingViewSnapshot = null;
  let restoreLogicalOnce = null;
  let resizeDebounceTimer = null;

  const CHART_TV_STORAGE_KEY = "atrChartTv_settings_v1";
  const CHART_TOGGLE_IDS = [
    "togVolume",
    "togEma",
    "togPctChange",
    "togRsi",
    "togEmaRsi",
    "togWmaRsi",
    "togAtr",
  ];

  const CrosshairModeNormal =
    typeof LightweightCharts !== "undefined" && LightweightCharts.CrosshairMode != null
      ? LightweightCharts.CrosshairMode.Normal
      : 0;

  function formatLegendPx(x) {
    if (x == null || !Number.isFinite(Number(x))) return "—";
    return Number(x).toFixed(2);
  }

  function findOhlcIndexByChartTime(t) {
    const ohlc = lastRenderedForCrosshair.ohlc || [];
    for (let i = 0; i < ohlc.length; i++) {
      if (toChartTime(ohlc[i].time) === t) return i;
    }
    return -1;
  }

  function updateLegendOhlcFromBar(c, timeSec) {
    const legO = document.getElementById("legO");
    const legH = document.getElementById("legH");
    const legL = document.getElementById("legL");
    const legC = document.getElementById("legC");
    const legDelta = document.getElementById("legDelta");
    if (!legO || !legDelta) return;
    if (!c) {
      legO.textContent = legH.textContent = legL.textContent = legC.textContent = "—";
      legDelta.textContent = "—";
      legDelta.classList.remove("positive", "negative");
      return;
    }
    const o = Number(c.open);
    const h = Number(c.high);
    const l = Number(c.low);
    const cl = Number(c.close);
    legO.textContent = formatLegendPx(o);
    legH.textContent = formatLegendPx(h);
    legL.textContent = formatLegendPx(l);
    legC.textContent = formatLegendPx(cl);
    const ohlc = lastRenderedForCrosshair.ohlc || [];
    const idx = timeSec != null ? findOhlcIndexByChartTime(timeSec) : ohlc.length - 1;
    let chgPct = null;
    if (idx > 0 && ohlc[idx - 1] && ohlc[idx - 1].close != null) {
      const prevC = Number(ohlc[idx - 1].close);
      if (prevC && Number.isFinite(prevC)) chgPct = ((cl - prevC) / prevC) * 100;
    }
    if (chgPct == null && Number.isFinite(o) && o !== 0) {
      chgPct = ((cl - o) / o) * 100;
    }
    if (chgPct != null && Number.isFinite(chgPct)) {
      const sign = chgPct >= 0 ? "+" : "";
      legDelta.textContent = sign + chgPct.toFixed(2) + "%";
      legDelta.classList.toggle("positive", chgPct >= 0);
      legDelta.classList.toggle("negative", chgPct < 0);
    } else {
      legDelta.textContent = "—";
      legDelta.classList.remove("positive", "negative");
    }
  }

  function updateLegendFromCrosshairParam(param) {
    if (!seriesCandle) return;
    if (!param || param.time == null) {
      const ohlc = lastRenderedForCrosshair.ohlc || [];
      const last = ohlc[ohlc.length - 1];
      if (last) updateLegendOhlcFromBar(last, toChartTime(last.time));
      else updateLegendOhlcFromBar(null, null);
      return;
    }
    const pt = param.seriesData && param.seriesData.get(seriesCandle);
    if (pt && pt.open != null && pt.high != null && pt.low != null && pt.close != null) {
      updateLegendOhlcFromBar(pt, param.time);
      return;
    }
    const idx = findOhlcIndexByChartTime(param.time);
    const ohlc = lastRenderedForCrosshair.ohlc || [];
    if (idx >= 0 && ohlc[idx]) updateLegendOhlcFromBar(ohlc[idx], param.time);
    else updateLegendOhlcFromBar(null, null);
  }

  let fullKlinePayload = null;
  let lastRenderedForCrosshair = { ohlc: [], indicators: {} };
  let playbackTimer = null;

  const timeframeSelectTv = document.getElementById("timeframeTv");
  const lookbackPctInput = document.getElementById("lookbackPctTv");
  const chartPriceTitleTv = document.getElementById("chartPriceTitleTv");
  const chartSymbolTitle = document.getElementById("chartSymbolTitle");

  function getLookbackTrades() {
    if (!lookbackPctInput) return 15;
    var n = parseInt(String(lookbackPctInput.value), 10);
    if (!Number.isFinite(n)) n = 15;
    return Math.min(200, Math.max(1, n));
  }

  function loadChartSettingsFromStorage() {
    try {
      var raw = localStorage.getItem(CHART_TV_STORAGE_KEY);
      if (!raw) return null;
      var o = JSON.parse(raw);
      if (!o || typeof o !== "object" || o.version !== 1) return null;
      return o;
    } catch (e) {
      return null;
    }
  }

  function applyChartStorageToDom() {
    var s = loadChartSettingsFromStorage();
    var allowedTf = { "1m": 1, "5m": 1, "15m": 1, "1h": 1, "4h": 1, "1d": 1, "3d": 1 };
    if (s) {
      if (s.timeframe && allowedTf[s.timeframe]) timeframeSelectTv.value = s.timeframe;
      if (s.lookback != null && lookbackPctInput) {
        lookbackPctInput.value = String(Math.min(200, Math.max(1, parseInt(String(s.lookback), 10) || 15)));
      }
      var tg = s.toggles || {};
      CHART_TOGGLE_IDS.forEach(function (id) {
        var el = document.getElementById(id);
        if (el && typeof tg[id] === "boolean") el.checked = tg[id];
      });
      if (s.logicalRange && typeof s.logicalRange.from === "number" && typeof s.logicalRange.to === "number") {
        restoreLogicalOnce = { from: s.logicalRange.from, to: s.logicalRange.to };
      }
    }
    currentTimeframeTv = timeframeSelectTv.value;
  }

  function saveChartSettingsToStorage() {
    var toggles = {};
    CHART_TOGGLE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      toggles[id] = el ? !!el.checked : true;
    });
    var lr = null;
    if (chartPrice) {
      try {
        lr = chartPrice.timeScale().getVisibleLogicalRange();
      } catch (e) {}
    }
    var payload = {
      version: 1,
      timeframe: timeframeSelectTv.value,
      lookback: getLookbackTrades(),
      toggles: toggles,
      logicalRange:
        lr && lr.from != null && lr.to != null ? { from: lr.from, to: lr.to } : null,
      savedAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem(CHART_TV_STORAGE_KEY, JSON.stringify(payload));
    } catch (e) {}
    var btn = document.getElementById("btnChartSave");
    if (btn) {
      var prev = btn.textContent;
      btn.textContent = "Đã lưu";
      btn.disabled = true;
      window.setTimeout(function () {
        btn.textContent = prev;
        btn.disabled = false;
      }, 1600);
    }
  }

  applyChartStorageToDom();

  function stopPlaybackTimer() {
    if (playbackTimer) {
      clearInterval(playbackTimer);
      playbackTimer = null;
    }
  }

  var SLOT_STYLES = {
    1: { entryColor: "#26a69a", exitColor: "#ef5350", entryShape: "arrowUp", exitShape: "arrowDown", label: "P1" },
    2: { entryColor: "#00bcd4", exitColor: "#ff9800", entryShape: "circle", exitShape: "circle", label: "P2" },
    3: { entryColor: "#ffeb3b", exitColor: "#9c27b0", entryShape: "square", exitShape: "square", label: "P3" },
  };
  function isSlotMarkersVisible(slot) {
    var el = document.getElementById("togMarkersP" + slot);
    return el ? el.checked : true;
  }
  function buildMarkersAllSlots() {
    var markers = [];
    [1, 2, 3].forEach(function (slot) {
      if (!isSlotMarkersVisible(slot)) return;
      var st = SLOT_STYLES[slot];
      var orders = lastOrdersBySlot[slot] || [];
      orders.forEach(function (o) {
        var tEntry = o.entry_time ? toChartTime(o.entry_time) : null;
        if (tEntry) markers.push({ time: tEntry, position: o.side === "LONG" ? "belowBar" : "aboveBar", color: o.side === "LONG" ? st.entryColor : st.exitColor, shape: st.entryShape, text: st.label + " In", size: 1 });
        var tExit = o.exit_time ? toChartTime(o.exit_time) : null;
        if (tExit) markers.push({ time: tExit, position: o.side === "LONG" ? "aboveBar" : "belowBar", color: st.exitColor, shape: st.exitShape, text: st.label + " Out", size: 1 });
      });
    });
    markers.sort(function (a, b) { return a.time - b.time; });
    return markers;
  }
  function applyMarkersTv() {
    if (!seriesCandle) return;
    try { seriesCandle.setMarkers(buildMarkersAllSlots()); } catch (e) {}
  }

  function slicePctChangePayload(payload, n) {
    if (!payload.pct_change) return null;
    const pc = payload.pct_change;
    const lines = pc.lines || {};
    const sliceArr = function (arr) {
      return (arr || []).slice(0, n);
    };
    const fullOhlc = payload.ohlc || [];
    const lastTs = n > 0 && fullOhlc[n - 1] ? fullOhlc[n - 1].time : null;
    const lastT = lastTs ? toChartTime(lastTs) : null;
    let trades = pc.trades || [];
    if (lastT != null) {
      trades = trades.filter(function (t) {
        const ex = toChartTime(t.exit_time);
        return ex != null && ex <= lastT;
      });
    }
    return {
      trade_count: pc.trade_count,
      avg_signed_pct: pc.avg_signed_pct,
      avg_abs_pct: pc.avg_abs_pct,
      band_half_width_pct: pc.band_half_width_pct,
      band_half_width_usdt: pc.band_half_width_usdt,
      current_close: pc.current_close,
      upper: pc.upper,
      mid: pc.mid,
      lower: pc.lower,
      lines: {
        upper: sliceArr(lines.upper),
        mid: sliceArr(lines.mid),
        lower: sliceArr(lines.lower),
      },
      trades: trades,
    };
  }

  function slicePayload(payload, n) {
    const ohlc = payload.ohlc.slice(0, n);
    const ind = payload.indicators || {};
    const times = ind.times || payload.ohlc.map(function (c) {
      return c.time;
    });
    const out = { ohlc: ohlc, indicators: { times: times.slice(0, n) } };
    ["RSI", "EMA_RSI", "WMA_RSI", "EMA", "ATR"].forEach(function (k) {
      if (ind[k] && ind[k].length) out.indicators[k] = ind[k].slice(0, n);
    });
    if (payload.pct_change) out.pct_change = slicePctChangePayload(payload, n);
    if (payload.lookback_trades != null) out.lookback_trades = payload.lookback_trades;
    return out;
  }

  function mapPctLine(line) {
    return (line || [])
      .map(function (x) {
        return { time: toChartTime(x.time), value: Number(x.value) };
      })
      .filter(function (x) {
        return x.time != null && Number.isFinite(x.value);
      });
  }

  /** Chỉ giữ điểm trong [nến đầu, nến cuối] — tránh đường %change vẽ thừa sang vùng trống / autoscale lệch. */
  function mapPctLineClampedToOhlc(ohlc, line) {
    if (!ohlc || !ohlc.length) return [];
    var tMin = toChartTime(ohlc[0].time);
    var tMax = toChartTime(ohlc[ohlc.length - 1].time);
    if (tMin == null || tMax == null) return mapPctLine(line);
    var pts = mapPctLine(line).filter(function (x) {
      return x.time >= tMin && x.time <= tMax;
    });
    pts.sort(function (a, b) {
      return a.time - b.time;
    });
    return pts;
  }

  function updateChartPctStat(pc) {
    const statEl = document.getElementById("chartPctChangeStat");
    if (!statEl) return;
    if (!pc) {
      statEl.textContent = "";
      return;
    }
    const halfPct =
      pc.band_half_width_pct != null ? Number(pc.band_half_width_pct) : Number(pc.avg_abs_pct || 0);
    const halfUsdt = pc.band_half_width_usdt != null ? Number(pc.band_half_width_usdt) : null;
    var t = "%change ";
    t += Number.isFinite(halfPct) ? "±" + halfPct.toFixed(4) + "%" : "—";
    if (halfUsdt != null && Number.isFinite(halfUsdt)) t += " (~" + halfUsdt.toFixed(2) + " USDT)";
    statEl.textContent = t;
  }

  function renderPayloadToCharts(data, opts) {
    opts = opts || {};
    const forceFit = opts.forceFit === true;
    const timeframeChanged = opts.timeframeChanged === true;
    lastRenderedForCrosshair = { ohlc: data.ohlc || [], indicators: data.indicators || {} };

    const ohlc = data.ohlc || [];
    const interval = timeframeSelectTv.value;
    chartPriceTitleTv.textContent = "Giá + Volume · " + (data.symbol || "") + " " + interval;
    if (chartSymbolTitle) chartSymbolTitle.textContent = data.symbol || "";

    if (!ohlc.length) {
      chartPriceTitleTv.textContent =
        "Không có nến — kiểm tra kết nối API / Binance · " + (data.symbol || "") + " " + interval;
      pendingViewSnapshot = null;
      updateChartPctStat(null);
      if (seriesPctUpper) {
        seriesPctUpper.setData([]);
        seriesPctMid.setData([]);
        seriesPctLower.setData([]);
      }
      requestAnimationFrame(function () {
        updateLegendFromCrosshairParam({ time: null });
      });
      return;
    }

    const candleData = ohlc.map(function (c) {
      return {
        time: toChartTime(c.time),
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      };
    });
    const volumeData = ohlc
      .map(function (c) {
        return {
          time: toChartTime(c.time),
          value: c.volume != null ? c.volume : 0,
          color: c.close >= c.open ? "rgba(38, 166, 154, 0.5)" : "rgba(239, 83, 80, 0.5)",
        };
      })
      .filter(function (x) {
        return x.time != null && x.value > 0;
      });

    const ind = data.indicators || {};
    const times = ind.times || ohlc.map(function (c) {
      return c.time;
    });

    if (seriesCandle) {
      seriesCandle.setData(candleData);
      seriesCandle.setMarkers(buildMarkersAllSlots());
    }
    if (seriesVolume && volumeData.length) seriesVolume.setData(volumeData);
    if (seriesEma && ind.EMA && ind.EMA.length) {
      seriesEma.setData(
        times
          .map(function (t, i) {
            return { time: toChartTime(t), value: ind.EMA[i] };
          })
          .filter(function (x) {
            return x.time;
          })
      );
    }
    if (seriesAtr && ind.ATR && ind.ATR.length) {
      seriesAtr.setData(
        times
          .map(function (t, i) {
            return { time: toChartTime(t), value: ind.ATR[i] };
          })
          .filter(function (x) {
            return x.time != null;
          })
      );
    }

    const pc = data.pct_change;
    if (seriesPctUpper && pc && pc.lines) {
      const L = pc.lines;
      seriesPctUpper.setData(mapPctLineClampedToOhlc(ohlc, L.upper));
      seriesPctMid.setData(mapPctLineClampedToOhlc(ohlc, L.mid));
      seriesPctLower.setData(mapPctLineClampedToOhlc(ohlc, L.lower));
      updateChartPctStat(pc);
    } else if (seriesPctUpper) {
      seriesPctUpper.setData([]);
      seriesPctMid.setData([]);
      seriesPctLower.setData([]);
      updateChartPctStat(null);
    }

    if (chartIndicator && ind.RSI && ind.RSI.length) {
      const rsiData = times
        .map(function (t, i) {
          return { time: toChartTime(t), value: ind.RSI[i] };
        })
        .filter(function (x) {
          return x.time != null;
        });
      const emaRsiData = (ind.EMA_RSI || []).length
        ? times
            .map(function (t, i) {
              return { time: toChartTime(t), value: ind.EMA_RSI[i] };
            })
            .filter(function (x) {
              return x.time != null;
            })
        : [];
      const wmaRsiData = (ind.WMA_RSI || []).length
        ? times
            .map(function (t, i) {
              return { time: toChartTime(t), value: ind.WMA_RSI[i] };
            })
            .filter(function (x) {
              return x.time != null;
            })
        : [];
      if (seriesRsi) seriesRsi.setData(rsiData);
      if (seriesEmaRsi && emaRsiData.length) seriesEmaRsi.setData(emaRsiData);
      if (seriesWmaRsi && wmaRsiData.length) seriesWmaRsi.setData(wmaRsiData);
    }

    if (playbackIndex !== null) {
      requestAnimationFrame(function () {
        anchorPlaybackLogicalRange(ohlc.length);
      });
      return;
    }

    if (chartPrice && (forceFit || timeframeChanged || !hasInitialFit)) {
      hasInitialFit = true;
      if (restoreLogicalOnce && ohlc.length > 1 && playbackIndex === null) {
        var nBar = ohlc.length;
        var lf = Number(restoreLogicalOnce.from);
        var lt = Number(restoreLogicalOnce.to);
        restoreLogicalOnce = null;
        if (Number.isFinite(lf) && Number.isFinite(lt)) {
          var f = Math.max(0, Math.min(nBar - 1, lf));
          var t = Math.max(0, Math.min(nBar - 1, lt));
          if (f < t) {
            var ro = computeRightOffsetBars();
            runWithTimeSyncSuppressed(function () {
              try {
                chartPrice.timeScale().applyOptions({
                  rightOffset: ro,
                  barSpacing: 6,
                  shiftVisibleRangeOnNewBar: false,
                  rightBarStaysOnScroll: false,
                });
                if (chartIndicator) {
                  chartIndicator.timeScale().applyOptions({
                    rightOffset: ro,
                    barSpacing: 6,
                    shiftVisibleRangeOnNewBar: false,
                    rightBarStaysOnScroll: false,
                  });
                }
                chartPrice.timeScale().setVisibleLogicalRange({ from: f, to: t });
                if (chartIndicator) chartIndicator.timeScale().setVisibleLogicalRange({ from: f, to: t });
              } catch (e) {
                applyDefaultEndView();
              }
            });
          } else {
            applyDefaultEndView();
          }
        } else {
          applyDefaultEndView();
        }
      } else {
        applyDefaultEndView();
      }
    } else if (chartPrice) {
      restoreAfterPoll(ohlc);
    }

    requestAnimationFrame(function () {
      updateLegendFromCrosshairParam({ time: null });
    });
  }

  function fetchKlinesTv(forceFitContent) {
    if (!chartPrice || !tvChartsInited) return;
    const interval = timeframeSelectTv.value;
    const timeframeChanged = interval !== currentTimeframeTv;
    currentTimeframeTv = interval;

    if (playbackIndex !== null && !forceFitContent) return;

    if (chartPrice && !forceFitContent && !timeframeChanged && playbackIndex === null) {
      pendingViewSnapshot = captureViewSnapshot();
    } else {
      pendingViewSnapshot = null;
    }

    var lb = getLookbackTrades();
    function getIndParam(id, def) { var el = document.getElementById(id); if (!el) return def; var v = parseInt(el.value, 10); return Number.isFinite(v) && v >= 2 ? v : def; }
    var qIndParams = "&ema_period=" + getIndParam("indEma", 20) + "&rsi_period=" + getIndParam("indRsi", 14) + "&ema_rsi_period=" + getIndParam("indEmaRsi", 9) + "&wma_rsi_period=" + getIndParam("indWmaRsi", 45) + "&atr_period=" + getIndParam("indAtr", 14);
    fetch(
      "/api/klines?interval=" + encodeURIComponent(interval) + "&limit=500&lookback_trades=" + encodeURIComponent(String(lb)) + qIndParams
    )
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        fullKlinePayload = data;
        if (playbackIndex !== null) return;
        const ohlc = data.ohlc || [];
        if (!ohlc.length) {
          renderPayloadToCharts(data, {
            forceFit: forceFitContent,
            timeframeChanged: timeframeChanged,
          });
          return;
        }
        renderPayloadToCharts(data, {
          forceFit: forceFitContent,
          timeframeChanged: timeframeChanged,
        });
      })
      .catch(function () {});
  }

  function getValueAtTime(time) {
    const ohlc = lastRenderedForCrosshair.ohlc || [];
    const ind = lastRenderedForCrosshair.indicators || {};
    const t = typeof time === "number" ? time : typeof time === "string" ? toChartTime(time) : null;
    if (t == null) return null;
    for (let i = 0; i < ohlc.length; i++) {
      if (toChartTime(ohlc[i].time) === t) {
        const close = ohlc[i].close != null ? Number(ohlc[i].close) : null;
        const rsi = ind.RSI && ind.RSI[i] != null ? Number(ind.RSI[i]) : null;
        return { close: close, rsi: rsi, time: t };
      }
    }
    let best = null;
    let bestDiff = Infinity;
    for (let i = 0; i < ohlc.length; i++) {
      const ct = toChartTime(ohlc[i].time);
      const d = Math.abs(ct - t);
      if (d < bestDiff) {
        bestDiff = d;
        best = {
          close: Number(ohlc[i].close),
          rsi: ind.RSI && ind.RSI[i] != null ? Number(ind.RSI[i]) : null,
          time: ct,
        };
      }
    }
    return best;
  }

  function initChartsTv() {
    var ro = computeRightOffsetBars();
    var tsOpts = {
      timeVisible: true,
      secondsVisible: false,
      rightOffset: ro,
      lockVisibleTimeRangeOnResize: true,
      rightBarStaysOnScroll: false,
      shiftVisibleRangeOnNewBar: false,
      minBarSpacing: 0.8,
      barSpacing: 6,
    };
    const crosshairOpts = {
      mode: CrosshairModeNormal,
      vertLine: {
        width: 1,
        color: "rgba(224, 227, 235, 0.25)",
        style: 2,
        labelBackgroundColor: "#2a2e39",
      },
      horzLine: {
        width: 1,
        color: "rgba(224, 227, 235, 0.25)",
        style: 2,
        labelBackgroundColor: "#2a2e39",
      },
    };
    const opts = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartPriceTv").clientWidth,
      height: document.getElementById("chartPriceTv").clientHeight,
      crosshair: crosshairOpts,
      kineticScroll: { mouse: false, touch: false },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
        axisDoubleClickReset: { time: false, price: false },
      },
      timeScale: tsOpts,
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.22 }, borderVisible: true },
      leftPriceScale: { visible: true, borderVisible: true },
    };
    chartPrice = LightweightCharts.createChart(document.getElementById("chartPriceTv"), opts);
    seriesCandle = chartPrice.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
    });
    seriesCandle.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.35 } });
    seriesEma = chartPrice.addLineSeries({ color: "#f2a900", lineWidth: 2 });
    var pctNoAutoscale = function (_original) {
      return null;
    };
    seriesPctUpper = chartPrice.addLineSeries({
      color: "#42a5f5",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: pctNoAutoscale,
    });
    seriesPctMid = chartPrice.addLineSeries({
      color: "#90a4ae",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: pctNoAutoscale,
    });
    seriesPctLower = chartPrice.addLineSeries({
      color: "#7e57c2",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      autoscaleInfoProvider: pctNoAutoscale,
    });
    seriesVolume = chartPrice.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
    seriesVolume.priceScale().applyOptions({ scaleMargins: { top: 0.7, bottom: 0 }, borderVisible: false });
    seriesAtr = chartPrice.addLineSeries({
      color: "#ab47bc",
      lineWidth: 1,
      priceScaleId: "atr",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartPrice.priceScale("atr").applyOptions({
      position: "left",
      autoScale: true,
      scaleMargins: { top: 0.12, bottom: 0.12 },
      borderVisible: true,
      visible: false,
    });

    const optsInd = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartIndicatorTv").clientWidth,
      height: document.getElementById("chartIndicatorTv").clientHeight,
      crosshair: crosshairOpts,
      kineticScroll: { mouse: false, touch: false },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
        axisDoubleClickReset: { time: false, price: false },
      },
      timeScale: Object.assign({}, tsOpts),
      rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.1 }, borderVisible: true },
    };
    chartIndicator = LightweightCharts.createChart(document.getElementById("chartIndicatorTv"), optsInd);
    seriesRsi = chartIndicator.addLineSeries({ color: "#e0e0e0", lineWidth: 2 });
    seriesEmaRsi = chartIndicator.addLineSeries({ color: "#26a69a", lineWidth: 2 });
    seriesWmaRsi = chartIndicator.addLineSeries({ color: "#ef5350", lineWidth: 2 });

    chartPrice.timeScale().subscribeVisibleLogicalRangeChange(function () {
      if (timeSyncSuppress > 0) return;
      if (!chartIndicator) return;
      syncPeerLogicalRange(chartPrice, chartIndicator);
    });
    chartIndicator.timeScale().subscribeVisibleLogicalRangeChange(function () {
      if (timeSyncSuppress > 0) return;
      if (!chartPrice) return;
      syncPeerLogicalRange(chartIndicator, chartPrice);
    });

    function getCrosshairPoint(series, param) {
      if (!param || param.time == null) return null;
      var pt = param.seriesData && param.seriesData.get(series);
      if (!pt) return null;
      var v = pt.close != null ? pt.close : pt.value;
      return v != null && Number.isFinite(v) ? { time: param.time, value: v } : null;
    }
    function setOtherCrosshair(fromPrice, time, value) {
      if (fromPrice && chartIndicator && seriesRsi && value != null && Number.isFinite(value)) {
        try {
          chartIndicator.setCrosshairPosition(value, time, seriesRsi);
        } catch (e) {}
      } else if (fromPrice && chartIndicator) {
        try {
          chartIndicator.clearCrosshairPosition();
        } catch (e) {}
      } else if (!fromPrice && chartPrice && seriesCandle && value != null && Number.isFinite(value)) {
        try {
          chartPrice.setCrosshairPosition(value, time, seriesCandle);
        } catch (e) {}
      } else if (!fromPrice && chartPrice) {
        try {
          chartPrice.clearCrosshairPosition();
        } catch (e) {}
      }
    }
    chartPrice.subscribeCrosshairMove(function (param) {
      updateLegendFromCrosshairParam(param);
      var pt = getCrosshairPoint(seriesCandle, param);
      if (pt) {
        var at = getValueAtTime(pt.time);
        if (at && at.rsi != null) setOtherCrosshair(true, pt.time, at.rsi);
        else setOtherCrosshair(true, pt.time, null);
      } else {
        if (chartIndicator)
          try {
            chartIndicator.clearCrosshairPosition();
          } catch (e) {}
      }
    });
    chartIndicator.subscribeCrosshairMove(function (param) {
      updateLegendFromCrosshairParam(param);
      var pt = getCrosshairPoint(seriesRsi, param);
      if (pt) {
        var at = getValueAtTime(pt.time);
        if (at && at.close != null) setOtherCrosshair(false, pt.time, at.close);
        else setOtherCrosshair(false, pt.time, null);
      } else {
        if (chartPrice)
          try {
            chartPrice.clearCrosshairPosition();
          } catch (e) {}
      }
    });

    var playbackDblClickLast = 0;
    chartPrice.subscribeClick(function (param) {
      if (!param || param.time == null || !fullKlinePayload || !fullKlinePayload.ohlc) return;
      var now = Date.now();
      if (now - playbackDblClickLast < 450 && playbackDblClickLast > 0) {
        playbackDblClickLast = 0;
      } else {
        playbackDblClickLast = now;
        return;
      }
      const ohlc = fullKlinePayload.ohlc;
      let idx = -1;
      for (let i = 0; i < ohlc.length; i++) {
        if (toChartTime(ohlc[i].time) === param.time) {
          idx = i;
          break;
        }
      }
      if (idx < 0) return;
      playbackIndex = idx;
      stopPlaybackTimer();
      const sliced = slicePayload(fullKlinePayload, playbackIndex + 1);
      renderPayloadToCharts(sliced, { forceFit: false });
    });

    function applyToggles() {
      const v = document.getElementById("togVolume").checked;
      const e = document.getElementById("togEma").checked;
      const pchg = document.getElementById("togPctChange").checked;
      const r = document.getElementById("togRsi").checked;
      const er = document.getElementById("togEmaRsi").checked;
      const wr = document.getElementById("togWmaRsi").checked;
      const a = document.getElementById("togAtr").checked;
      if (seriesVolume) seriesVolume.applyOptions({ visible: v });
      if (seriesEma) seriesEma.applyOptions({ visible: e });
      if (seriesPctUpper) {
        seriesPctUpper.applyOptions({ visible: pchg });
        seriesPctMid.applyOptions({ visible: pchg });
        seriesPctLower.applyOptions({ visible: pchg });
      }
      if (seriesAtr) seriesAtr.applyOptions({ visible: a });
      try {
        if (chartPrice) chartPrice.priceScale("atr").applyOptions({ visible: a });
      } catch (err) {}
      if (seriesRsi) seriesRsi.applyOptions({ visible: r });
      if (seriesEmaRsi) seriesEmaRsi.applyOptions({ visible: er });
      if (seriesWmaRsi) seriesWmaRsi.applyOptions({ visible: wr });
    }
    CHART_TOGGLE_IDS.forEach(function (id) {
      const el = document.getElementById(id);
      if (el) el.addEventListener("change", applyToggles);
    });
    applyToggles();
  }

  function resizeChartsTv() {
    const w = document.getElementById("chartPriceTv").clientWidth;
    const h = document.getElementById("chartPriceTv").clientHeight;
    const wi = document.getElementById("chartIndicatorTv").clientWidth;
    const hi = document.getElementById("chartIndicatorTv").clientHeight;
    if (chartPrice) chartPrice.applyOptions({ width: w, height: h });
    if (chartIndicator) chartIndicator.applyOptions({ width: wi, height: hi });
    // Do NOT reset barSpacing/rightOffset on resize — that overrides user zoom/pan.
  }

  window.addEventListener("resize", function () {
    if (resizeDebounceTimer != null) clearTimeout(resizeDebounceTimer);
    resizeDebounceTimer = setTimeout(function () {
      resizeDebounceTimer = null;
      resizeChartsTv();
    }, 120);
  });

  timeframeSelectTv.addEventListener("change", function () {
    playbackIndex = null;
    stopPlaybackTimer();
    fetchKlinesTv(true);
  });

  if (lookbackPctInput) {
    lookbackPctInput.addEventListener("change", function () {
      var v = getLookbackTrades();
      lookbackPctInput.value = String(v);
      playbackIndex = null;
      stopPlaybackTimer();
      fetchKlinesTv(false);
    });
    lookbackPctInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter") {
        ev.preventDefault();
        lookbackPctInput.blur();
      }
    });
  }

  document.getElementById("btnPlaybackLive").addEventListener("click", function () {
    playbackIndex = null;
    stopPlaybackTimer();
    fetchKlinesTv(true);
  });

  document.getElementById("btnPlaybackStep").addEventListener("click", function () {
    if (!fullKlinePayload || !fullKlinePayload.ohlc) return;
    const len = fullKlinePayload.ohlc.length;
    if (playbackIndex === null) playbackIndex = 0;
    else playbackIndex = Math.min(playbackIndex + 1, len - 1);
    const sliced = slicePayload(fullKlinePayload, playbackIndex + 1);
    renderPayloadToCharts(sliced, { forceFit: false });
  });

  document.getElementById("btnPlaybackPlay").addEventListener("click", function () {
    if (!fullKlinePayload || !fullKlinePayload.ohlc) return;
    const len = fullKlinePayload.ohlc.length;
    if (playbackIndex === null) playbackIndex = 0;
    stopPlaybackTimer();
    playbackTimer = setInterval(function () {
      if (playbackIndex >= len - 1) {
        stopPlaybackTimer();
        return;
      }
      playbackIndex += 1;
      const sliced = slicePayload(fullKlinePayload, playbackIndex + 1);
      renderPayloadToCharts(sliced, { forceFit: false });
    }, 450);
  });

  document.getElementById("btnPlaybackPause").addEventListener("click", function () {
    stopPlaybackTimer();
  });

  var btnChartSave = document.getElementById("btnChartSave");
  if (btnChartSave) {
    btnChartSave.addEventListener("click", function () {
      saveChartSettingsToStorage();
    });
  }

  var btnIndApply = document.getElementById("btnIndApply");
  if (btnIndApply) { btnIndApply.addEventListener("click", function () { playbackIndex = null; stopPlaybackTimer(); fetchKlinesTv(false); }); }
  ["indEma","indRsi","indEmaRsi","indWmaRsi","indAtr"].forEach(function(id) { var el = document.getElementById(id); if (el) el.addEventListener("keydown", function(ev) { if (ev.key === "Enter") { ev.preventDefault(); fetchKlinesTv(false); } }); });
  ["togMarkersP1","togMarkersP2","togMarkersP3"].forEach(function(id) { var el = document.getElementById(id); if (el) el.addEventListener("change", function() { applyMarkersTv(); }); });
  window.fetchKlinesTv = fetchKlinesTv;
  window.applyMarkersTv = applyMarkersTv;

  initChartsTv();
  tvChartsInited = true;
  fetchKlinesTv(true);
  startKlinesTicker();
  setTimeout(resizeChartsTv, 50);
  fetchOrdersForMarkers();
  setInterval(fetchOrdersForMarkers, ORDERS_REFRESH_MS);

  window.addEventListener("pagehide", function () {
    stopKlinesTicker();
    stopPlaybackTimer();
  });
})();
