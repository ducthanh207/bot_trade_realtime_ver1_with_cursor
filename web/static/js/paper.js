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

  function field(d, name) {
    var k = prefix + "_" + name;
    return d[k];
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

  function updateOverview(d) {
    document.getElementById("statStarted").textContent =
      "Bắt đầu: " + (field(d, "started_at") ? formatDate(field(d, "started_at")) : "—");
    document.getElementById("statTradesDone").textContent =
      "Lệnh đã hoàn thành: " + (field(d, "trades_count") || 0);
    document.getElementById("statOrdersOpen").textContent =
      "Lệnh_Open: " + (field(d, "orders_open_count") != null ? field(d, "orders_open_count") : 0);
    document.getElementById("statWinrate").textContent =
      "Winrate: " + (field(d, "winrate") != null ? field(d, "winrate") : 0) + "%";
    var pnl = field(d, "total_pnl") != null ? field(d, "total_pnl") : 0;
    var elPnl = document.getElementById("statPnl");
    elPnl.textContent = "PNL: " + pnl.toFixed(2);
    elPnl.className = "stat " + (pnl >= 0 ? "positive" : "negative");
    var pnlOpen = field(d, "pnl_open") != null ? field(d, "pnl_open") : 0;
    var elPnlOpen = document.getElementById("statPnlOpen");
    elPnlOpen.textContent = "PNL_Open: " + pnlOpen.toFixed(2);
    elPnlOpen.className = "stat " + (pnlOpen >= 0 ? "positive" : "negative");
    document.getElementById("statBalance").textContent =
      "Vốn: " + (field(d, "balance") != null ? field(d, "balance") : 0).toFixed(2);
    document.getElementById("statCapitalOpen").textContent =
      "Capital_Open: " +
      (field(d, "capital_open") != null
        ? field(d, "capital_open")
        : field(d, "balance") || 0
      ).toFixed(2);
    setStatusBadge(field(d, "status") || "stopped");
    var levEl = document.getElementById("inputLeverage");
    var pctEl = document.getElementById("inputWalletPct");
    var lbEl = document.getElementById("inputPctLookback");
    var ae = document.activeElement;
    // Không ghi đè ô đang gõ (poll trước đây mỗi 1s khiến không sửa được lookback / vốn)
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

  function fetchOrders() {
    fetch("/api/orders?slot=" + encodeURIComponent(String(slot)))
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        var orders = data.orders || [];
        ordersBody.innerHTML = orders
          .map(function (o, idx) {
            var pnl = o.pnl != null ? o.pnl : 0;
            var rowClass = pnl >= 0 ? "pnl-positive" : "pnl-negative";
            var pnlClass = pnl >= 0 ? "pnl-pos" : "pnl-neg";
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2);
            var pctVal = o.pct_pnl != null ? Number(o.pct_pnl) : null;
            var pctPnl =
              pctVal != null ? (pctVal >= 0 ? "+" : "") + pctVal.toFixed(2) + "%" : "—";
            var pctCapVal = o.pct_pnl_capital != null ? Number(o.pct_pnl_capital) : null;
            var pctPnlCapital =
              pctCapVal != null ? (pctCapVal >= 0 ? "+" : "") + pctCapVal.toFixed(2) + "%" : "—";
            var capAfter = o.capital_after != null ? Number(o.capital_after).toFixed(2) : "—";
            var id = o.is_open ? "•" : o.id != null ? o.id : idx + 1;
            var actionCell = o.is_open
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
            fetch(apiBase + "/close", { method: "POST" })
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
  document.getElementById("btnClearHistory").addEventListener("click", function () {
    if (!confirm("Xóa toàn bộ lịch sử lệnh? Vốn và trạng thái sẽ reset. Bạn có chắc?")) return;
    fetch(apiBase + "/clear-history", { method: "POST" })
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

  refresh();
  checkRestorePending();
  setInterval(refresh, INTERVAL_MS);
  setInterval(fetchOrders, ORDERS_REFRESH_MS);
})();
