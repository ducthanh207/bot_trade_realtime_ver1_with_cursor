# -*- coding: utf-8 -*-
"""
Điểm chạy chính:
- Paper trade (vốn ảo, giá thật từ Binance) — PP1–PP4 trên SYMBOL, như trước.
- Trade thật (live/engine.py) — chạy song song, cấu hình hoàn toàn trên web /live
  (tài khoản sàn, Telegram, bot = cặp coin × chiến lược). Mặc định công tắc trade thật TẮT.
- Web: paper + /live. Telegram: lệnh paper (.env) + bảng điều khiển /live.
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

    # Trade thật: lỗi khởi động ở đây không được làm dừng paper trade
    try:
        from live.engine import start_engine_thread
        from live.telegram_ctl import start_poller_manager
        start_engine_thread()
        start_poller_manager()
    except Exception as e:
        print("[LIVE] Không khởi động được engine trade thật:", e)

    try:
        run_paper_loop(client, notify_func=notify, status_func=status_callback)
    except KeyboardInterrupt:
        stop_telegram.set()
        print("Đã dừng.")


if __name__ == "__main__":
    main()
