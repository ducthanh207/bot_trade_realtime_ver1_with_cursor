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
  // [2026-11-22] Lọc (chiến lược, cặp, lãi/lỗ, khoảng ngày, số lệnh, chữ) + bấm tiêu đề cột để sắp xếp.
  var items = [], restored = false;
  function label(id) { var d = disks.filter(function (x) { return x.id === id; })[0]; return d ? d.short : id; }
  function d10(v) { return String(v == null ? "" : v).slice(0, 10); }
  function ovText(x) { return Object.keys(x.overrides || {}).map(function (k) { return k + "=" + x.overrides[k]; }).join(" "); }
  function nOrNull(v) { return (v === null || v === undefined || v === "" || isNaN(Number(v))) ? null : Number(v); }
  // [khoá, tiêu đề, giá trị để sắp xếp, chiều mặc định khi bấm lần đầu]
  var COLS = [
    ["saved_at", "Lúc chạy", function (x) { return nOrNull(x.saved_at); }, -1],
    ["method", "Chiến lược", function (x) { return String(x.label || label(x.method)).toLowerCase(); }, 1],
    ["symbol", "Cặp", function (x) { return String(x.symbol || ""); }, 1],
    ["start", "Khoảng ngày", function (x) { return d10(x.start) + d10(x.end); }, -1],
    ["return_pct", "Lời/lỗ %", function (x) { return nOrNull(x.return_pct); }, -1],
    ["total_pnl", "Lời/lỗ USDT", function (x) { return nOrNull(x.total_pnl); }, -1],
    ["max_drawdown_pct", "DD max", function (x) { return nOrNull(x.max_drawdown_pct); }, 1],
    ["total_trades", "Lệnh", function (x) { return nOrNull(x.total_trades); }, -1],
    ["winrate", "Winrate", function (x) { return nOrNull(x.winrate); }, -1],
    ["profit_factor", "Profit factor", function (x) {  // không có lệnh thua mà có lãi → coi như vô cùng
      var v = nOrNull(x.profit_factor); return v === null && Number(x.return_pct) > 0 && x.max_loss_streak === 0 ? Infinity : v; }, -1],
    ["max_loss_streak", "Chuỗi thua", function (x) { return nOrNull(x.max_loss_streak); }, 1],
    ["overrides", "Tham số thử", function (x) { return ovText(x); }, 1]
  ];
  var SKEY = "bt_hist_view";
  var view = {sort: "saved_at", dir: -1};
  var FIELDS = ["fFilter", "hSym", "hRes", "hRange", "hFrom", "hTo", "hMinTr", "hText"];
  try { var sv = JSON.parse(localStorage.getItem(SKEY) || "null"); if (sv && sv.sort) view = sv; } catch (e) {}
  function saveView() {
    view.f = {}; FIELDS.forEach(function (k) { view.f[k] = $(k).value; });
    try { localStorage.setItem(SKEY, JSON.stringify(view)); } catch (e) {}
  }
  function col(k) { return COLS.filter(function (c) { return c[0] === k; })[0] || COLS[0]; }
  var NARROW = window.matchMedia && window.matchMedia("(max-width: 768px)").matches;
  if (NARROW) $("histBox").open = false;  // điện thoại: thu gọn bộ lọc, bấm để mở
  function runAt(t) {
    var d = new Date(t * 1000);
    return NARROW ? d.toLocaleString("vi-VN", {hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"})
      : d.toLocaleString("vi-VN", {hour12: false});
  }
  $("hSort").innerHTML = COLS.map(function (c) { return "<option value='" + c[0] + "'>" + esc(c[1]) + "</option>"; }).join("");

  function fillSelect(id, first, vals) {  // giữ lựa chọn hiện tại nếu còn
    var el = $(id), cur = el.value;
    el.innerHTML = "<option value=''>" + esc(first) + "</option>" + vals.map(function (v) {
      return "<option value='" + esc(v[0]) + "'>" + esc(v[1]) + "</option>"; }).join("");
    if (cur && vals.some(function (v) { return v[0] === cur; })) el.value = cur;
  }
  function uniq(a) { return a.filter(function (v, i) { return v && a.indexOf(v) === i; }); }
  function fillOptions() {
    fillSelect("hSym", "Tất cả cặp", uniq(items.map(function (x) { return x.symbol; })).sort().map(function (v) { return [v, v]; }));
    fillSelect("hRange", "Mọi khoảng ngày", uniq(items.map(function (x) { return d10(x.start) + "|" + d10(x.end); })).sort().reverse()
      .map(function (v) { var p = v.split("|"); return [v, p[0] + " → " + p[1]]; }));
  }

  function filtered() {
    var f = $("fFilter").value, sym = $("hSym").value, res = $("hRes").value, rg = $("hRange").value;
    var from = $("hFrom").value, to = $("hTo").value, minTr = parseInt($("hMinTr").value, 10) || 0;
    var q = $("hText").value.trim().toLowerCase();
    return items.filter(function (x) {
      var r = Number(x.return_pct || 0);
      if (f && x.method !== f) return false;
      if (sym && x.symbol !== sym) return false;
      if (res === "win" && !(r > 0)) return false;
      if (res === "loss" && !(r < 0)) return false;
      if (rg && d10(x.start) + "|" + d10(x.end) !== rg) return false;
      if (from && d10(x.start) < from) return false;  // khoảng backtest nằm trong [từ, đến]
      if (to && d10(x.end) > to) return false;
      if (minTr && !(Number(x.total_trades || 0) >= minTr)) return false;
      if (q && [x.label, label(x.method), x.disk_name, x.symbol, ovText(x), x.batch].join(" ").toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }
  function sorted(rows) {
    var get = col(view.sort)[2], dir = view.dir;
    return rows.map(function (x, i) { return {x: x, v: get(x), i: i}; }).sort(function (a, b) {
      if (a.v === null && b.v === null) return a.i - b.i;
      if (a.v === null) return 1;  // ô trống luôn nằm cuối
      if (b.v === null) return -1;
      var c = typeof a.v === "string" ? a.v.localeCompare(b.v) : (a.v < b.v ? -1 : a.v > b.v ? 1 : 0);
      return c ? c * dir : a.i - b.i;
    }).map(function (o) { return o.x; });
  }

  function drawHist() {
    var rows = sorted(filtered());
    $("hSort").value = view.sort;
    $("hDir").textContent = view.dir < 0 ? "↓ Giảm dần" : "↑ Tăng dần";
    var nf = FIELDS.filter(function (k) { return $(k).value; }).length;
    $("histActive").textContent = nf ? "(đang lọc " + nf + " điều kiện)" : "";
    $("histCount").textContent = items.length ? rows.length + " / " + items.length + " kết quả" : "";
    $("histEmpty").textContent = items.length ? "Không có kết quả nào khớp bộ lọc." : "Chưa có kết quả nào. Chạy một backtest ở trên.";
    $("histEmpty").style.display = rows.length ? "none" : "";
    shown = rows.map(function (x) { return x.id; });
    var allOn = shown.length && shown.every(function (id) { return picked[id]; });
    $("histTbl").innerHTML = rows.length ? "<tr><th class='sel'><label title='Chọn / bỏ chọn tất cả đang hiện'><input type='checkbox' id='selAll'" +
      (allOn ? " checked" : "") + "></label></th>" + COLS.map(function (c) {
        var on = c[0] === view.sort;
        return "<th class='sortable" + (on ? " sorted" : "") + "' data-k='" + c[0] + "' title='Bấm để sắp xếp'>" + esc(c[1]) +
          "<span class='arr'>" + (on ? (view.dir < 0 ? "▼" : "▲") : "↕") + "</span></th>";
      }).join("") + "</tr>" + rows.map(function (x) {
        var r = Number(x.return_pct || 0), pnl = nOrNull(x.total_pnl), pf = nOrNull(x.profit_factor);
        return "<tr class='click" + (picked[x.id] ? " picked" : "") + "' data-id='" + esc(x.id) + "'><td class='sel'><label><input type='checkbox' class='pick'" +
          (picked[x.id] ? " checked" : "") + "></label></td><td>" + runAt(x.saved_at) +
          "</td><td>" + esc(x.label || label(x.method)) + "</td><td>" + esc(x.symbol) + "</td><td>" + esc(d10(x.start)) + " → " +
          esc(d10(x.end)) + "</td><td class='" + (r >= 0 ? "pos" : "neg") + "'>" + V.money(r) + "%</td><td class='" +
          (pnl === null ? "" : pnl >= 0 ? "pos" : "neg") + "'>" + (pnl === null ? "—" : V.money(pnl)) + "</td><td>" + V.num(x.max_drawdown_pct, 1) +
          "%</td><td>" + esc(x.total_trades) + "</td><td>" + V.num(x.winrate, 1) + "%</td><td>" +
          (pf !== null ? pf.toFixed(2) : (Number(x.return_pct) > 0 && x.max_loss_streak === 0 ? "∞" : "—")) + "</td><td>" +
          (x.max_loss_streak == null ? "—" : esc(x.max_loss_streak)) + "</td><td class='muted'>" + esc(ovText(x)) + "</td></tr>";
      }).join("") : "";
    drawSel();
  }
  // [2026-11-22] chọn nhiều kết quả → tải ZIP
  var picked = {}, shown = [];
  function pickedIds() { return items.filter(function (x) { return picked[x.id]; }).map(function (x) { return x.id; }); }
  function drawSel() {
    var ids = pickedIds(), n = ids.length, MAX = 50;
    $("selInfo").textContent = n ? "Đã chọn " + n + " kết quả" + (n > MAX ? " (tối đa " + MAX + " mỗi lần tải)" : "") : "Chưa chọn kết quả nào";
    $("selZip").disabled = !n || n > MAX;
    $("selNone").disabled = !n;
    $("selBar").classList.toggle("on", n > 0);
  }
  $("selZip").addEventListener("click", function () {
    var ids = pickedIds(); if (!ids.length) return;
    var btn = this; btn.disabled = true; btn.textContent = "Đang tạo file...";
    fetch("/api/backtests/zip?ids=" + ids.join(",")).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ("Lỗi " + r.status)); });
      var cd = r.headers.get("Content-Disposition") || "", m = /filename="([^"]+)"/.exec(cd);
      return r.blob().then(function (b) {
        var a = document.createElement("a"), u = URL.createObjectURL(b);
        a.href = u; a.download = m ? m[1] : "backtest.zip"; document.body.appendChild(a); a.click();
        setTimeout(function () { URL.revokeObjectURL(u); a.remove(); }, 2000);
      });
    }).catch(function (e) { alert("Không tải được: " + e.message); })
      .then(function () { btn.textContent = "Tải thư mục Excel (ZIP)"; drawSel(); });
  });
  $("selShown").addEventListener("click", function () { shown.forEach(function (id) { picked[id] = true; }); drawHist(); });
  $("selNone").addEventListener("click", function () { picked = {}; drawHist(); });
  function setSort(k, dir) { view.sort = k; view.dir = dir; saveView(); drawHist(); }
  FIELDS.forEach(function (k) { $(k).addEventListener(k === "hText" || k === "hMinTr" ? "input" : "change", function () { saveView(); drawHist(); }); });
  $("hSort").addEventListener("change", function () { setSort(this.value, col(this.value)[3]); });
  $("hDir").addEventListener("click", function () { setSort(view.sort, -view.dir); });
  $("hClear").addEventListener("click", function () {
    FIELDS.forEach(function (k) { $(k).value = ""; }); saveView(); drawHist();
  });
  $("histTbl").addEventListener("change", function (e) {
    var t = e.target;
    if (t.id === "selAll") { shown.forEach(function (id) { if (t.checked) picked[id] = true; else delete picked[id]; }); drawHist(); return; }
    if (t.classList.contains("pick")) {
      var tr = t.closest("tr"), id = tr.dataset.id;
      if (t.checked) picked[id] = true; else delete picked[id];
      tr.classList.toggle("picked", t.checked);
      var all = $("selAll"); if (all) all.checked = shown.every(function (k) { return picked[k]; });
      drawSel();
    }
  });
  $("histTbl").addEventListener("click", function (e) {
    if (e.target.closest(".sel")) return;  // bấm ô tick không mở chi tiết
    var th = e.target.closest("th.sortable");
    if (th) { var k = th.dataset.k; setSort(k, k === view.sort ? -view.dir : col(k)[3]); return; }
    var tr = e.target.closest("tr.click"); if (tr) openResult(tr.dataset.id);
  });
  function restoreFilters() {  // sau khi có danh sách đĩa / cặp mới đặt lại lựa chọn đã lưu
    var f = view.f || {};
    FIELDS.forEach(function (k) { if (f[k] != null && f[k] !== "") $(k).value = f[k]; });
  }

  function refresh() {
    return api("/api/backtests?limit=300").then(function (d) {
      items = d.items || [];
      fillOptions();
      if (!restored) { restoreFilters(); restored = true; }
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
