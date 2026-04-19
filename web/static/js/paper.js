(function () {
  var cfg = window.PAPER_UI || {};
  var slot = cfg.slot != null ? Number(cfg.slot) : 1;
  var prefix = cfg.prefix || "paper";
  var apiBase = cfg.apiBase || "/api/paper";

  var INTERVAL_MS = 5000;
  var ORDERS_REFRESH_MS = 1000;

  var capitalInput = document.getElementById("initial_capital");
  var statusBadge = document.getElementById("statusBadge");
  var ordersBody = document.getElementById("ordersBody");

  var lastStatus = null;
  var lastOrders = [];

  function field(d, name) {
    var k = prefix + "_" + name;
    return d[k];
  }

  function hiddenStorageKey() {
    return "bot_paper_hidden_trade_keys_" + slot;
  }

  function loadHiddenMap() {
    var m = {};
    try {
      var raw = localStorage.getItem(hiddenStorageKey());
      var arr = raw ? JSON.parse(raw) : [];
      if (Array.isArray(arr)) {
        for (var i = 0; i < arr.length; i++) {
          if (arr[i]) m[String(arr[i])] = true;
        }
      }
    } catch (e) {}
    return m;
  }

  var hiddenMap = loadHiddenMap();

  function persistHidden() {
    try {
      var keys = Object.keys(hiddenMap);
      localStorage.setItem(hiddenStorageKey(), JSON.stringify(keys));
    } catch (e) {}
  }

  function clearHiddenStorage() {
    hiddenMap = {};
    try {
      localStorage.removeItem(hiddenStorageKey());
    } catch (e) {}
  }

  /** JSON/API đôi khi trả is_open không chuẩn — chỉ coi true/1 là đang mở. */
  function orderIsOpen(o) {
    return !!o && (o.is_open === true || o.is_open === 1);
  }

  function orderRowDataId(o, idx) {
    if (orderIsOpen(o)) return "open";
    return String(o.id != null ? o.id : idx + 1);
  }

  function clearOrderRowHighlight() {
    ordersBody.querySelectorAll("tr.order-row-highlight").forEach(function (tr) {
      tr.classList.remove("order-row-highlight");
    });
    if (window.PaperMiniCharts && typeof window.PaperMiniCharts.clearHighlight === "function") {
      window.PaperMiniCharts.clearHighlight();
    }
  }

  function focusOrderRowById(rowId) {
    var rid = String(rowId);
    clearOrderRowHighlight();
    var row = null;
    ordersBody.querySelectorAll("tr[data-order-id]").forEach(function (tr) {
      if (tr.getAttribute("data-order-id") === rid) row = tr;
    });
    if (!row) return;
    row.classList.add("order-row-highlight");
    row.scrollIntoView({ block: "center", behavior: "smooth" });
    if (window.PaperMiniCharts && typeof window.PaperMiniCharts.setHighlightRowId === "function") {
      window.PaperMiniCharts.setHighlightRowId(rid);
    }
  }

  window.PaperOrderNav = {
    clear: clearOrderRowHighlight,
    focusByRowId: focusOrderRowById,
  };

  function chronosClosed(orders) {
    var closed = orders.filter(function (o) {
      return !orderIsOpen(o);
    });
    closed.sort(function (a, b) {
      var ra = a.replay_index != null ? Number(a.replay_index) : 0;
      var rb = b.replay_index != null ? Number(b.replay_index) : 0;
      return ra - rb;
    });
    return closed;
  }

  /** Có ít nhất một lệnh đóng hiện trong list đang bị ẩn. */
  function hasHiddenActive(orders, hm) {
    for (var i = 0; i < orders.length; i++) {
      var o = orders[i];
      if (orderIsOpen(o)) continue;
      var tk = String(o.trade_key || "");
      if (tk && hm[tk]) return true;
    }
    return false;
  }

  function replayBalanceAfterVisible(chronoClosed, hm, initial, takerFee) {
    var run = Number(initial) || 0;
    for (var i = 0; i < chronoClosed.length; i++) {
      var o = chronoClosed[i];
      var tk = String(o.trade_key || "");
      if (hm[tk]) continue;
      var entry = Number(o.entry_price) || 0;
      var size = Number(o.size) || 0;
      var feeIn = size * entry * takerFee;
      run -= feeIn;
      run += Number(o.pnl) || 0;
    }
    return run;
  }

  function computeOverrides(d, orders) {
    if (!d) return null;
    var taker = Number(d.taker_fee);
    if (!isFinite(taker) || taker < 0) taker = 0.0004;
    var iniReplay = field(d, "replay_initial");
    var iniState = field(d, "initial_capital");
    var initial = Number(iniReplay);
    if (!isFinite(initial) || initial <= 0) initial = Number(iniState) || 0;
    var chrono = chronosClosed(orders);
    if (!hasHiddenActive(orders, hiddenMap)) return null;

    var visible = chrono.filter(function (o) {
      return !hiddenMap[String(o.trade_key || "")];
    });
    var done = visible.length;
    var wins = 0;
    var sumPnl = 0;
    for (var j = 0; j < visible.length; j++) {
      var p = Number(visible[j].pnl) || 0;
      sumPnl += p;
      if (p > 0) wins++;
    }
    var wr = done > 0 ? (wins / done) * 100 : 0;
    var hasOpen = orders.some(orderIsOpen);
    var synBal = replayBalanceAfterVisible(chrono, hiddenMap, initial, taker);
    if (hasOpen) {
      var pOpen = Number(field(d, "pnl_open")) || 0;
      var syn = Math.round(synBal * 100) / 100;
      return {
        trades_done: done,
        winrate: Math.round(wr * 100) / 100,
        total_pnl: Math.round(sumPnl * 100) / 100,
        balance: syn,
        pnl_open: pOpen,
        capital_open: Math.round((syn + pOpen) * 100) / 100,
      };
    }
    var b = Math.round(synBal * 100) / 100;
    return {
      trades_done: done,
      winrate: Math.round(wr * 100) / 100,
      total_pnl: Math.round(sumPnl * 100) / 100,
      balance: b,
      pnl_open: 0,
      capital_open: b,
    };
  }

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

  function updateOverview(d, overrides) {
    document.getElementById("statStarted").textContent =
      "Bắt đầu: " + (field(d, "started_at") ? formatDate(field(d, "started_at")) : "—");

    var done =
      overrides && overrides.trades_done != null
        ? overrides.trades_done
        : field(d, "trades_count") || 0;
    document.getElementById("statTradesDone").textContent = "Lệnh đã hoàn thành: " + done;

    document.getElementById("statOrdersOpen").textContent =
      "Lệnh_Open: " + (field(d, "orders_open_count") != null ? field(d, "orders_open_count") : 0);

    var wr =
      overrides && overrides.winrate != null
        ? overrides.winrate
        : field(d, "winrate") != null
          ? field(d, "winrate")
          : 0;
    document.getElementById("statWinrate").textContent =
      "Winrate: " + Number(wr).toFixed(2) + "%";

    var pnl =
      overrides && overrides.total_pnl != null
        ? overrides.total_pnl
        : field(d, "total_pnl") != null
          ? field(d, "total_pnl")
          : 0;
    var elPnl = document.getElementById("statPnl");
    elPnl.textContent = "PNL: " + Number(pnl).toFixed(2);
    elPnl.className = "stat " + (pnl >= 0 ? "positive" : "negative");

    var pnlOpen =
      overrides && overrides.pnl_open != null
        ? overrides.pnl_open
        : field(d, "pnl_open") != null
          ? field(d, "pnl_open")
          : 0;
    var elPnlOpen = document.getElementById("statPnlOpen");
    elPnlOpen.textContent = "PNL_Open: " + Number(pnlOpen).toFixed(2);
    elPnlOpen.className = "stat " + (pnlOpen >= 0 ? "positive" : "negative");

    var bal =
      overrides && overrides.balance != null
        ? overrides.balance
        : field(d, "balance") != null
          ? field(d, "balance")
          : 0;
    document.getElementById("statBalance").textContent = "Vốn: " + Number(bal).toFixed(2);

    var capOpen =
      overrides && overrides.capital_open != null
        ? overrides.capital_open
        : field(d, "capital_open") != null
          ? field(d, "capital_open")
          : field(d, "balance") || 0;
    document.getElementById("statCapitalOpen").textContent =
      "Capital_Open: " + Number(capOpen).toFixed(2);

    setStatusBadge(field(d, "status") || "stopped");
    var levEl = document.getElementById("inputLeverage");
    var pctEl = document.getElementById("inputWalletPct");
    var lbEl = document.getElementById("inputPctLookback");
    var ae = document.activeElement;
    if (levEl != null && ae !== levEl)
      levEl.value = field(d, "leverage_display") != null ? Number(field(d, "leverage_display")) : 20;
    if (pctEl != null && ae !== pctEl)
      pctEl.value =
        field(d, "wallet_pct_display") != null ? Number(field(d, "wallet_pct_display")) * 100 : 30;
    if (lbEl != null && ae !== lbEl) {
      var lbv = field(d, "lookback_display");
      if (lbv != null && lbv !== "") {
        var n = parseInt(String(lbv), 10);
        if (!isNaN(n)) lbEl.value = String(Math.min(200, Math.max(1, n)));
      } else {
        lbEl.value = "15";
      }
    }
  }

  function bindCloseButtons() {
    ordersBody.querySelectorAll(".btn-close-order").forEach(function (btn) {
      btn.addEventListener("click", function () {
        if (!confirm("Chốt lệnh đang mở?")) return;
        fetch(apiBase + "/close", { method: "POST" })
          .then(function (r) {
            return r.json();
          })
          .then(function (d2) {
            if (d2.ok) refresh();
            else alert(d2.error || "Lỗi");
          })
          .catch(function () {
            alert("Lỗi kết nối");
          });
      });
    });
  }

  function refreshPaperCharts() {
    if (window.PaperMiniCharts && typeof window.PaperMiniCharts.update === "function") {
      window.PaperMiniCharts.update(lastOrders, lastStatus, {
        prefix: prefix,
        hiddenMap: hiddenMap,
        slot: slot,
        onOrderSelect: function (id) {
          if (window.PaperOrderNav && typeof window.PaperOrderNav.focusByRowId === "function") {
            window.PaperOrderNav.focusByRowId(id);
          }
        },
      });
    }
  }

  function syncOverviewBar() {
    if (lastStatus) updateOverview(lastStatus, computeOverrides(lastStatus, lastOrders));
    refreshPaperCharts();
  }

  function renderOrders(orders) {
    ordersBody.innerHTML = orders
      .map(function (o, idx) {
        var pnl = o.pnl != null ? o.pnl : 0;
        var rowClass = pnl >= 0 ? "pnl-positive" : "pnl-negative";
        var tk = String(o.trade_key || "");
        var isH = !orderIsOpen(o) && tk && hiddenMap[tk];
        if (isH) rowClass += " is-row-hidden";
        var pnlClass = pnl >= 0 ? "pnl-pos" : "pnl-neg";
        var pnlStr = (pnl >= 0 ? "+" : "") + Number(pnl).toFixed(2);
        var pctVal = o.pct_pnl != null ? Number(o.pct_pnl) : null;
        var pctPnl =
          pctVal != null ? (pctVal >= 0 ? "+" : "") + pctVal.toFixed(2) + "%" : "—";
        var pctCapVal = o.pct_pnl_capital != null ? Number(o.pct_pnl_capital) : null;
        var pctPnlCapital =
          pctCapVal != null ? (pctCapVal >= 0 ? "+" : "") + pctCapVal.toFixed(2) + "%" : "—";
        var capAfter = o.capital_after != null ? Number(o.capital_after).toFixed(2) : "—";
        var id = orderIsOpen(o) ? "•" : o.id != null ? o.id : idx + 1;
        var rowDataId = orderRowDataId(o, idx);
        var actionCell = orderIsOpen(o)
          ? '<td><button type="button" class="btn-close-order" data-open="1">Chốt lệnh</button></td>'
          : "<td></td>";
        var hideCell = orderIsOpen(o)
          ? '<td class="td-hide">—</td>'
          : '<td class="td-hide"><button type="button" class="btn-toggle-hide' +
            (isH ? " is-hidden" : "") +
            '" data-trade-key="' +
            tk +
            '" title="Ẩn/Hiện lệnh (không tính vào thống kê trên khi đang ẩn)">👁</button></td>';
        return (
          '<tr class="' +
          rowClass +
          '" data-order-id="' +
          String(rowDataId).replace(/"/g, "&quot;") +
          '"><td>' +
          id +
          "</td><td>" +
          (o.symbol || "") +
          "</td><td>" +
          (o.side || "") +
          (orderIsOpen(o) ? " (mở)" : "") +
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
          hideCell +
          "</tr>"
        );
      })
      .join("");
    bindCloseButtons();
  }

  function fetchOrdersAndRefreshBar() {
    fetch("/api/orders?slot=" + encodeURIComponent(String(slot)))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        lastOrders = data.orders || [];
        renderOrders(lastOrders);
        syncOverviewBar();
      })
      .catch(function () {});
  }

  function refresh() {
    fetch("/api/status")
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        lastStatus = d;
        return fetch("/api/orders?slot=" + encodeURIComponent(String(slot)));
      })
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        lastOrders = data.orders || [];
        renderOrders(lastOrders);
        syncOverviewBar();
      })
      .catch(function () {});
  }

  document.getElementById("btnStart").addEventListener("click", function () {
    var cap = parseFloat(capitalInput.value);
    if (!(cap > 0)) {
      alert("Nhập vốn > 0");
      return;
    }
    fetch(apiBase + "/start", {
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
    fetch(apiBase + "/pause", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) refresh();
      });
  });
  document.getElementById("btnExportCsv").addEventListener("click", function () {
    window.location.href = "/api/export/csv?slot=" + encodeURIComponent(String(slot));
  });
  document.getElementById("btnStop").addEventListener("click", function () {
    fetch(apiBase + "/stop", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) refresh();
      });
  });
  var btnSaveHidden = document.getElementById("btnSaveHidden");
  if (btnSaveHidden) {
    btnSaveHidden.addEventListener("click", function () {
      persistHidden();
      syncOverviewBar();
      alert("Đã lưu danh sách ẩn/hiện lệnh (trình duyệt).");
    });
  }
  document.getElementById("btnClearHistory").addEventListener("click", function () {
    if (!confirm("Xóa toàn bộ lịch sử lệnh? Vốn và trạng thái sẽ reset. Bạn có chắc?")) return;
    fetch(apiBase + "/clear-history", { method: "POST" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.ok) {
          clearHiddenStorage();
          clearOrderRowHighlight();
          refresh();
          alert(d.message || "Đã xóa toàn bộ lịch sử lệnh.");
        } else alert(d.error || "Lỗi");
      })
      .catch(function () {
        alert("Lỗi kết nối");
      });
  });
  var btnSaveStrategy = document.getElementById("btnSaveStrategy");
  if (btnSaveStrategy != null) {
    btnSaveStrategy.addEventListener("click", function () {
      var lbEl = document.getElementById("inputPctLookback");
      var n = lbEl ? parseInt(String(lbEl.value), 10) : NaN;
      if (isNaN(n) || n < 1 || n > 200) {
        alert("Lookback (số lệnh) phải từ 1 đến 200");
        return;
      }
      fetch(apiBase + "/strategy", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lookback_trades: n }),
      })
        .then(function (r) {
          return r.json();
        })
        .then(function (res) {
          if (res.ok) {
            var el = document.getElementById("inputPctLookback");
            if (el != null && res.paper2_lookback_trades != null)
              el.value = String(res.paper2_lookback_trades);
            refresh();
            alert(res.message || "Đã lưu chiến lược.");
          } else alert(res.error || "Lỗi");
        })
        .catch(function () {
          alert("Lỗi kết nối");
        });
    });
  }

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
    fetch(apiBase + "/capital-rules", {
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
        var pend = slot === 2 ? d.pending_paper2 : d.pending;
        if (!pend) return;
        var msg =
          slot === 2
            ? "Vừa load lại code. Có lệnh paper trade 2 đang mở. Bạn có muốn GIỮ vị thế và tiếp tục? (Cancel = Đóng lệnh và bỏ vị thế)"
            : "Vừa load lại code. Có lệnh paper đang mở. Bạn có muốn GIỮ vị thế và tiếp tục? (Cancel = Đóng lệnh và bỏ vị thế)";
        var keep = confirm(msg);
        fetch("/api/restore-choice", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ keep: keep, slot: slot }),
        })
          .then(function (r) {
            return r.json();
          })
          .then(function () {
            return refresh();
          });
      })
      .catch(function () {});
  }

  document.addEventListener(
    "mousedown",
    function (ev) {
      if (ev.target.closest && ev.target.closest(".paper-charts-row")) return;
      if (window.PaperOrderNav && typeof window.PaperOrderNav.clear === "function") {
        window.PaperOrderNav.clear();
      }
    },
    true
  );

  ordersBody.addEventListener("click", function (ev) {
    var tgt = ev.target;
    if (!tgt || typeof tgt.closest !== "function") return;
    var hideBtn = tgt.closest(".btn-toggle-hide");
    if (!hideBtn) return;
    ev.preventDefault();
    var tk = String(hideBtn.getAttribute("data-trade-key") || "").trim();
    if (!tk) return;
    if (hiddenMap[tk]) delete hiddenMap[tk];
    else hiddenMap[tk] = true;
    persistHidden();
    renderOrders(lastOrders);
    syncOverviewBar();
  });

  refresh();
  checkRestorePending();
  setInterval(refresh, INTERVAL_MS);
  setInterval(fetchOrdersAndRefreshBar, ORDERS_REFRESH_MS);
})();
