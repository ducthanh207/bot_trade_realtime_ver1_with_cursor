(function () {
  const chartWrap = document.getElementById("chartWrap");
  const chartEl = document.getElementById("chart");

  const chart = LightweightCharts.createChart(chartEl, {
    layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
    grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
    rightPriceScale: { borderVisible: true },
    timeScale: { timeVisible: true, secondsVisible: false },
    width: chartWrap.clientWidth,
    height: chartWrap.clientHeight,
  });

  const tradeVlines = document.createElement("div");
  tradeVlines.id = "tradeVlines";
  tradeVlines.setAttribute("aria-hidden", "true");
  tradeVlines.style.cssText =
    "position:absolute;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:10;overflow:hidden;";
  chartEl.style.position = "relative";
  chartEl.appendChild(tradeVlines);

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#26a69a",
    downColor: "#ef5350",
    borderVisible: false,
    wickUpColor: "#26a69a",
    wickDownColor: "#ef5350",
  });
  const upperSeries = chart.addLineSeries({ color: "#42a5f5", lineWidth: 2 });
  const midSeries = chart.addLineSeries({ color: "#f2a900", lineWidth: 2 });
  const lowerSeries = chart.addLineSeries({ color: "#ab47bc", lineWidth: 2 });

  /** Trades từ API (entry_time / exit_time ISO) — dùng cho đường dọc */
  let lastTrades = [];

  function toChartTime(iso) {
    if (!iso) return null;
    const d = new Date(iso);
    return Math.floor(d.getTime() / 1000);
  }

  function mapLine(line) {
    return (line || [])
      .map((x) => ({ time: toChartTime(x.time), value: Number(x.value) }))
      .filter((x) => x.time && Number.isFinite(x.value));
  }

  function updateTradeVerticalLines() {
    if (!tradeVlines) return;
    tradeVlines.innerHTML = "";
    const ts = chart.timeScale();
    for (let ti = 0; ti < lastTrades.length; ti++) {
      const t = lastTrades[ti];
      const pairs = [
        [t.entry_time, "#26a69a"],
        [t.exit_time, "#78909c"],
      ];
      for (let pi = 0; pi < pairs.length; pi++) {
        const iso = pairs[pi][0];
        const color = pairs[pi][1];
        if (!iso) continue;
        const tm = toChartTime(iso);
        if (!tm) continue;
        const x = ts.timeToCoordinate(tm);
        if (x == null || x === undefined || !Number.isFinite(x)) continue;
        const line = document.createElement("div");
        line.style.cssText =
          "position:absolute;top:0;bottom:0;width:0;border-left:1px dashed " +
          color +
          ";left:" +
          x +
          "px;opacity:0.9;";
        tradeVlines.appendChild(line);
      }
    }
  }

  chart.timeScale().subscribeVisibleTimeRangeChange(function () {
    updateTradeVerticalLines();
  });

  async function loadData() {
    const symbol = (document.getElementById("symbol").value || "BTCUSDT").trim().toUpperCase();
    const interval = (document.getElementById("interval").value || "5m").trim();
    const lookback = Number(document.getElementById("lookback").value || 15);

    const url =
      "http://127.0.0.1:5055/api/pct-change-avg?symbol=" +
      encodeURIComponent(symbol) +
      "&interval=" +
      encodeURIComponent(interval) +
      "&lookback_trades=" +
      encodeURIComponent(lookback) +
      "&limit=600";

    const res = await fetch(url);
    const data = await res.json();

    const ohlc = (data.ohlc || [])
      .map((c) => ({
        time: toChartTime(c.time),
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      }))
      .filter((x) => x.time && Number.isFinite(x.close));

    candleSeries.setData(ohlc);

    const pct = data.pct_change_avg || {};
    const lines = pct.lines || {};
    upperSeries.setData(mapLine(lines.upper));
    midSeries.setData(mapLine(lines.mid));
    lowerSeries.setData(mapLine(lines.lower));

    lastTrades = Array.isArray(pct.trades) ? pct.trades : [];

    const statEl = document.getElementById("stat");
    const tradeCount = Number(pct.trade_count || 0);
    const halfPct = pct.band_half_width_pct != null ? Number(pct.band_half_width_pct) : Number(pct.avg_abs_pct || 0);
    const halfUsdt = pct.band_half_width_usdt != null ? Number(pct.band_half_width_usdt) : null;
    statEl.textContent =
      "window_trades=" +
      tradeCount +
      " | ±half_width=" +
      (Number.isFinite(halfPct) ? halfPct.toFixed(4) + "%" : "—") +
      " (≈ " +
      (halfUsdt != null && Number.isFinite(halfUsdt) ? halfUsdt.toFixed(2) + " USDT @ last close" : "—") +
      ") | trades=" +
      lastTrades.length;

    chart.timeScale().fitContent();
    requestAnimationFrame(function () {
      requestAnimationFrame(updateTradeVerticalLines);
    });
  }

  document.getElementById("btnLoad").addEventListener("click", function () {
    loadData().catch(function (err) {
      alert("Load error: " + err);
    });
  });

  window.addEventListener("resize", function () {
    chart.applyOptions({ width: chartWrap.clientWidth, height: chartWrap.clientHeight });
    requestAnimationFrame(updateTradeVerticalLines);
  });

  chart.applyOptions({ width: chartWrap.clientWidth, height: chartWrap.clientHeight });
  loadData().catch(function () {});
})();
