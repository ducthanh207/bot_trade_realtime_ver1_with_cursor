(function () {
  const INTERVAL_MS = 5000;
  const ORDERS_REFRESH_MS = 1000;

  const capitalInput = document.getElementById("initial_capital");
  const statusBadge = document.getElementById("statusBadge");
  const ordersBody = document.getElementById("ordersBody");

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

  refresh();
  checkRestorePending();
  setInterval(refresh, INTERVAL_MS);
  setInterval(fetchOrders, ORDERS_REFRESH_MS);
})();
