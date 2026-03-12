# -*- coding: utf-8 -*-
"""
Điểm chạy chính: Paper trade (vốn ảo, giá thật từ Binance).
- Binance chỉ dùng để lấy klines, không đặt lệnh thật.
- Web: số vốn ban đầu, ngày bắt đầu, Kích hoạt / Tạm dừng / Dừng.
- Telegram: đọc và gửi thông tin paper trade.
Sau này trade thật: đổi run_paper_loop -> run_live_loop và cấu hình.
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from exchange.binance_client import BinanceClient
from bot import state
from bot.paper_loop import run_paper_loop
from telegram.notifier import send_message, send_status_15m
from telegram.commands import run_telegram_commands


def main():
    state.set_bot_started_at()
    try:
        from bot.paper_persistence import load_paper_state
        load_paper_state()  # Khôi phục vốn + lệnh từ file (nếu có) sau khi pull/deploy
    except Exception:
        pass
    client = BinanceClient()  # Giá từ API công khai Binance, không cần API key

    def notify(text: str):
        print(text)
        send_message(text)

    def status_callback():
        send_status_15m()

    def run_web_server():
        from web.app import run_web
        run_web()

    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()

    stop_telegram = threading.Event()
    tg_thread = threading.Thread(
        target=run_telegram_commands,
        args=(stop_telegram,),
        daemon=True,
    )
    tg_thread.start()

    try:
        run_paper_loop(client, notify_func=notify, status_func=status_callback)
    except KeyboardInterrupt:
        stop_telegram.set()
        print("Đã dừng.")


if __name__ == "__main__":
    main()
