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


def send_status_15m():
    """Gửi bản tóm tắt status paper trade – balance ảo, position ảo, PnL, số lệnh."""
    try:
        from bot import state
        d = state.to_status_dict()
        balance = d.get("paper_balance", 0)
        pos = d.get("paper_open_trade")
        pos_str = "Không"
        if pos:
            pos_str = f"{pos.get('side', '')} @ {pos.get('entry_price', 0):.2f}"
        n_trades = d.get("paper_trades_count", 0)
        total_pnl = d.get("paper_total_pnl", 0)
        started = d.get("paper_started_at") or "N/A"
        status = d.get("paper_status", "stopped")
        lines = [
            "📊 [PAPER] Status 15 phút",
            f"Vốn hiện tại: {balance:.2f} USDT",
            f"Position: {pos_str}",
            f"Trạng thái: {status}",
            f"Tổng lệnh (từ khi bắt đầu): {n_trades}",
            f"PNL tổng: {total_pnl:.2f} USDT",
            f"Ngày bắt đầu: {started}",
        ]
        last = d.get("paper_last_trade")
        if last:
            lines.append(f"Lệnh gần nhất PnL: {last.get('profit', 0):.2f}")
        send_message("\n".join(lines))
    except Exception as e:
        send_message(f"Lỗi khi gửi status: {e}")
