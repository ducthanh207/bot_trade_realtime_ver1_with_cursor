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


def _exit_levels_sorted(open_trade: dict) -> list:
    """
    Trả về danh sách điểm đóng (tên, giá) sắp xếp từ bé đến lớn.
    ATR trailing, Stoploss có giá; Chiến lược không có giá cố định.
    """
    from strategy.risk import max_loss_from_capital
    side = open_trade.get("side", "LONG")
    entry = float(open_trade.get("entry_price") or 0)
    size = float(open_trade.get("size") or 0)
    trail_stop = float(open_trade.get("trail_stop") or 0)
    max_loss = max_loss_from_capital(open_trade)
    if size <= 0:
        return [("ATR trailing", trail_stop), ("Stoploss", entry), ("Chiến lược", None)]
    if side == "LONG":
        stop_px = entry - max_loss / size
        # Giá từ bé → lớn: Stoploss, ATR, Chiến lược
        ordered = [("Stoploss", stop_px), ("ATR trailing", trail_stop)]
    else:
        stop_px = entry + max_loss / size
        # Giá từ bé → lớn: ATR, Stoploss, Chiến lược
        ordered = [("ATR trailing", trail_stop), ("Stoploss", stop_px)]
    ordered.append(("Chiến lược", None))  # theo tín hiệu 4H, không có giá cố định
    return ordered


def get_status_update_text() -> str:
    """
    Nội dung update trạng thái (dùng cho tin 15 phút và lệnh /now):
    Position, PNL, PNL%, %PNL vốn, Điểm vào, Điểm đóng theo.
    """
    try:
        from bot import state
        d = state.to_status_dict()
        balance = float(d.get("paper_balance") or 0)
        pos = d.get("paper_open_trade")

        # Position: Long, Short, Không có
        if not pos:
            pos_label = "Không có"
        else:
            side = (pos.get("side") or "").strip().upper()
            pos_label = "Long" if side == "LONG" else "Short" if side == "SHORT" else side or "Không có"

        lines = [f"Position: {pos_label}"]

        if pos:
            entry = float(pos.get("entry_price") or 0)
            size = float(pos.get("size") or 0)
            margin = pos.get("margin")
            leverage = getattr(settings, "LEVERAGE", 20.0)
            try:
                from bot import state
                leverage = state.get_paper_leverage() or leverage
            except Exception:
                pass
            if margin is None and entry and size and leverage:
                margin = (entry * size) / leverage
            current_px = _get_current_price()
            if current_px and entry and size:
                if pos_label == "Long":
                    pnl_usdt = (current_px - entry) * size
                else:
                    pnl_usdt = (entry - current_px) * size
                pnl_pct_trade = round((pnl_usdt / margin * 100), 2) if margin else 0
                pnl_pct_capital = round((pnl_usdt / balance * 100), 2) if balance else 0
            else:
                pnl_usdt = 0.0
                pnl_pct_trade = 0.0
                pnl_pct_capital = 0.0

            lines.append(f"PNL: {pnl_usdt:.2f} USDT")
            lines.append(f"PNL%: {pnl_pct_trade}%")
            lines.append(f"%PNL vốn: {pnl_pct_capital}%")
            lines.append(f"Điểm vào: {entry:.2f}")

            # Điểm đóng theo: ATR, Chiến lược, Stoploss (từ bé đến lớn)
            levels = _exit_levels_sorted(pos)
            exit_lines = []
            for name, px in levels:
                if px is not None:
                    exit_lines.append(f"  • {name}: {px:.2f}")
                else:
                    exit_lines.append(f"  • {name}: theo tín hiệu 4H")
            lines.append("Điểm đóng theo (từ bé → lớn):")
            lines.extend(exit_lines)
        else:
            lines.append("PNL: 0.00 USDT")
            lines.append("PNL%: 0%")
            lines.append("%PNL vốn: 0%")
            lines.append("Điểm vào: —")
            lines.append("Điểm đóng theo: —")

        return "\n".join(lines)
    except Exception as e:
        return f"Lỗi khi lấy status: {e}"


def send_status_15m():
    """
    Tin nhắn update trạng thái (định kỳ 15 phút). Cùng nội dung với lệnh /now.
    """
    send_message(get_status_update_text())


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


def notify_trade_closed(closed: dict, source: str = "loop") -> bool:
    """
    Gửi thông báo đóng lệnh (paper hoặc sau này live).
    source: "loop" | "web" | "telegram"
    closed: dict có profit, capital_before, capital_after, side, entry_price, exit_price, exit_reason, ...
    """
    if not closed:
        return False
    try:
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
            "[PAPER] 🔴 Đóng lệnh",
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


def notify_trade_opened(open_trade: dict, source: str = "loop") -> bool:
    """
    Gửi thông báo mở lệnh. source: "loop" | "web" | "telegram"
    """
    if not open_trade:
        return False
    try:
        side = str(open_trade.get("side", "")).upper()
        entry_px = float(open_trade.get("entry_price") or 0)
        size = float(open_trade.get("size") or 0)
        src_label = {"loop": "Tự động (Loop)", "web": "Web", "telegram": "Telegram"}.get(source, source)
        lines = [
            "[PAPER] 🟢 Mở lệnh",
            f"Nguồn: {src_label}",
            f"Side: {side} @ {entry_px:.2f}",
            f"Size: {size:.4f}",
        ]
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
