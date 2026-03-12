# Danh sách file – Bot VPS Realtime

## Thư mục gốc: `D:\Bot_VPS_Realtime_ver1_11_3_26`

**Chế độ hiện tại: Paper trade** – Binance chỉ dùng để lấy giá (klines), không đặt lệnh thật. Trên web: nhập vốn ban đầu, bấm Kích hoạt (tính từ ngày đó), Tạm dừng / Dừng. Telegram đọc và gửi thông tin paper. Khi sẵn sàng trade thật: đổi `run_live.py` gọi `run_live_loop` thay vì `run_paper_loop`.

---

### 1. Cấu hình & môi trường

| File | Mục đích |
|------|----------|
| `.env.example` | Mẫu biến môi trường (BINANCE_KEY, BINANCE_SECRET, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID); copy thành `.env` trên VPS và điền. |
| `.gitignore` | Bỏ qua `.env`, `__pycache__`, `logs/`, `*.log`, `*.db`. |
| `requirements.txt` | Pip: python-binance, pandas, pandas-ta, requests, python-dotenv, flask. |
| `config/settings.py` | Đọc từ `os.environ` + `.env`: symbol, leverage, fee, RSI/ATR tham số, đường dẫn; export biến dùng toàn project. |

---

### 2. Chiến lược (tách từ test_chien_luoc_ATR_ver_6)

| File | Mục đích |
|------|----------|
| `strategy/__init__.py` | Package; export signals, indicators, risk. |
| `strategy/indicators.py` | Tính RSI, EMA_RSI (WMA 9), WMA_RSI (45), ATR trên DataFrame 4h (pandas_ta). |
| `strategy/signals.py` | long_entry, short_entry, long_exit, short_exit, long_exit_early, short_exit_early (nhận prev_row, row). |
| `strategy/risk.py` | size_and_margin, check_atr_trailing, max_loss_from_capital, limit_pnl_and_exit_price; hằng số từ config. |

---

### 3. Sàn (Binance)

| File | Mục đích |
|------|----------|
| `exchange/__init__.py` | Package. |
| `exchange/binance_client.py` | Class BinanceClient: get_klines_4h(), get_klines_1m(), get_balance(), get_position(), place_market_order(), close_position(); dùng python-binance Futures, đọc key từ config. |

---

### 4. Bot

| File | Mục đích |
|------|----------|
| `bot/__init__.py` | Package. |
| `bot/state.py` | Trạng thái: real (balance, position, ...) + **paper** (paper_balance, paper_started_at, paper_status, paper_trades, paper_open_trade); paper_start/paper_pause/paper_stop. |
| `bot/paper_loop.py` | **Đang dùng:** Vòng paper: lấy 4h/1m từ Binance, logic giống live nhưng chỉ cập nhật paper_*; không gọi đặt lệnh. Chạy khi paper_status = running; paused vẫn xử lý thoát. |
| `bot/live_loop.py` | Dành cho trade thật sau: đặt/đóng lệnh trên Binance. |

---

### 5. Telegram

| File | Mục đích |
|------|----------|
| `telegram/__init__.py` | Package. |
| `telegram/notifier.py` | Hàm send_message(text): gửi tin nhắn tới TELEGRAM_CHAT_ID; gọi khi mở/đóng lệnh, lỗi; hàm send_status_15m(): nội dung status 15 phút (balance, position, PnL ngày). |
| `telegram/commands.py` | Long poll (hoặc threading) nhận update: /status, /pnl, /stop, /start, /ping; trả lời trong Telegram; /stop có thể set flag để live_loop dừng đặt lệnh mới. |

---

### 6. Web trạng thái

| File | Mục đích |
|------|----------|
| `web/__init__.py` | Package. |
| `web/app.py` | Flask app: route `/` hoặc `/api/status` trả JSON (balance, position, last_trade, uptime); có thể thêm trang HTML đơn giản đọc JSON. |
| `web/templates/status.html` | (Tùy chọn) Trang HTML hiển thị balance, position, PnL, lịch sử gần nhất. |

---

### 7. Điểm chạy & script

| File | Mục đích |
|------|----------|
| `run_live.py` | Script chính: load .env, khởi tạo config, Binance client, state, telegram notifier; chạy live_loop trong thread; chạy Flask trong thread khác (hoặc process); (tùy chọn) chạy telegram commands trong thread; giữ process chạy 24/7. |
| `scripts/deploy.sh` | Trên VPS: git pull, restart systemd service (vd systemctl restart bot-live). |
| `scripts/update_duckdns.sh` | Cập nhật IP hiện tại lên DuckDNS (nếu dùng). |

---

### 8. Systemd (chạy trên VPS, không nằm trong repo)

Tạo file `/etc/systemd/system/bot-live.service`:

```ini
[Unit]
Description=Bot Trading Live
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/Bot_VPS_Realtime_ver1_11_3_26
ExecStart=/home/ubuntu/Bot_VPS_Realtime_ver1_11_3_26/.venv/bin/python run_live.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/Bot_VPS_Realtime_ver1_11_3_26/.env

[Install]
WantedBy=multi-user.target
```

Sau đó: `sudo systemctl daemon-reload && sudo systemctl enable bot-live && sudo systemctl start bot-live`

---

### 9. Tổng số file cần tạo trong repo

- `.env.example`, `.gitignore`, `requirements.txt`
- `config/settings.py`
- `strategy/__init__.py`, `strategy/indicators.py`, `strategy/signals.py`, `strategy/risk.py`
- `exchange/__init__.py`, `exchange/binance_client.py`
- `bot/__init__.py`, `bot/state.py`, `bot/live_loop.py`
- `telegram/__init__.py`, `telegram/notifier.py`, `telegram/commands.py`
- `web/__init__.py`, `web/app.py`, `web/templates/status.html` (optional)
- `run_live.py`
- `scripts/deploy.sh`, `scripts/update_duckdns.sh`
- `FILES_AND_PLAN.md` (file này)

Sau khi có danh sách này, bước tiếp theo: tạo lần lượt từng file và code nội dung để deploy thật (đọc key từ .env, gửi lệnh Binance, gửi Telegram thật).
