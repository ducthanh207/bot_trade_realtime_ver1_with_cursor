(function () {
  const chart = LightweightCharts.createChart(document.getElementById("chart"), {
    layout: { background: { type: "solid", color: "#131722" }, textColor: "#d1d4dc" },
    grid: { vertLines: { color: "#2a2e39" }, horzLines: { color: "#2a2e39" } },
    rightPriceScale: { borderVisible: true },
    timeScale: { timeVisible: true, secondsVisible: false },
  });

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

  function toChartTime(iso) {
    const d = new Date(iso);
    return Math.floor(d.getTime() / 1000);
  }

  function mapLine(line) {
    return (line || [])
      .map((x) => ({ time: toChartTime(x.time), value: Number(x.value) }))
      .filter((x) => x.time && Number.isFinite(x.value));
  }

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

    const statEl = document.getElementById("stat");
    const tradeCount = Number(pct.trade_count || 0);
    const avgAbs = Number(pct.avg_abs_pct || 0);
    statEl.textContent = "trade_count=" + tradeCount + " | avg_abs_pct=" + avgAbs.toFixed(4) + "%";

    chart.timeScale().fitContent();
  }

  document.getElementById("btnLoad").addEventListener("click", function () {
    loadData().catch((err) => alert("Load error: " + err));
  });

  window.addEventListener("resize", function () {
    const node = document.getElementById("chart");
    chart.applyOptions({ width: node.clientWidth, height: node.clientHeight });
  });

  // first load
  const node = document.getElementById("chart");
  chart.applyOptions({ width: node.clientWidth, height: node.clientHeight });
  loadData().catch(() => {});
})();
