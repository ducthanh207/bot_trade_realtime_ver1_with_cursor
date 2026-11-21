/* [2026-11-21] Trang Chiến lược: danh sách đĩa, xem / tải .md, nạp đĩa (admin), paper cho đĩa (admin). */
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var V = window.BTView, esc = V.esc;
  var page = $("dkPage"), CSRF = page.dataset.csrf, ADMIN = page.dataset.admin === "1";
  var BLOCK_NAMES = {regime_cut: "Giai đoạn + cắt lỗ sớm", daily_cycle: "Chu kỳ ngày", cvd: "CVD",
    trend_filter_always: "Lọc trend EMA50", stop_atr_4h: "Stop ATR 4H", risk_sizing: "Size theo rủi ro"};
  var STATUS = {running: ["Đang chạy", "run"], paused: ["Tạm dừng", "pause"], stopped: ["Đã dừng", ""]};
  var disks = [], openId = null;
  function dkName(x) { return (x.name || "").indexOf(x.short) === 0 ? x.name : x.short + " — " + x.name; }

  function api(url, body, raw) {
    var o = {};
    if (body !== undefined) {
      o = {method: "POST", headers: {"X-CSRF-Token": CSRF}};
      if (raw) o.body = body; else { o.headers["Content-Type"] = "application/json"; o.body = JSON.stringify(body); }
    }
    return fetch(url, o).then(function (r) { return r.json().then(function (j) { if (!r.ok && !j.error) j.error = "Lỗi " + r.status; return j; }); });
  }

  function badges(d) {
    var h = "<span class='badge base'>" + esc(d.base.toUpperCase()) + "</span> ";
    h += d.blocks.map(function (b) { return "<span class='badge blk' title='" + esc(d.blocks_text[b]) + "'>" + esc(BLOCK_NAMES[b] || b) + "</span>"; }).join(" ");
    if (d.source !== "builtin") h += " <span class='badge up'>Đĩa nạp</span>";
    return h;
  }
  function paperLine(d) {
    if (d.own_page) return "<a class='btn sm' href='" + d.own_page + "'>Mở trang Paper " + esc(d.id) + "</a>";
    var p = d.paper || {}, st = STATUS[p.status] || STATUS.stopped;
    var ret = p.initial_capital ? (p.balance / p.initial_capital - 1) * 100 : 0;
    return "<span class='badge " + st[1] + "'>Paper: " + st[0] + "</span> " +
      (p.status !== "stopped" || p.n_trades ? "<span class='muted'>" + esc(p.symbol) + " · vốn " + V.num(p.balance, 2) +
        " (<span class='" + (ret >= 0 ? "pos" : "neg") + "'>" + V.money(ret) + "%</span>) · " + p.n_trades + " lệnh" +
        (p.open_trade ? " · đang mở " + esc(p.open_trade.side) : "") + "</span>" : "");
  }
  function card(d) {
    var params = Object.keys(d.params || {});
    return "<article class='card'><div class='row' style='justify-content:space-between'><h2 style='margin:0'>" + esc(d.name) +
      "</h2><span class='badge'>" + esc(d.short) + "</span></div>" +
      "<p class='muted' style='margin:6px 0'>" + esc(d.description) + "</p><div class='row'>" + badges(d) + "</div>" +
      (params.length ? "<p class='muted' style='margin:6px 0 0'>Tham số riêng: " + params.map(function (k) { return esc(k) + "=" + esc(d.params[k]); }).join(", ") + "</p>" : "") +
      "<div class='row' style='margin-top:8px'>" + paperLine(d) + "</div>" +
      "<div class='row' style='margin-top:10px'><button class='btn sm' data-open='" + esc(d.id) + "'>Chi tiết</button>" +
      "<a class='btn sm' href='/backtest?disk=" + encodeURIComponent(d.id) + "'>Backtest</a>" +
      "<a class='btn sm' href='/api/disks/" + encodeURIComponent(d.id) + "/md'>Tải .md</a>" +
      (ADMIN && d.source !== "builtin" ? "<button class='btn sm danger' data-del='" + esc(d.id) + "'>Xoá</button>" : "") +
      "</div></article>";
  }
  function load(reopen) {
    return api("/api/disks").then(function (r) {
      disks = r.disks || [];
      $("diskGrid").innerHTML = disks.map(card).join("");
      var errs = r.errors || {};
      $("loadErr").innerHTML = Object.keys(errs).length ? "<div class='notice err' style='margin-bottom:12px'>Đĩa lỗi, không nạp: " +
        Object.keys(errs).map(function (k) { return esc(k) + " — " + esc(errs[k]); }).join("; ") + "</div>" : "";
      if (reopen !== false && openId) openDisk(openId, true);
    });
  }
  $("diskGrid").addEventListener("click", function (e) {
    var o = e.target.dataset.open, del = e.target.dataset.del;
    if (o) openDisk(o);
    if (del && confirm("Xoá đĩa " + del + "? (lịch sử paper của đĩa vẫn giữ trong file)")) {
      api("/api/disks/" + encodeURIComponent(del) + "/delete", {}).then(function (r) { if (r.error) alert(r.error); load(); });
    }
  });

  // ---------- chi tiết + paper ----------
  function paperPanel(d) {
    if (d.own_page) return "<p><a class='btn sm' href='" + d.own_page + "'>Paper " + esc(d.id) + " có trang riêng</a></p>";
    var p = d.paper || {}, st = STATUS[p.status] || STATUS.stopped;
    var h = "<section class='card' style='margin-top:10px'><h2>Paper trade của đĩa</h2><div class='row'>" + paperLine(d) + "</div>";
    if (p.open_trade) {
      var o = p.open_trade;
      h += "<p class='muted'>Lệnh mở: " + esc(o.side) + " @ " + V.num(o.entry_price, 4) + " · size " + V.num(o.size, 4) +
        " · stop " + V.num(o.trail_stop, 4) + " · từ " + V.tshort(o.entry_time) + "</p>";
    }
    if (ADMIN) {
      var locked = !!(p.n_trades || p.open_trade);
      h += "<div class='bt-form' style='margin-top:8px'>" +
        "<label class='field'><span>Cặp</span><input type='text' id='ppSym' value='" + esc(p.symbol) + "'" + (p.open_trade ? " disabled" : "") + "></label>" +
        "<label class='field'><span>Vốn</span><input type='number' id='ppCap' value='" + esc(p.initial_capital) + "'" + (locked ? " disabled title='Đặt lại để đổi vốn'" : "") + "></label>" +
        "<label class='field'><span>Đòn bẩy</span><input type='number' id='ppLev' value='" + esc(p.leverage) + "'></label>" +
        "<label class='field'><span>% vốn</span><input type='number' id='ppWct' value='" + esc(Math.round(p.wallet_pct * 1000) / 10) + "'></label></div>" +
        "<div class='row' style='margin-top:8px'>" +
        (p.status !== "running" ? "<button class='btn ok sm' data-pp='start'>Bật paper</button>" : "") +
        (p.status === "running" ? "<button class='btn warn sm' data-pp='pause'>Tạm dừng (chỉ thoát lệnh)</button>" : "") +
        (p.status !== "stopped" ? "<button class='btn sm' data-pp='stop'>Dừng</button>" : "") +
        (p.open_trade ? "<button class='btn danger sm' data-pp='close'>Đóng lệnh ngay</button>" : "") +
        (!p.open_trade ? "<button class='btn sm' data-pp='reset'>Đặt lại vốn + xoá lịch sử</button>" : "") +
        "<span class='muted' id='ppMsg'></span></div>";
    } else {
      h += "<p class='muted'><a href='/live/login?next=/strategies'>Đăng nhập admin</a> để bật paper cho đĩa này.</p>";
    }
    return h + "<div id='ppTrades' style='margin-top:8px'></div></section>";
  }
  function openDisk(id, keepScroll) {
    openId = id;
    api("/api/disks/" + encodeURIComponent(id)).then(function (d) {
      if (d.error) return;
      $("dkTitle").textContent = dkName(d);
      $("dkMd").href = "/api/disks/" + encodeURIComponent(id) + "/md";
      $("dkBt").href = "/backtest?disk=" + encodeURIComponent(id);
      var params = Object.keys(d.params || {});
      $("dkMeta").innerHTML = "<div class='row'>" + badges(d) + "</div><p class='muted'>" + esc(d.base_text) + "</p>" +
        d.blocks.map(function (b) { return "<p class='muted' style='margin:2px 0'>• <b>" + esc(BLOCK_NAMES[b] || b) + "</b>: " + esc(d.blocks_text[b]) + "</p>"; }).join("") +
        (params.length ? "<p class='muted'>Tham số riêng (chỉ cho đĩa này): " + params.map(function (k) { return esc(k) + "=" + esc(d.params[k]); }).join(", ") + "</p>"
          : "<p class='muted'>Không có tham số riêng: dùng theo .env.</p>");
      $("dkPaper").innerHTML = paperPanel(d);
      $("dkBody").innerHTML = d.body_html || "";
      if (!d.own_page) api("/api/disks/" + encodeURIComponent(id) + "/paper").then(function (p) {
        var el = $("ppTrades"); if (!el || !p.trades) return;
        el.innerHTML = p.trades.length ? V.tradesHtml({trades: p.trades.slice().reverse()}) : "<p class='muted'>Chưa có lệnh paper.</p>";
      });
      $("dkDrawer").classList.add("open");
    });
  }
  $("dkPaper").addEventListener("click", function (e) {
    var a = e.target.dataset.pp; if (!a) return;
    if (a === "close" && !confirm("Đóng lệnh paper theo giá hiện tại?")) return;
    if (a === "reset" && !confirm("Xoá lịch sử paper của đĩa và đặt lại vốn?")) return;
    var body = {};
    if (a === "start") body = {symbol: $("ppSym").value, capital: $("ppCap").disabled ? null : $("ppCap").value,
      leverage: $("ppLev").value, wallet_pct: $("ppWct").value};
    if (a === "reset") body = {capital: $("ppCap").value};
    $("ppMsg").textContent = "...";
    api("/api/disks/" + encodeURIComponent(openId) + "/paper/" + a, body).then(function (r) {
      if (r.error) { $("ppMsg").innerHTML = "<span class='neg'>" + esc(r.error) + "</span>"; return; }
      load();
    });
  });
  function close() { $("dkDrawer").classList.remove("open"); openId = null; }
  $("dkClose").addEventListener("click", close);
  $("dkDrawer").addEventListener("click", function (e) { if (e.target === this) close(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") close(); });

  // ---------- nạp đĩa ----------
  if (ADMIN) {
    var text = "";
    $("btnPaste").addEventListener("click", function () { $("upText").style.display = ""; $("upText").focus(); });
    $("upFile").addEventListener("change", function () {
      var f = this.files[0]; if (!f) return;
      if (f.size > 64 * 1024) { $("upMsg").textContent = "File quá lớn (tối đa 64 KB)"; return; }
      f.text().then(function (t) { $("upText").value = t; $("upText").style.display = ""; check(); });
    });
    $("upText").addEventListener("input", function () { $("btnUpload").disabled = true; });
    function check() {
      text = $("upText").value;
      $("btnUpload").disabled = true; $("upMsg").textContent = "Đang kiểm tra...";
      api("/api/disks/validate", {text: text}).then(function (r) {
        if (r.error) { $("upMsg").innerHTML = "<span class='neg'>✗ " + esc(r.error) + "</span>"; $("upPreview").innerHTML = ""; return; }
        var d = r.disk;
        $("upMsg").innerHTML = d.conflict_builtin ? "<span class='neg'>✗ id '" + esc(d.id) + "' là đĩa có sẵn, đổi id khác</span>"
          : "<span class='pos'>✓ Hợp lệ</span>" + (d.replaces ? " — sẽ thay đĩa nạp cùng id" : "");
        $("btnUpload").disabled = !!d.conflict_builtin;
        $("upPreview").innerHTML = "<div class='card' style='background:#131722'><b>" + esc(dkName(d)) + "</b><div class='row' style='margin-top:6px'>" +
          badges(d) + "</div>" + (Object.keys(d.params).length ? "<p class='muted'>Tham số: " + Object.keys(d.params).map(function (k) { return esc(k) + "=" + esc(d.params[k]); }).join(", ") + "</p>" : "") + "</div>";
      });
    }
    $("btnCheck").addEventListener("click", check);
    $("btnUpload").addEventListener("click", function () {
      api("/api/disks/upload", {text: text}).then(function (r) {
        if (r.error) { $("upMsg").innerHTML = "<span class='neg'>✗ " + esc(r.error) + "</span>"; return; }
        $("upMsg").innerHTML = "<span class='pos'>✓ Đã nạp " + esc(r.disk.short) + ". Đĩa ở trạng thái paper DỪNG — bật trong Chi tiết.</span>";
        $("upText").value = ""; $("upPreview").innerHTML = ""; $("btnUpload").disabled = true;
        load();
      });
    });
  }
  load();
  setInterval(function () { if (!document.hidden) load(false); }, 30000);
})();
