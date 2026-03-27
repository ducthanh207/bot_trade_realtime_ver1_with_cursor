# -*- coding: utf-8 -*-
"""
Gửi tin nhắn Telegram: paper/live trade, lỗi.
Quy tắc: mọi thay đổi trạng thái lệnh (mở/đóng) và sự cố (API, server) đều gửi thông báo.
Dùng chung cho paper và sau này kết nối ví Binance thật.
"""

import requests
from config import settings


def send_message(text: str) -> bool:
    """Gửi text tới TELEGRAM_CHAT_ID. Trả True nếu thành công."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r.status_code == 200
    except Exception:
        return False


def _get_current_price() -> float:
    """Lấy giá đóng cửa nến 1m gần nhất từ Binance. Trả 0 nếu lỗi."""
    try:
        from exchange.binance_client import BinanceClient
        client = BinanceClient()
        if not client.is_connected():
            return 0.0
        df = client.get_klines_1m(settings.SYMBOL, limit=1)
        if df.empty:
            return 0.0
        return float(df["close"].iloc[-1])
    except Exception:
        return 0.0


def _atr_pct_sl_sorted(side: str, atr_px: float, pct_px: float, sl_px: float):
    """ATR, %change, stoploss — Long giá tăng dần; Short giá giảm dần."""
    items = []
    if atr_px is not None and atr_px > 0:
        items.append(("ATR", float(atr_px)))
    if pct_px is not None and pct_px > 0:
        items.append(("%change", float(pct_px)))
    if sl_px is not None and sl_px > 0:
        items.append(("stoploss", float(sl_px)))
    if not items:
        return []
    su = str(side).upper()
    if su == "LONG":
        items.sort(key=lambda x: x[1])
    else:
        items.sort(key=lambda x: x[1], reverse=True)
    return items


def _format_status_phuong_phap(method_num: int, d: dict) -> list:
    """Một block Phương pháp 1 hoặc 2 — chỉ khi slot không stopped."""
    from bot import state
    from strategy.risk import max_loss_from_capital
    from strategy.exit_scenarios import build_exit_scenarios_dict

    prefix = "paper" if method_num == 1 else "paper2"
    st = d.get(f"{prefix}_status") or "stopped"
    if st == "stopped":
        return []

    pos = d.get(f"{prefix}_open_trade")
    balance = float(d.get(f"{prefix}_balance") or 0)
    lev = getattr(settings, "LEVERAGE", 20.0)
    if method_num == 1:
        lev = state.get_paper_leverage() or lev
    else:
        lev = state.get_paper2_leverage() or lev

    lines = [f"Phương pháp {method_num}"]

    if not pos:
        lines.append("Position: Không có")
        lines.append("PNL: 0.00 USDT")
        lines.append("PNL%: 0%")
        lines.append("%PNL vốn: 0%")
        lines.append("Điểm vào: —")
        cur = _get_current_price()
        lines.append(f"Giá hiện tại: {cur:.2f}" if cur else "Giá hiện tại: —")
        lines.append("Các điểm đóng: —")
        return lines

    side = str(pos.get("side") or "LONG").upper()
    pos_label = "Long" if side == "LONG" else "Short" if side == "SHORT" else side
    entry = float(pos.get("entry_price") or 0)
    size = float(pos.get("size") or 0)
    margin = pos.get("margin")
    if margin is None and entry and size and lev:
        margin = (entry * size) / lev
    cur = _get_current_price()
    if cur and entry and size:
        if side == "LONG":
            pnl_usdt = (cur - entry) * size
        else:
            pnl_usdt = (entry - cur) * size
        pnl_pct_trade = round((pnl_usdt / margin * 100), 2) if margin else 0
        pnl_pct_capital = round((pnl_usdt / balance * 100), 2) if balance else 0
    else:
        pnl_usdt = 0.0
        pnl_pct_trade = 0.0
        pnl_pct_capital = 0.0

    lines.append(f"Position: {pos_label}")
    lines.append(f"PNL: {pnl_usdt:.2f} USDT")
    lines.append(f"PNL%: {pnl_pct_trade}%")
    lines.append(f"%PNL vốn: {pnl_pct_capital}%")
    lines.append(f"Điểm vào: {entry:.2f}")
    lines.append(f"Giá hiện tại: {cur:.2f}" if cur else "Giá hiện tại: —")

    atr_px = float(pos.get("trail_stop") or 0) or None
    max_loss = max_loss_from_capital(pos)
    sl_px = None
    if size > 0 and max_loss > 0:
        if side == "LONG":
            sl_px = entry - max_loss / size
        else:
            sl_px = entry + max_loss / size

    pct_exit_px = None
    # Chỉ hiển thị điểm %change khi slot tương ứng là phương pháp 2 (paper_slots)
    if method_num == 2:
        try:
            from exchange.binance_client import BinanceClient
            client = BinanceClient()
            df4 = client.get_klines_4h(settings.SYMBOL, limit=200)
            lb = getattr(settings, "LOOKBACK_TRADES", 15)
            v = state.get_paper2_lookback_trades()
            if v is not None:
                lb = min(max(int(v), 1), 200)
            sc = build_exit_scenarios_dict(pos, df4, lb)
            if side == "LONG":
                pct_exit_px = sc.get("pct_upper")
            else:
                pct_exit_px = sc.get("pct_lower")
        except Exception:
            pass

    pts = _atr_pct_sl_sorted(side, atr_px, pct_exit_px, sl_px)
    lines.append("Các điểm đóng:")
    if pts:
        for name, px in pts:
            lines.append(f"   {name}: {px:.2f}")
    else:
        lines.append("   —")
    return lines


def get_status_update_text() -> str:
    """
    Status định kỳ (15p / /now / [1h]): gộp các slot Paper đang bật trên web.
    - Phương pháp 1 = Paper trade (chiến lược cổ điển, không %change trong exit).
    - Phương pháp 2 = Paper trade 2 (chiến lược mới + %change / PCT_CHANGE_TP).
    Mỗi block chỉ gửi khi slot tương ứng không stopped.
    """
    try:
        from bot import state
        d = state.to_status_dict()
        parts = []
        b1 = _format_status_phuong_phap(1, d)
        if b1:
            parts.extend(b1)
        b2 = _format_status_phuong_phap(2, d)
        if b2:
            if parts:
                parts.append("")
            parts.extend(b2)
        if not parts:
            return "Không có Paper trade nào đang bật (cả Phương pháp 1 và 2 đều stopped)."
        sym = getattr(settings, "SYMBOL", "—")
        header = f"Trạng thái Paper ({sym}) — đa phương pháp (cập nhật PP1 + PP2)\n"
        return header + "\n".join(parts)
    except Exception as e:
        return f"Lỗi khi lấy status: {e}"


def send_status_15m():
    """
    Tin nhắn update trạng thái (định kỳ STATUS_INTERVAL_MIN phút). Cùng nội dung với lệnh /now.
    """
    send_message(get_status_update_text())


def send_status_hourly():
    """Báo trạng thái + kịch bản thoát (mỗi STATUS_HOURLY_INTERVAL_MIN phút)."""
    send_message("[1h] " + get_status_update_text())


def _format_dt(v):
    """Chuẩn hóa thời gian hiển thị theo GMT+7."""
    if v is None:
        return "—"
    try:
        from datetime import datetime, timezone, timedelta
        gmt7 = timezone(timedelta(hours=7))
        if hasattr(v, "strftime"):
            dt = v
            if getattr(dt, "tzinfo", None) is not None and hasattr(dt, "astimezone"):
                dt = dt.astimezone(gmt7)
            elif getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc).astimezone(gmt7)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    s = str(v)
    if "T" in s:
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            gmt7 = timezone(timedelta(hours=7))
            if dt.tzinfo and hasattr(dt, "astimezone"):
                dt = dt.astimezone(gmt7)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass
    return s[:16] if len(s) > 16 else s


def notify_trade_closed(closed: dict, source: str = "loop", paper_slot: int = None) -> bool:
    """
    Gửi thông báo đóng lệnh (paper hoặc sau này live).
    source: "loop" | "web" | "telegram"
    paper_slot: 1 = Paper (PP1), 2 = Paper 2 (PP2); hoặc lấy từ closed["paper_slot"].
    """
    if not closed:
        return False
    try:
        try:
            slot = int(paper_slot if paper_slot is not None else closed.get("paper_slot") or 1)
        except (TypeError, ValueError):
            slot = 1
        tag = "[PAPER]" if slot == 1 else "[PAPER2]"
        side = str(closed.get("side", "")).upper()
        profit = float(closed.get("profit", 0))
        cap_before = float(closed.get("capital_before") or 0)
        cap_after = float(closed.get("capital_after") or 0)
        entry_px = closed.get("entry_price")
        exit_px = closed.get("exit_price")
        reason = closed.get("exit_reason") or "—"
        leverage = getattr(settings, "LEVERAGE", 20.0)
        try:
            from bot import state
            if slot == 2:
                leverage = state.get_paper2_leverage() or leverage
            else:
                leverage = state.get_paper_leverage() or leverage
        except Exception:
            pass
        size = float(closed.get("size") or 0)
        entry_f = float(entry_px) if entry_px is not None else 0
        # % PnL = profit / vốn vào lệnh (margin) * 100; % vốn = profit / capital_before * 100
        margin_calc = (entry_f * size) / float(leverage) if (entry_f and size and leverage) else None
        margin = closed.get("margin")
        if margin is None or margin <= 0:
            margin = margin_calc
        if cap_before and margin and margin > cap_before:
            margin = margin_calc
        pct_pnl = round((profit / margin * 100), 2) if margin else 0
        pct_cap = round((profit / cap_before * 100), 2) if cap_before else 0
        pct_sign = "+" if pct_pnl >= 0 else ""
        src_label = {"loop": "Tự động (Loop)", "web": "Web", "telegram": "Telegram"}.get(source, source)
        ep = float(entry_px) if entry_px is not None else 0
        xp = float(exit_px) if exit_px is not None else 0
        lines = [
            f"{tag} 🔴 Đóng lệnh",
            f"Nguồn: {src_label}",
            f"Side: {side}",
            f"Trạng thái: Đã đóng",
            f"PnL: {profit:+.2f} USDT",
            f"% PnL (vốn lệnh): {pct_sign}{pct_pnl}%",
            f"% vốn: {pct_sign}{pct_cap}%",
            f"Vốn sau: {cap_after:.2f} USDT",
            f"Vào: {_format_dt(closed.get('entry_time'))} @ {ep:.2f}",
            f"Ra: {_format_dt(closed.get('exit_time'))} @ {xp:.2f}",
            f"Lý do: {reason}",
        ]
        return send_message("\n".join(lines))
    except Exception:
        return False


def notify_trade_opened(open_trade: dict, source: str = "loop", paper_slot: int = None) -> bool:
    """
    Gửi thông báo mở lệnh. paper_slot: 1 hoặc 2 (hoặc open_trade["paper_slot"]).
    """
    if not open_trade:
        return False
    try:
        try:
            slot = int(paper_slot if paper_slot is not None else open_trade.get("paper_slot") or 1)
        except (TypeError, ValueError):
            slot = 1
        tag = "[PAPER]" if slot == 1 else "[PAPER2]"
        side = str(open_trade.get("side", "")).upper()
        entry_px = float(open_trade.get("entry_price") or 0)
        size = float(open_trade.get("size") or 0)
        src_label = {"loop": "Tự động (Loop)", "web": "Web", "telegram": "Telegram"}.get(source, source)
        lines = [
            f"{tag} 🟢 Mở lệnh",
            f"Nguồn: {src_label}",
            f"Side: {side} @ {entry_px:.2f}",
            f"Size: {size:.4f}",
        ]
        try:
            from strategy.strategies.registry import get_method_label, get_trading_method, uses_pct_change_bands
            m = open_trade.get("trading_method") or get_trading_method()
            lines.append(get_method_label(m))
            if uses_pct_change_bands(m):
                pu = open_trade.get("pct_upper_at_entry")
                pl = open_trade.get("pct_lower_at_entry")
                hw = open_trade.get("pct_half_width_pct")
                if pu is not None and pl is not None:
                    lines.append(
                        f"%change (lúc vào): ±{hw}% — upper {float(pu):.2f} USDT | lower {float(pl):.2f} USDT"
                    )
        except Exception:
            pass
        return send_message("\n".join(lines))
    except Exception:
        return False


def notify_error(message: str, context: str = "app") -> bool:
    """
    Gửi thông báo lỗi (API bị chặn, mất kết nối, server, ...).
    context: "api" | "binance" | "server" | "app"
    """
    try:
        ctx = {"api": "API", "binance": "Binance", "server": "Server", "app": "App"}.get(context, context)
        text = f"⚠️ [{ctx}] {message}"
        return send_message(text)
    except Exception:
        return False
