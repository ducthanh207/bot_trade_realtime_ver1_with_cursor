(function () {
  const INTERVAL_MS = 5000;
  const ORDERS_REFRESH_MS = 1000;

  /** Playback cursor (chart tab); declared early for klines ticker closure. */
  let playbackIndex = null;

  /* ---------- Tab ---------- */
  function isChartTabActive() {
    const p = document.getElementById("tab-chart");
    return p && p.classList.contains("active");
  }

  let klinesTick = null;
  function startKlinesTicker() {
    if (klinesTick) return;
    klinesTick = setInterval(function () {
      if (isChartTabActive() && playbackIndex === null && typeof fetchKlinesTv === "function") {
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

  function onChartTabShow() {
    if (!tvChartsInited) {
      initChartsTv();
      tvChartsInited = true;
      fetchKlinesTv(true);
    } else {
      fetchKlinesTv(false);
    }
    startKlinesTicker();
    setTimeout(resizeChartsTv, 50);
  }

  function onChartTabHide() {
    stopKlinesTicker();
    stopPlaybackTimer();
  }

  document.querySelectorAll(".tab-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      const tab = btn.getAttribute("data-tab");
      document.querySelectorAll(".tab-btn").forEach(function (b) {
        b.classList.remove("active");
        b.setAttribute("aria-selected", "false");
      });
      btn.classList.add("active");
      btn.setAttribute("aria-selected", "true");
      document.querySelectorAll(".tab-panel").forEach(function (p) {
        p.classList.remove("active");
      });
      const panel = document.getElementById("tab-" + tab);
      if (panel) panel.classList.add("active");
      if (tab === "chart") onChartTabShow();
      else onChartTabHide();
    });
  });

  /* ---------- Paper tab (orders / status) ---------- */
  const capitalInput = document.getElementById("initial_capital");
  const statusBadge = document.getElementById("statusBadge");
  const ordersBody = document.getElementById("ordersBody");
  let lastOrders = [];

  function setStatusBadge(s) {
    statusBadge.textContent = s;
    statusBadge.className = "status-badge ";
    if (s === "running") statusBadge.classList.add("status-running");
    else if (s === "paused") statusBadge.classList.add("status-paused");
    else statusBadge.classList.add("status-stopped");
  }

  function formatDate(x) {
    if (!x) return "—";
    try {
      return new Date(x).toLocaleString("vi-VN", {
        timeZone: "Asia/Bangkok",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (e) {
      return String(x);
    }
  }

  function updateOverview(d) {
    document.getElementById("statStarted").textContent =
      "Bắt đầu: " + (d.paper_started_at ? formatDate(d.paper_started_at) : "—");
    document.getElementById("statTradesDone").textContent =
      "Lệnh đã hoàn thành: " + (d.paper_trades_count || 0);
    document.getElementById("statOrdersOpen").textContent =
      "Lệnh_Open: " + (d.paper_orders_open_count != null ? d.paper_orders_open_count : 0);
    document.getElementById("statWinrate").textContent =
      "Winrate: " + (d.paper_winrate != null ? d.paper_winrate : 0) + "%";
    const pnl = d.paper_total_pnl != null ? d.paper_total_pnl : 0;
    const elPnl = document.getElementById("statPnl");
    elPnl.textContent = "PNL: " + pnl.toFixed(2);
    elPnl.className = "stat " + (pnl >= 0 ? "positive" : "negative");
    const pnlOpen = d.paper_pnl_open != null ? d.paper_pnl_open : 0;
    const elPnlOpen = document.getElementById("statPnlOpen");
    elPnlOpen.textContent = "PNL_Open: " + pnlOpen.toFixed(2);
    elPnlOpen.className = "stat " + (pnlOpen >= 0 ? "positive" : "negative");
    document.getElementById("statBalance").textContent =
      "Vốn: " + (d.paper_balance != null ? d.paper_balance : 0).toFixed(2);
    document.getElementById("statCapitalOpen").textContent =
      "Capital_Open: " +
      (d.paper_capital_open != null ? d.paper_capital_open : d.paper_balance || 0).toFixed(2);
    setStatusBadge(d.paper_status || "stopped");
    var levEl = document.getElementById("inputLeverage");
    var pctEl = document.getElementById("inputWalletPct");
    if (levEl != null) levEl.value = d.paper_leverage_display != null ? Number(d.paper_leverage_display) : 20;
    if (pctEl != null)
      pctEl.value =
        d.paper_wallet_pct_display != null ? Number(d.paper_wallet_pct_display) * 100 : 30;
  }

  function fetchOrders() {
    fetch("/api/orders")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        const orders = data.orders || [];
        lastOrders = orders;
        ordersBody.innerHTML = orders
          .map(function (o, idx) {
            const pnl = o.pnl != null ? o.pnl : 0;
            const rowClass = pnl >= 0 ? "pnl-positive" : "pnl-negative";
            const pnlClass = pnl >= 0 ? "pnl-pos" : "pnl-neg";
            const pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2);
            const pctVal = o.pct_pnl != null ? Number(o.pct_pnl) : null;
            const pctPnl =
              pctVal != null ? (pctVal >= 0 ? "+" : "") + pctVal.toFixed(2) + "%" : "—";
            const pctCapVal = o.pct_pnl_capital != null ? Number(o.pct_pnl_capital) : null;
            const pctPnlCapital =
              pctCapVal != null ? (pctCapVal >= 0 ? "+" : "") + pctCapVal.toFixed(2) + "%" : "—";
            const capAfter = o.capital_after != null ? Number(o.capital_after).toFixed(2) : "—";
            const id = o.is_open ? "•" : o.id != null ? o.id : idx + 1;
            const actionCell = o.is_open
              ? '<td><button type="button" class="btn-close-order" data-open="1">Chốt lệnh</button></td>'
              : "<td></td>";
            return (
              '<tr class="' +
              rowClass +
              '"><td>' +
              id +
              "</td><td>" +
              (o.symbol || "") +
              "</td><td>" +
              (o.side || "") +
              (o.is_open ? " (mở)" : "") +
              "</td><td>" +
              formatDate(o.entry_time) +
              "</td><td>" +
              (o.entry_price != null ? Number(o.entry_price).toFixed(2) : "") +
              "</td><td>" +
              formatDate(o.exit_time) +
              "</td><td>" +
              (o.exit_price != null ? Number(o.exit_price).toFixed(2) : "") +
              '</td><td class="' +
              pnlClass +
              '">' +
              pnlStr +
              '</td><td class="' +
              pnlClass +
              '">' +
              pctPnl +
              '</td><td class="' +
              pnlClass +
              '">' +
              pctPnlCapital +
              "</td><td>" +
              capAfter +
              "</td><td>" +
              (o.exit_reason || "—") +
              "</td>" +
              actionCell +
              "</tr>"
            );
          })
          .join("");
        ordersBody.querySelectorAll(".btn-close-order").forEach(function (btn) {
          btn.addEventListener("click", function () {
            if (!confirm("Chốt lệnh đang mở?")) return;
            fetch("/api/paper/close", { method: "POST" })
              .then(function (r) {
                return r.json();
              })
              .then(function (d) {
                if (d.ok) refresh();
                else alert(d.error || "Lỗi");
              })
              .catch(function () {
                alert("Lỗi kết nối");
              });
          });
        });
        fetch("/api/status")
          .then(function (r) {
            return r.json();
          })
          .then(updateOverview)
          .catch(function () {});
        if (isChartTabActive() && playbackIndex === null && typeof applyMarkersTv === "function") {
          applyMarkersTv();
        }
      })
      .catch(function () {});
  }

  function refresh() {
    fetch("/api/status")
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        updateOverview(d);
        fetchOrders();
      })
      .catch(function () {});
  }

  document.getElementById("btnStart").addEventListener("click", function () {
    const cap = parseFloat(capitalInput.value);
    if (!(cap > 0)) {
      alert("Nhập vốn > 0");
      return;
    }
    fetch("/api/paper/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ initial_capital: cap }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) refresh();
        else alert(d.error || "Lỗi");
      });
  });
  document.getElementById("btnPause").addEventListener("click", function () {
    fetch("/api/paper/pause", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) refresh();
      });
  });
  document.getElementById("btnExportCsv").addEventListener("click", function () {
    window.location.href = "/api/export/csv";
  });
  document.getElementById("btnStop").addEventListener("click", function () {
    fetch("/api/paper/stop", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) refresh();
      });
  });
  document.getElementById("btnClearHistory").addEventListener("click", function () {
    if (!confirm("Xóa toàn bộ lịch sử lệnh? Vốn và trạng thái sẽ reset. Bạn có chắc?")) return;
    fetch("/api/paper/clear-history", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) {
          refresh();
          alert(d.message || "Đã xóa toàn bộ lịch sử lệnh.");
        } else alert(d.error || "Lỗi");
      })
      .catch(function () {
        alert("Lỗi kết nối");
      });
  });
  document.getElementById("btnCapitalRules").addEventListener("click", function () {
    var lev = parseFloat(document.getElementById("inputLeverage").value);
    var pct = parseFloat(document.getElementById("inputWalletPct").value);
    if (isNaN(lev) || lev < 1 || lev > 125) {
      alert("Đòn bẩy phải từ 1 đến 125");
      return;
    }
    if (isNaN(pct) || pct < 1 || pct > 100) {
      alert("% vốn vào lệnh phải từ 1 đến 100");
      return;
    }
    fetch("/api/paper/capital-rules", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ leverage: lev, wallet_pct: pct / 100 }),
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) {
          refresh();
          alert("Đã cập nhật quy tắc vốn.");
        } else alert(d.error || "Lỗi");
      })
      .catch(function () {
        alert("Lỗi kết nối");
      });
  });

  function checkRestorePending() {
    fetch("/api/restore-pending")
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.pending) {
          const keep = confirm(
            "Vừa load lại code. Có lệnh paper đang mở. Bạn có muốn GIỮ vị thế và tiếp tục? (Cancel = Đóng lệnh và bỏ vị thế)"
          );
          fetch("/api/restore-choice", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ keep: keep }),
          })
            .then(function (r) {
              return r.json();
            })
            .then(function () {
              return refresh();
            });
        }
      })
      .catch(function () {});
  }

  /* ---------- Chart tab (TV) ---------- */
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
  let lastLogicalRange = null;

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
    if (!seriesCandle || !lastOrders.length) return;
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
    if (seriesAtr && ind.ATR && ind.ATR.length) {
      seriesAtr.setData(
        times
          .map(function (t, i) {
            return { time: toChartTime(t), value: ind.ATR[i] };
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

    if (chartPrice && (forceFit || timeframeChanged || !hasInitialFit)) {
      chartPrice.timeScale().fitContent();
      if (chartIndicator) chartIndicator.timeScale().fitContent();
      hasInitialFit = true;
    } else if (chartPrice && lastLogicalRange && lastLogicalRange.from != null && lastLogicalRange.to != null) {
      try {
        chartPrice.timeScale().setVisibleLogicalRange(lastLogicalRange);
        if (chartIndicator) chartIndicator.timeScale().setVisibleLogicalRange(lastLogicalRange);
      } catch (e) {}
    }
  }

  function fetchKlinesTv(forceFitContent) {
    if (!chartPrice || !tvChartsInited) return;
    const interval = timeframeSelectTv.value;
    const timeframeChanged = interval !== currentTimeframeTv;
    currentTimeframeTv = interval;

    if (playbackIndex !== null && !forceFitContent) return;

    if (chartPrice && !forceFitContent && !timeframeChanged) {
      try {
        const lr = chartPrice.timeScale().getVisibleLogicalRange();
        if (lr && lr.from != null && lr.to != null) lastLogicalRange = { from: lr.from, to: lr.to };
      } catch (e) {
        lastLogicalRange = null;
      }
    } else if (timeframeChanged) {
      lastLogicalRange = null;
    }

    fetch("/api/klines?interval=" + encodeURIComponent(interval) + "&limit=500")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        fullKlinePayload = data;
        if (playbackIndex !== null) return;
        const ohlc = data.ohlc || [];
        if (!ohlc.length) return;
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
    const rightOffset = 20;
    const opts = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartPriceTv").clientWidth,
      height: document.getElementById("chartPriceTv").clientHeight,
      handleScale: { mouseWheel: true, axisPressedMouseMove: false, pinch: false },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        rightOffset: rightOffset,
        lockVisibleTimeRangeOnResize: false,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: false,
        minBarSpacing: 0.5,
      },
      rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.2 }, borderVisible: true },
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
    seriesAtr = chartPrice.addLineSeries({
      color: "#ab47bc",
      lineWidth: 1,
      priceScaleId: "atr",
      priceLineVisible: false,
    });
    chartPrice.priceScale("atr").applyOptions({ autoScale: true, scaleMargins: { top: 0.4, bottom: 0.4 } });

    const optsInd = {
      layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
      width: document.getElementById("chartIndicatorTv").clientWidth,
      height: document.getElementById("chartIndicatorTv").clientHeight,
      handleScale: { mouseWheel: true, axisPressedMouseMove: false, pinch: false },
      timeScale: {
        timeVisible: true,
        rightOffset: rightOffset,
        lockVisibleTimeRangeOnResize: false,
        rightBarStaysOnScroll: true,
        shiftVisibleRangeOnNewBar: false,
        minBarSpacing: 0.5,
      },
      rightPriceScale: { scaleMargins: { top: 0.1, bottom: 0.1 }, borderVisible: true },
    };
    chartIndicator = LightweightCharts.createChart(document.getElementById("chartIndicatorTv"), optsInd);
    seriesRsi = chartIndicator.addLineSeries({ color: "#e0e0e0", lineWidth: 2 });
    seriesEmaRsi = chartIndicator.addLineSeries({ color: "#26a69a", lineWidth: 2 });
    seriesWmaRsi = chartIndicator.addLineSeries({ color: "#ef5350", lineWidth: 2 });

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
    if (playbackIndex === null) playbackIndex = Math.min(0, len - 1);
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

  /* expose fetchKlinesTv for ticker */
  window.fetchKlinesTv = fetchKlinesTv;
  window.applyMarkersTv = applyMarkersTv;

  /* Boot */
  refresh();
  checkRestorePending();
  setInterval(refresh, INTERVAL_MS);
  setInterval(fetchOrders, ORDERS_REFRESH_MS);
})();
