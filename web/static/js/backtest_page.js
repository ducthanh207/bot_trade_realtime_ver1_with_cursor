/* [2026-11-21] Trang Backtest: chọn đĩa + cặp + thời gian, chạy, theo dõi, lịch sử đã lưu, Excel. */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var V = window.BTView, esc = V.esc;
  var page = $("btPage"), CSRF = page.dataset.csrf, ADMIN = page.dataset.admin === "1";
  var QUICK = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"];
  var disks = [], current = null, watching = {};

  function api(url, body) {
    var o = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": CSRF}, body: JSON.stringify(body)};
    return fetch(url, o).then(function (r) { return r.json().then(function (j) { if (!r.ok && !j.error) j.error = "Lỗi " + r.status; return j; }); });
  }
  function fmt(d) { return d.toISOString().slice(0, 10); }
  function syms() { return $("fSymbols").value.toUpperCase().split(/[\s,;]+/).filter(Boolean); }
  function setSyms(a) { $("fSymbols").value = a.join(", "); drawSymChips(); }

  // ---------- form ----------
  function drawSymChips() {
    var cur = syms();
    $("symChips").innerHTML = QUICK.map(function (s) {
      return "<button type='button' class='chip" + (cur.indexOf(s) >= 0 ? " on" : "") + "' data-s='" + s + "'>" + s.replace("USDT", "") + "</button>";
    }).join("");
  }
  $("symChips").addEventListener("click", function (e) {
    var s = e.target.dataset.s; if (!s) return;
    var cur = syms(), i = cur.indexOf(s);
    if (i >= 0) cur.splice(i, 1); else cur.push(s);
    setSyms(cur);
  });
  $("fSymbols").addEventListener("input", drawSymChips);
  var today = new Date();
  var RANGES = [["30 ngày", 30], ["90 ngày", 90], ["6 tháng", 182], ["1 năm", 365], ["Từ đầu năm", "ytd"]];
  $("rangeChips").innerHTML = RANGES.map(function (r, i) { return "<button type='button' class='chip' data-i='" + i + "'>" + r[0] + "</button>"; }).join("");
  $("rangeChips").addEventListener("click", function (e) {
    var i = e.target.dataset.i; if (i === undefined) return;
    var r = RANGES[i][1], s = new Date(today);
    if (r === "ytd") s = new Date(Date.UTC(today.getUTCFullYear(), 0, 1)); else s.setDate(s.getDate() - r);
    $("fStart").value = fmt(s); $("fEnd").value = fmt(today);
  });
  $("fEnd").value = fmt(today);
  var p30 = new Date(today); p30.setDate(p30.getDate() - 90); $("fStart").value = fmt(p30);

  function loadDisks() {
    return api("/api/disks").then(function (d) {
      disks = d.disks || [];
      var want = new URLSearchParams(location.search).get("disk");
      var dkName = function (x) { return (x.name || "").indexOf(x.short) === 0 ? x.name : x.short + " — " + x.name; };
      var opt = function (x) { return "<option value='" + esc(x.id) + "'>" + esc(dkName(x)) + "</option>"; };
      var bi = disks.filter(function (x) { return x.source === "builtin"; }), up = disks.filter(function (x) { return x.source !== "builtin"; });
      $("fDisk").innerHTML = "<optgroup label='Có sẵn'>" + bi.map(opt).join("") + "</optgroup>" +
        (up.length ? "<optgroup label='Đĩa đã nạp'>" + up.map(opt).join("") + "</optgroup>" : "");
      $("fDisk").value = want && disks.some(function (x) { return x.id === want; }) ? want : "4";
      $("fFilter").innerHTML = "<option value=''>Tất cả chiến lược</option>" + disks.map(function (x) {
        return "<option value='" + esc(x.id) + "'>" + esc(x.short) + "</option>"; }).join("");
    });
  }

  $("btnRun").addEventListener("click", function () {
    var btn = this, msg = $("runMsg");
    if (!$("fStart").value) { msg.textContent = "Chọn ngày bắt đầu"; return; }
    btn.disabled = true; msg.textContent = "Đang gửi...";
    api("/api/backtest/run", {
      method: $("fDisk").value, symbols: syms(), start_date: $("fStart").value, end_date: $("fEnd").value,
      initial_capital: parseFloat($("fCapital").value), leverage: parseFloat($("fLev").value),
      wallet_pct: parseFloat($("fWct").value), params: $("fParams").value
    }).then(function (d) {
      btn.disabled = false;
      if (d.error) { msg.innerHTML = "<span class='neg'>" + esc(d.error) + "</span>"; return; }
      msg.textContent = "Đã gửi " + d.jobs.length + " cặp. Có thể rời trang, kết quả vẫn được lưu.";
      d.jobs.forEach(function (j) { watching[j.job_id] = j.symbol; });
      refresh();
    }).catch(function (e) { btn.disabled = false; msg.textContent = "Lỗi kết nối: " + e; });
  });

  // ---------- lịch sử ----------
  var items = [];
  function label(id) { var d = disks.filter(function (x) { return x.id === id; })[0]; return d ? d.short : id; }
  function drawHist() {
    var f = $("fFilter").value;
    var rows = items.filter(function (x) { return !f || x.method === f; });
    $("histEmpty").style.display = rows.length ? "none" : "";
    $("histTbl").innerHTML = rows.length ? "<tr><th>Lúc chạy</th><th>Chiến lược</th><th>Cặp</th><th>Khoảng ngày</th><th>Lời/lỗ %</th>" +
      "<th>DD max</th><th>Lệnh</th><th>Winrate</th><th>Tham số thử</th></tr>" + rows.map(function (x) {
        var r = Number(x.return_pct || 0), ov = Object.keys(x.overrides || {}).map(function (k) { return k + "=" + x.overrides[k]; }).join(" ");
        return "<tr class='click' data-id='" + esc(x.id) + "'><td>" + new Date(x.saved_at * 1000).toLocaleString("vi-VN", {hour12: false}) +
          "</td><td>" + esc(x.label || label(x.method)) + "</td><td>" + esc(x.symbol) + "</td><td>" + esc(String(x.start).slice(0, 10)) + " → " +
          esc(String(x.end).slice(0, 10)) + "</td><td class='" + (r >= 0 ? "pos" : "neg") + "'>" + V.money(r) + "%</td><td>" + V.num(x.max_drawdown_pct, 1) +
          "%</td><td>" + esc(x.total_trades) + "</td><td>" + V.num(x.winrate, 1) + "%</td><td class='muted'>" + esc(ov) + "</td></tr>";
      }).join("") : "";
  }
  $("fFilter").addEventListener("change", drawHist);
  $("histTbl").addEventListener("click", function (e) {
    var tr = e.target.closest("tr.click"); if (tr) openResult(tr.dataset.id);
  });

  function refresh() {
    return api("/api/backtests").then(function (d) {
      items = d.items || [];
      drawHist();
      var run = d.running || [];
      $("runningCard").style.display = run.length ? "" : "none";
      $("runningList").innerHTML = run.map(function (j) {
        return "<div>" + esc(label(j.method)) + " · " + esc(j.symbol) + " — " + (j.queued ? "đang xếp hàng" : "đang chạy...") + "</div>";
      }).join("");
      // job vừa xong mà mình đang theo dõi → mở kết quả cặp đầu tiên
      Object.keys(watching).forEach(function (id) {
        if (!run.some(function (j) { return j.id === id; })) {
          var done = items.some(function (x) { return x.id === id; }), sym = watching[id];
          delete watching[id];
          if (done && !$("resDrawer").classList.contains("open")) openResult(id);
          else if (!done) api("/api/backtests/" + id).then(function (r) { if (r.error) $("runMsg").innerHTML = "<span class='neg'>" + esc(sym) + ": " + esc(r.error) + "</span>"; });
        }
      });
      var c = d.cache || [];
      $("cacheTbl").innerHTML = c.length ? "<tr><th>Cặp</th><th>Nến 1m từ</th><th>đến</th><th>Số tháng</th><th>1D</th><th>Taker 1H</th><th>MB</th></tr>" +
        c.map(function (x) { return "<tr><td>" + esc(x.symbol) + "</td><td>" + x.from + "</td><td>" + x.to + "</td><td>" + x.months + "</td><td>" +
          (x.daily ? "✓" : "") + "</td><td>" + (x.taker ? "✓" : "") + "</td><td>" + x.mb + "</td></tr>"; }).join("") : "<tr><td class='muted'>Chưa có</td></tr>";
      if (run.length) setTimeout(refresh, 3000);
    });
  }

  // ---------- xem kết quả ----------
  function openResult(id) {
    api("/api/backtests/" + id).then(function (d) {
      if (d.error) { alert(d.error); return; }
      current = {id: id, d: d};
      $("resTitle").textContent = (d.label || "PP" + d.method) + " · " + d.symbol;
      var ov = Object.keys(d.overrides || {}).map(function (k) { return k + "=" + d.overrides[k]; }).join(", ");
      $("resSub").textContent = (d.disk_name || "") + " — " + String(d.start).slice(0, 10) + " → " + String(d.end).slice(0, 10) + (ov ? " — tham số thử: " + ov : "");
      $("resStats").innerHTML = V.statsHtml(d);
      var rs = Object.keys(d.exit_reasons || {}).map(function (k) { return k + ": " + d.exit_reasons[k]; }).join(" · ");
      $("resReasons").textContent = rs ? "Lý do thoát — " + rs : "";
      $("resTrades").innerHTML = V.tradesHtml(d);
      $("resXlsx").href = "/api/backtest/job/" + id + "/xlsx";
      $("resDel").style.display = ADMIN ? "" : "none";
      $("resDrawer").classList.add("open");
      V.drawChart($("resChart"), $("resTip"), d);
    });
  }
  function close() { $("resDrawer").classList.remove("open"); }
  $("resClose").addEventListener("click", close);
  $("resDrawer").addEventListener("click", function (e) { if (e.target === this) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });
  window.addEventListener("resize", function () { if (current && $("resDrawer").classList.contains("open")) V.drawChart($("resChart"), $("resTip"), current.d); });
  $("resDel").addEventListener("click", function () {
    if (!current || !confirm("Xoá kết quả này?")) return;
    api("/api/backtests/" + current.id + "/delete", {}).then(function () { close(); refresh(); });
  });

  drawSymChips();
  loadDisks().then(refresh);
})();
