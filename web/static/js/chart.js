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

  let lastOrders = [];
  function fetchOrdersForMarkers() {
    fetch("/api/orders")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        lastOrders = data.orders || [];
        if (typeof applyMarkersTv === "function") applyMarkersTv();
      })
      .catch(function () {});
  }

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

  /** getVisibleRange có thể trả UTCTimestamp (số) hoặc BusinessDay — chuẩn hóa về giây Unix. */
  function toUnixSeconds(t) {
    if (t == null) return null;
    if (typeof t === "number" && Number.isFinite(t)) return t;
    if (typeof t === "object" && t.year != null && t.month != null && t.day != null) {
      return Math.floor(Date.UTC(t.year, t.month - 1, t.day, 0, 0, 0) / 1000);
    }
    return null;
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

  function captureViewSnapshot() {
    if (!chartPrice || !fullKlinePayload || !fullKlinePayload.ohlc || !fullKlinePayload.ohlc.length) return null;
    try {
      var vr = chartPrice.timeScale().getVisibleRange();
      var lr = chartPrice.timeScale().getVisibleLogicalRange();
      if (!vr) return null;
      var from = toUnixSeconds(vr.from);
      var to = toUnixSeconds(vr.to);
      if (from == null || to == null || from >= to) return null;
      var ohlc = fullKlinePayload.ohlc;
      var n = ohlc.length;
      var avg = estimateAvgBarSec(ohlc);
      var atRight = false;
      if (lr && lr.to != null && n > 0) {
        atRight = lr.to >= n - 1.85;
      } else {
        var lastT = toChartTime(ohlc[n - 1].time);
        atRight = lastT - to <= avg * 4;
      }
      return { from: from, to: to, atRight: atRight, avgBarSec: avg };
    } catch (e) {
      return null;
    }
  }

  /** Khoảng trống bên phải (đơn vị “nến”) giống Binance/TradingView — không dán nến mới vào mép phải. */
  function computeRightOffsetBars() {
    var el = document.getElementById("chartPriceTv");
    var w = el ? el.clientWidth : 900;
    var barW = 6;
    var target = Math.floor((w * 0.45) / barW);
    return Math.max(48, Math.min(140, target));
  }

  function applyTradingViewEndScroll() {
    if (!chartPrice) return;
    var ro = computeRightOffsetBars();
    try {
      chartPrice.timeScale().applyOptions({ rightOffset: ro, barSpacing: 6 });
      chartPrice.timeScale().scrollToRealTime();
      if (chartIndicator) {
        chartIndicator.timeScale().applyOptions({ rightOffset: ro, barSpacing: 6 });
        chartIndicator.timeScale().scrollToRealTime();
      }
    } catch (e) {}
  }

  function restoreAfterDataUpdate(ohlc) {
    if (!chartPrice || !ohlc || !ohlc.length) return;
    var snap = pendingViewSnapshot;
    pendingViewSnapshot = null;
    if (!snap) return;
    var t0 = toChartTime(ohlc[0].time);
    var t1 = toChartTime(ohlc[ohlc.length - 1].time);
    var avg = snap.avgBarSec || estimateAvgBarSec(ohlc);
    var minSpan = avg * 28;

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        try {
          if (playbackIndex !== null) return;
          if (snap.atRight) {
            applyTradingViewEndScroll();
            return;
          }
          var from = snap.from;
          var to = snap.to;
          if (to - from < minSpan) {
            var mid = (from + to) / 2;
            from = mid - minSpan / 2;
            to = mid + minSpan / 2;
          }
          from = Math.max(t0, Math.min(from, t1));
          to = Math.max(t0, Math.min(to, t1));
          if (from >= to) {
            applyTradingViewEndScroll();
            return;
          }
          chartPrice.timeScale().setVisibleRange({ from: from, to: to });
          if (chartIndicator) chartIndicator.timeScale().setVisibleRange({ from: from, to: to });
        } catch (e) {}
      });
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
  let currentTimeframeTv = "5m";
  let tvChartsInited = false;
  let hasInitialFit = false;
  let syncingVisibleRange = false;
  /** Khôi phục viewport sau poll API (theo thời gian, không dùng logical range — tránh co nến cực rộng). */
  let pendingViewSnapshot = null;

  let fullKlinePayload = null;
  let lastRenderedForCrosshair = { ohlc: [], indicators: {} };
  let playbackTimer = null;

  const timeframeSelectTv = document.getElementById("timeframeTv");
  const chartPriceTitleTv = document.getElementById("chartPriceTitleTv");
  const chartSymbolTitle = document.getElementById("chartSymbolTitle");

  function stopPlaybackTimer() {
    if (playbackTimer) {
      clearInterval(playbackTimer);
      playbackTimer = null;
    }
  }

  function buildMarkers(orders) {
    const markers = [];
    (orders || []).forEach(function (o) {
      const tEntry = o.entry_time ? toChartTime(o.entry_time) : null;
      if (tEntry)
        markers.push({
          time: tEntry,
          position: o.side === "LONG" ? "belowBar" : "aboveBar",
          color: o.side === "LONG" ? "#26a69a" : "#ef5350",
          shape: "arrowUp",
          text: "Vào",
        });
      const tExit = o.exit_time ? toChartTime(o.exit_time) : null;
      if (tExit)
        markers.push({
          time: tExit,
          position: o.side === "LONG" ? "aboveBar" : "belowBar",
          color: "#787b86",
          shape: "arrowDown",
          text: "Ra",
        });
    });
    return markers;
  }

  function applyMarkersTv() {
    if (!seriesCandle || !lastOrders.length) {
      if (seriesCandle)
        try {
          seriesCandle.setMarkers([]);
        } catch (e) {}
      return;
    }
    try {
      seriesCandle.setMarkers(buildMarkers(lastOrders));
    } catch (e) {}
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
    return out;
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
      seriesCandle.setMarkers(buildMarkers(lastOrders));
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
    if (chartIndicator && seriesAtr && ind.ATR && ind.ATR.length) {
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

    if (playbackIndex !== null) {
      try {
        chartPrice.timeScale().applyOptions({ rightOffset: 28, barSpacing: 6 });
        chartPrice.timeScale().scrollToRealTime();
        if (chartIndicator) {
          chartIndicator.timeScale().applyOptions({ rightOffset: 28, barSpacing: 6 });
          chartIndicator.timeScale().scrollToRealTime();
        }
      } catch (e) {}
      return;
    }

    if (chartPrice && (forceFit || timeframeChanged || !hasInitialFit)) {
      hasInitialFit = true;
      applyTradingViewEndScroll();
    } else if (chartPrice) {
      restoreAfterDataUpdate(ohlc);
    }
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

    fetch("/api/klines?interval=" + encodeURIComponent(interval) + "&limit=500")
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
    const rightOffset = computeRightOffsetBars();
    const opts = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartPriceTv").clientWidth,
      height: document.getElementById("chartPriceTv").clientHeight,
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
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        rightOffset: rightOffset,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: true,
        minBarSpacing: 0.8,
        barSpacing: 6,
      },
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.22 }, borderVisible: true },
    };
    chartPrice = LightweightCharts.createChart(document.getElementById("chartPriceTv"), opts);
    seriesCandle = chartPrice.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
    });
    seriesCandle.priceScale().applyOptions({ scaleMargins: { top: 0.1, bottom: 0.35 } });
    seriesEma = chartPrice.addLineSeries({ color: "#f2a900", lineWidth: 2 });
    seriesVolume = chartPrice.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "" });
    seriesVolume.priceScale().applyOptions({ scaleMargins: { top: 0.7, bottom: 0 }, borderVisible: false });

    const optsInd = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartIndicatorTv").clientWidth,
      height: document.getElementById("chartIndicatorTv").clientHeight,
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
      },
      timeScale: {
        timeVisible: true,
        rightOffset: rightOffset,
        lockVisibleTimeRangeOnResize: true,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: true,
        minBarSpacing: 0.8,
        barSpacing: 6,
      },
      rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.1 }, borderVisible: true },
      leftPriceScale: { visible: true, borderVisible: true },
    };
    chartIndicator = LightweightCharts.createChart(document.getElementById("chartIndicatorTv"), optsInd);
    seriesRsi = chartIndicator.addLineSeries({ color: "#e0e0e0", lineWidth: 2 });
    seriesEmaRsi = chartIndicator.addLineSeries({ color: "#26a69a", lineWidth: 2 });
    seriesWmaRsi = chartIndicator.addLineSeries({ color: "#ef5350", lineWidth: 2 });
    seriesRsi.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.4 } });
    seriesAtr = chartIndicator.addLineSeries({
      color: "#ab47bc",
      lineWidth: 1,
      priceScaleId: "atr",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartIndicator.priceScale("atr").applyOptions({
      position: "left",
      autoScale: true,
      scaleMargins: { top: 0.58, bottom: 0.08 },
      borderVisible: true,
    });

    chartPrice.timeScale().subscribeVisibleTimeRangeChange(function () {
      if (syncingVisibleRange) return;
      const range = chartPrice.timeScale().getVisibleRange();
      if (!range || !chartIndicator) return;
      syncingVisibleRange = true;
      try {
        chartIndicator.timeScale().setVisibleRange(range);
      } catch (e) {}
      syncingVisibleRange = false;
    });
    chartIndicator.timeScale().subscribeVisibleTimeRangeChange(function () {
      if (syncingVisibleRange) return;
      const range = chartIndicator.timeScale().getVisibleRange();
      if (!range || !chartPrice) return;
      syncingVisibleRange = true;
      try {
        chartPrice.timeScale().setVisibleRange(range);
      } catch (e) {}
      syncingVisibleRange = false;
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

    chartPrice.subscribeClick(function (param) {
      if (!param || param.time == null || !fullKlinePayload || !fullKlinePayload.ohlc) return;
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
      renderPayloadToCharts(sliced, { forceFit: true });
    });

    function applyToggles() {
      const v = document.getElementById("togVolume").checked;
      const e = document.getElementById("togEma").checked;
      const r = document.getElementById("togRsi").checked;
      const er = document.getElementById("togEmaRsi").checked;
      const wr = document.getElementById("togWmaRsi").checked;
      const a = document.getElementById("togAtr").checked;
      if (seriesVolume) seriesVolume.applyOptions({ visible: v });
      if (seriesEma) seriesEma.applyOptions({ visible: e });
      if (seriesAtr) seriesAtr.applyOptions({ visible: a });
      if (seriesRsi) seriesRsi.applyOptions({ visible: r });
      if (seriesEmaRsi) seriesEmaRsi.applyOptions({ visible: er });
      if (seriesWmaRsi) seriesWmaRsi.applyOptions({ visible: wr });
    }
    ["togVolume", "togEma", "togRsi", "togEmaRsi", "togWmaRsi", "togAtr"].forEach(function (id) {
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
    if (playbackIndex === null && chartPrice) {
      var ro = computeRightOffsetBars();
      try {
        chartPrice.timeScale().applyOptions({ rightOffset: ro });
        if (chartIndicator) chartIndicator.timeScale().applyOptions({ rightOffset: ro });
      } catch (e) {}
    }
  }

  window.addEventListener("resize", function () {
    resizeChartsTv();
  });

  timeframeSelectTv.addEventListener("change", function () {
    playbackIndex = null;
    stopPlaybackTimer();
    fetchKlinesTv(true);
  });

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
