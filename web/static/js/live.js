/* Dashboard trade thật (/live) */
(function () {
  "use strict";
  var CFG = { accounts: [], telegrams: [], bots: [] };
  var OV = null;

  function $(s, r) { return (r || document).querySelector(s); }
  function $all(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v, d) { var x = Number(v); return isFinite(x) ? x.toFixed(d == null ? 2 : d) : "—"; }
  function px(v) {
    var x = Number(v); if (!isFinite(x) || !x) return "—";
    return x >= 1000 ? x.toLocaleString("en-US", { maximumFractionDigits: 2 }) : x >= 1 ? x.toFixed(4) : x.toFixed(6);
  }
  function signed(v, d) {
    var x = Number(v); if (!isFinite(x)) return "—";
    return '<span class="' + (x >= 0 ? "pos" : "neg") + '">' + (x >= 0 ? "+" : "") + x.toFixed(d == null ? 2 : d) + "</span>";
  }
  function t(v) {
    if (!v) return "—";
    var d = new Date(v); if (isNaN(d)) return esc(v);
    return d.toLocaleString("vi-VN", { hour12: false, day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
  }
  function toast(msg, isErr) {
    var el = document.createElement("div");
    el.className = "lv-toast" + (isErr ? " err" : "");
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, isErr ? 7000 : 3500);
  }

  function api(path, body) {
    var opt = { credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opt.method = "POST";
      opt.headers["Content-Type"] = "application/json";
      opt.headers["X-CSRF-Token"] = window.LIVE_CSRF;
      opt.body = JSON.stringify(body || {});
    }
    return fetch(path, opt).then(function (r) {
      if (r.status === 401) { location.href = "/live/login"; throw new Error("Chưa đăng nhập"); }
      return r.json().then(function (j) {
        if (!r.ok || j.ok === false || j.error) throw new Error(j.error || ("HTTP " + r.status));
        return j;
      });
    });
  }
  function act(path, body, okMsg) {
    return api(path, body).then(function (j) {
      toast(j.message || okMsg || "Đã lưu");
      return refreshAll().then(function () { return j; });
    }).catch(function (e) { toast(e.message, true); throw e; });
  }

  // ------------------------------------------------------------ hiển thị
  function accName(id) { var a = CFG.accounts.find(function (x) { return x.id === id; }); return a ? a.name : id; }

  function renderTop() {
    var on = OV ? OV.real_trading_enabled : CFG.real_trading_enabled;
    var b = $("#btnSwitch");
    b.textContent = on ? "ĐANG BẬT" : "ĐANG TẮT";
    b.className = "lv-switch " + (on ? "on" : "off");
    if (OV) {
      $("#tickInfo").textContent = "Engine: " + (OV.last_tick_at ? t(OV.last_tick_at) : "chưa chạy");
      $("#windowInfo").textContent = OV.in_4h_window ? "Cửa sổ vào lệnh 4H: ĐANG MỞ" : "Chờ nến 4H kế tiếp";
      var eb = $("#errorBar");
      if (OV.last_error) { eb.hidden = false; eb.textContent = "Lỗi gần nhất: " + OV.last_error; } else { eb.hidden = true; }
    }
  }

  function renderCards() {
    var box = $("#accountCards");
    if (!OV) return;
    if (!OV.accounts.length) {
      box.innerHTML = '<div class="lv-card"><h4>Chưa có tài khoản sàn</h4><span class="lv-muted">Vào tab "Tài khoản sàn" để thêm API key.</span></div>';
      return;
    }
    box.innerHTML = OV.accounts.map(function (a) {
      var body;
      if (a.error) body = '<div class="neg">Lỗi: ' + esc(a.error) + "</div>";
      else if (a.balance) {
        body = '<div class="big">' + num(a.balance.wallet + a.balance.unrealized) + ' USDT</div>' +
          '<div>Khả dụng: ' + num(a.balance.available) + ' | uPnL: ' + signed(a.balance.unrealized) + '</div>' +
          '<div class="lv-muted">Vị thế trên sàn: ' + ((a.positions || []).map(function (p) {
            return esc(p.symbol) + " " + p.side + " " + p.qty;
          }).join(", ") || "không có") + "</div>";
      } else body = '<div class="lv-muted">Chưa có API key</div>';
      return '<div class="lv-card"><h4>' + esc(a.name) + ' <span class="lv-muted">' + esc(a.env) + "</span> " +
        (a.enabled ? '<span class="pos">BẬT</span>' : '<span class="lv-muted">TẮT</span>') + "</h4>" + body + "</div>";
    }).join("");
  }

  function botRow(b) {
    var ot = b.open_trade;
    var pos = "—";
    if (ot) {
      pos = '<b class="' + (ot.side === "LONG" ? "pos" : "neg") + '">' + ot.side + "</b> " + ot.size + " @ " + px(ot.entry_price) +
        "<br>uPnL " + signed(ot.unrealized) + " | giá " + px(ot.mark_price) +
        '<br><span class="lv-muted">trail ' + px(ot.trail_stop) + " | stop sàn " + px(ot.exchange_stop) + "</span>" +
        (ot.on_exchange ? "" : '<br><span class="neg">Không thấy vị thế trên sàn</span>');
    }
    var cap = Number(b.capital) || 1;
    var st = '<span class="st-' + b.status + '">' + ({ running: "Chạy", paused: "Tạm dừng", stopped: "Dừng" }[b.status] || b.status) + "</span>";
    if (b.cb && (b.cb.light_until || b.cb.heavy_until)) st += '<br><span class="lv-muted">circuit breaker</span>';
    var acts = [];
    if (b.status !== "running") acts.push('<button class="lv-btn lv-small" data-act="run" data-id="' + b.id + '">Chạy</button>');
    if (b.status === "running") acts.push('<button class="lv-btn lv-small" data-act="pause" data-id="' + b.id + '">Tạm dừng</button>');
    if (b.status !== "stopped") acts.push('<button class="lv-btn lv-small" data-act="stop" data-id="' + b.id + '">Dừng</button>');
    if (ot) acts.push('<button class="lv-btn lv-small lv-danger" data-act="close" data-id="' + b.id + '">Đóng lệnh</button>');
    acts.push('<button class="lv-btn lv-small" data-act="edit" data-id="' + b.id + '">Sửa</button>');
    if (!ot) acts.push('<button class="lv-btn lv-small" data-act="del" data-id="' + b.id + '">Xoá</button>');
    function td(label, html) { return '<td data-label="' + label + '"><div>' + html + "</div></td>"; }
    return "<tr>" + td("Bot", "<b>" + esc(b.name) + "</b>") + td("Tài khoản", esc(accName(b.account_id))) +
      td("Cặp / chiến lược", esc(b.symbol) + "<br><span class=\"lv-muted\">PP" + esc(b.method) + " · x" + b.leverage + " · " + Math.round(b.wallet_pct * 100) + "% vốn</span>") +
      td("Trạng thái", st) +
      td("Vốn bot", num(b.equity) + '<br><span class="lv-muted">phân bổ ' + num(b.capital) + "</span>") +
      td("PnL tổng", signed(b.total_pnl) + "<br>" + signed((b.equity - cap) / cap * 100) + '%<br><span class="lv-muted">' + b.n_trades + " lệnh, thắng " + b.wins + "</span>") +
      td("Hôm nay", signed(b.today_pnl) + '<br><span class="lv-muted">' + b.today_n + " lệnh</span>") +
      td("Vị thế", pos) + td("", acts.join("")) + "</tr>";
  }

  function renderBots() {
    var tb = $("#botsTable tbody");
    var bots = OV ? OV.bots : [];
    tb.innerHTML = bots.length ? bots.map(botRow).join("") : '<tr><td colspan="9" class="lv-muted">Chưa có bot. Thêm tài khoản sàn trước, rồi bấm "+ Thêm bot".</td></tr>';
  }

  function renderAccounts() {
    $("#accTable tbody").innerHTML = CFG.accounts.length ? CFG.accounts.map(function (a) {
      var lt = a.last_test;
      var test = lt ? (lt.ok ? '<span class="pos">OK</span> ' + t(lt.t) + (lt.dual_side ? "<br><span class=\"lv-muted\">hedge mode</span>" : "") : '<span class="neg">Lỗi</span> ' + esc(lt.error || "")) : "—";
      return "<tr><td><b>" + esc(a.name) + "</b></td><td>" + esc(a.exchange) + "<br><span class=\"lv-muted\">" + esc((window.LIVE_ENVS || {})[a.env] || a.env) + "</span></td>" +
        "<td>" + esc(a.key_hint || "—") + "</td><td>" + test + "</td>" +
        "<td>" + (a.enabled ? '<span class="pos">BẬT</span>' : '<span class="lv-muted">TẮT</span>') + "</td><td>" +
        '<button class="lv-btn lv-small" data-acc="test" data-id="' + a.id + '">Kiểm tra</button>' +
        '<button class="lv-btn lv-small" data-acc="' + (a.enabled ? "off" : "on") + '" data-id="' + a.id + '">' + (a.enabled ? "Tắt" : "Bật") + "</button>" +
        '<button class="lv-btn lv-small" data-acc="edit" data-id="' + a.id + '">Sửa</button>' +
        '<button class="lv-btn lv-small" data-acc="del" data-id="' + a.id + '">Xoá</button></td></tr>';
    }).join("") : '<tr><td colspan="6" class="lv-muted">Chưa có tài khoản.</td></tr>';
    var sel = $("#botForm select[name=account_id]");
    var cur = sel.value;
    sel.innerHTML = CFG.accounts.map(function (a) { return '<option value="' + a.id + '">' + esc(a.name) + " (" + esc(a.env) + ")</option>"; }).join("");
    if (cur) sel.value = cur;
  }

  function yes(v) { return v ? "✓" : "—"; }
  function renderTelegrams() {
    $("#tgTable tbody").innerHTML = CFG.telegrams.length ? CFG.telegrams.map(function (g) {
      return "<tr><td><b>" + esc(g.name) + "</b>" + (g.enabled ? "" : ' <span class="lv-muted">(tắt)</span>') + "</td><td>" + esc(g.token_hint) + "</td><td>" + esc(g.chat_id) + "</td>" +
        "<td>" + yes(g.notify_trades) + "</td><td>" + yes(g.notify_hourly) + "</td><td>" + yes(g.notify_errors) + "</td><td>" + yes(g.allow_control) + "</td><td>" +
        '<button class="lv-btn lv-small" data-tg="test" data-id="' + g.id + '">Gửi thử</button>' +
        '<button class="lv-btn lv-small" data-tg="edit" data-id="' + g.id + '">Sửa</button>' +
        '<button class="lv-btn lv-small" data-tg="del" data-id="' + g.id + '">Xoá</button></td></tr>';
    }).join("") : '<tr><td colspan="8" class="lv-muted">Chưa có kết nối Telegram.</td></tr>';
    var box = $("#botTgChecks");
    var checked = $all("input", box).filter(function (i) { return i.checked; }).map(function (i) { return i.value; });
    box.innerHTML = CFG.telegrams.map(function (g) {
      return '<label class="lv-inline"><input type="checkbox" value="' + g.id + '"' + (checked.indexOf(g.id) >= 0 ? " checked" : "") + "> " + esc(g.name) + "</label>";
    }).join("") || '<span class="lv-muted">Chưa có kết nối Telegram</span>';
  }

  function loadTrades() {
    return api("/api/live/trades?limit=300").then(function (rows) {
      $("#tradesTable tbody").innerHTML = rows.length ? rows.map(function (r) {
        var fee = (Number(r.entry_fee) || 0) + (Number(r.exit_fee) || 0);
        return "<tr><td>" + esc(r.bot) + "<br><span class=\"lv-muted\">" + esc(r.symbol) + " PP" + esc(r.method) + "</span></td><td>" + esc(r.side) + "</td>" +
          "<td>" + t(r.entry_time) + "</td><td>" + t(r.exit_time) + "</td><td>" + px(r.entry_price) + "</td><td>" + px(r.exit_price) + "</td>" +
          "<td>" + esc(r.size) + "</td><td>" + signed(r.profit, 4) + "</td><td>" + num(fee, 4) + "</td><td>" + esc(r.exit_reason) + "</td></tr>";
      }).join("") : '<tr><td colspan="10" class="lv-muted">Chưa có lệnh thật nào.</td></tr>';
    });
  }

  function loadEvents() {
    return api("/api/live/events?limit=150").then(function (rows) {
      $("#eventsList").innerHTML = rows.map(function (e) {
        return '<li class="k-' + esc(e.kind) + '"><span class="lv-muted">' + t(e.t) + "</span> " + esc(e.text) + "</li>";
      }).join("") || '<li class="lv-muted">Trống</li>';
    });
  }

  function refreshOverview() {
    return api("/api/live/overview").then(function (ov) { OV = ov; renderTop(); renderCards(); renderBots(); })
      .catch(function (e) { var eb = $("#errorBar"); eb.hidden = false; eb.textContent = "Không tải được dữ liệu: " + e.message; });
  }
  function refreshConfig() {
    return api("/api/live/config").then(function (c) { CFG = c; renderTop(); renderAccounts(); renderTelegrams(); renderBots(); });
  }
  function refreshAll() { return Promise.all([refreshConfig(), refreshOverview()]); }

  // --------------------------------------------------------------- form
  function formData(form) {
    var o = {};
    $all("input, select", form).forEach(function (el) {
      if (!el.name) return;
      if (el.type === "checkbox") o[el.name] = el.checked;
      else o[el.name] = el.value;
    });
    return o;
  }
  function fill(form, obj) {
    $all("input, select", form).forEach(function (el) {
      if (!el.name || !(el.name in obj)) return;
      if (el.type === "checkbox") el.checked = !!obj[el.name];
      else el.value = obj[el.name] == null ? "" : obj[el.name];
    });
  }
  function showTab(id) {
    $all(".lv-tab").forEach(function (b) { b.classList.toggle("active", b.dataset.tab === id); });
    $all(".lv-tabpane").forEach(function (p) { p.hidden = p.id !== id; });
    if (id === "tabTrades") loadTrades().catch(function () {});
    if (id === "tabEvents") loadEvents().catch(function () {});
  }

  function resetBotForm() {
    var f = $("#botForm"); f.reset(); f.id.value = "";
    $("#botFormTitle").textContent = "Thêm bot";
    $all("#botTgChecks input").forEach(function (i) { i.checked = false; });
  }
  function editBot(id) {
    var b = CFG.bots.find(function (x) { return x.id === id; }); if (!b) return;
    var f = $("#botForm");
    fill(f, b);
    f.wallet_pct_ui.value = Math.round(b.wallet_pct * 1000) / 10;
    $all("#botTgChecks input").forEach(function (i) { i.checked = (b.telegram_ids || []).indexOf(i.value) >= 0; });
    $("#botFormTitle").textContent = "Sửa bot: " + b.name;
    showTab("tabBot"); f.scrollIntoView({ behavior: "smooth" });
  }

  function bind() {
    $all(".lv-tab").forEach(function (b) { b.addEventListener("click", function () { showTab(b.dataset.tab); }); });

    $("#btnSwitch").addEventListener("click", function () {
      var on = OV ? OV.real_trading_enabled : CFG.real_trading_enabled;
      var msg = on ? "TẮT trade thật? (lệnh đang mở vẫn được bot quản lý thoát)" :
        "BẬT trade thật? Bot sẽ đặt lệnh THẬT trên sàn khi có tín hiệu (với bot đang Chạy và tài khoản BẬT).";
      if (!confirm(msg)) return;
      act("/api/live/switch", { on: !on }, on ? "Đã tắt trade thật" : "Đã bật trade thật");
    });
    $("#btnCloseAll").addEventListener("click", function () {
      if (!confirm("Đóng TẤT CẢ vị thế của bot bằng lệnh MARKET và TẮT trade thật?")) return;
      act("/api/live/closeall", {});
    });
    $("#btnNewBot").addEventListener("click", function () { resetBotForm(); showTab("tabBot"); $("#botForm").scrollIntoView({ behavior: "smooth" }); });
    $("#btnBotCancel").addEventListener("click", resetBotForm);

    $("#botsTable").addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-act]"); if (!b) return;
      var id = b.dataset.id, a = b.dataset.act;
      if (a === "edit") return editBot(id);
      if (a === "run") return act("/api/live/bots/" + id + "/status", { status: "running" }, "Bot đang chạy");
      if (a === "pause") return act("/api/live/bots/" + id + "/status", { status: "paused" }, "Đã tạm dừng (vẫn quản lý lệnh đang mở)");
      if (a === "stop") return act("/api/live/bots/" + id + "/status", { status: "stopped" }, "Đã dừng bot");
      if (a === "close" && confirm("Đóng lệnh đang mở của bot này bằng lệnh MARKET?")) return act("/api/live/bots/" + id + "/close", {});
      if (a === "del" && confirm("Xoá bot này (kèm lịch sử lệnh của bot)?")) return act("/api/live/bots/" + id + "/delete", {}, "Đã xoá");
    });

    $("#botForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var d = formData(ev.target);
      d.wallet_pct = Number(d.wallet_pct_ui) / 100; delete d.wallet_pct_ui;
      d.telegram_ids = $all("#botTgChecks input").filter(function (i) { return i.checked; }).map(function (i) { return i.value; });
      if (!d.id) delete d.id;
      act("/api/live/bots", d, "Đã lưu bot").then(resetBotForm).catch(function () {});
    });

    $("#accForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var d = formData(ev.target); if (!d.id) delete d.id;
      act("/api/live/accounts", d, "Đã lưu tài khoản — bấm Kiểm tra để thử kết nối").then(function () {
        ev.target.reset(); ev.target.id.value = ""; $("#accFormTitle").textContent = "Thêm tài khoản sàn";
      }).catch(function () {});
    });
    $("#btnAccCancel").addEventListener("click", function () { var f = $("#accForm"); f.reset(); f.id.value = ""; $("#accFormTitle").textContent = "Thêm tài khoản sàn"; });
    $("#accTable").addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-acc]"); if (!b) return;
      var id = b.dataset.id, a = b.dataset.acc;
      if (a === "test") {
        b.disabled = true;
        api("/api/live/accounts/" + id + "/test", {}).then(function (j) {
          toast("Kết nối OK — ví " + num(j.info.wallet) + " USDT, khả dụng " + num(j.info.available) + (j.info.dual_side ? " (hedge mode)" : ""));
        }).catch(function (e) { toast(e.message, true); }).then(function () { b.disabled = false; refreshAll(); });
        return;
      }
      if (a === "on" || a === "off") return act("/api/live/accounts/" + id + "/enable", { enabled: a === "on" });
      if (a === "edit") {
        var acc = CFG.accounts.find(function (x) { return x.id === id; }); var f = $("#accForm");
        fill(f, acc); f.api_key.value = ""; f.api_secret.value = "";
        $("#accFormTitle").textContent = "Sửa tài khoản: " + acc.name; f.scrollIntoView({ behavior: "smooth" }); return;
      }
      if (a === "del" && confirm("Xoá tài khoản này?")) return act("/api/live/accounts/" + id + "/delete", {}, "Đã xoá");
    });

    $("#tgForm").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var d = formData(ev.target); if (!d.id) delete d.id;
      act("/api/live/telegrams", d, "Đã lưu — bấm Gửi thử để kiểm tra").then(function () {
        ev.target.reset(); ev.target.id.value = ""; $("#tgFormTitle").textContent = "Thêm kết nối Telegram";
      }).catch(function () {});
    });
    $("#btnTgCancel").addEventListener("click", function () { var f = $("#tgForm"); f.reset(); f.id.value = ""; $("#tgFormTitle").textContent = "Thêm kết nối Telegram"; });
    $("#tgTable").addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-tg]"); if (!b) return;
      var id = b.dataset.id, a = b.dataset.tg;
      if (a === "test") return act("/api/live/telegrams/" + id + "/test", {}, "Đã gửi tin thử — kiểm tra Telegram");
      if (a === "edit") {
        var g = CFG.telegrams.find(function (x) { return x.id === id; }); var f = $("#tgForm");
        fill(f, g); f.token.value = "";
        $("#tgFormTitle").textContent = "Sửa kết nối: " + g.name; f.scrollIntoView({ behavior: "smooth" }); return;
      }
      if (a === "del" && confirm("Xoá kết nối Telegram này?")) return act("/api/live/telegrams/" + id + "/delete", {}, "Đã xoá");
    });
  }

  bind();
  refreshAll();
  setInterval(refreshOverview, 5000);
  setInterval(function () {
    refreshConfig().catch(function () {});
    if (!$("#tabTrades").hidden) loadTrades().catch(function () {});
    if (!$("#tabEvents").hidden) loadEvents().catch(function () {});
  }, 20000);
})();
