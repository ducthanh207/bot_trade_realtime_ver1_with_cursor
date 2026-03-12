# -*- coding: utf-8 -*-
"""Gửi tin nhắn Telegram: nội dung dựa trên paper trade (vốn ảo, lệnh ảo)."""

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
            current_px = _get_current_price()
            if current_px and entry and size:
                if pos_label == "Long":
                    pnl_usdt = (current_px - entry) * size
                else:
                    pnl_usdt = (entry - current_px) * size
                notional = entry * size
                pnl_pct_trade = round((pnl_usdt / notional * 100), 2) if notional else 0
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
