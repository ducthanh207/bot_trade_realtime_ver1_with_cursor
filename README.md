# Bot VPS Realtime – ATR Strategy

Bot paper trade futures BTCUSDT (chiến lược 4H + RSI/EMA/WMA + ATR trailing), chạy trên VPS hoặc máy.

- **Giá:** Lấy từ Binance qua **API công khai** (https://fapi.binance.com) – **không cần bật profile hay tạo API key**.
- **Paper trade:** Chạy hoàn toàn trên code (VPS/máy), **không dùng** chương trình paper trade của Binance. Lệnh ảo, vốn ảo do bạn đặt trên web.
- **Trade thật:** trang web `/live` — nhập tài khoản Binance Futures, bot Telegram, chọn cặp coin × chiến lược × tài khoản, bật/tắt. Không cần sửa code; chỉ cần `LIVE_ADMIN_PASSWORD` trong `.env`. Chi tiết + hướng dẫn deploy VPS: `docs/LIVE_TRADING.md`.

## Cài đặt nhanh

```bash
cd D:\Bot_VPS_Realtime_ver1_11_3_26
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux
pip install -r requirements.txt
cp .env.example .env
# Điền TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID cho paper; LIVE_ADMIN_PASSWORD cho trang /live.
```

## Chạy

```bash
python run_live.py
```

- Web: http://localhost:5000 — nhập vốn ảo, bấm Kích hoạt, xem lệnh và thống kê.
- Telegram: gửi `/status`, `/pnl`, `/stop` (thông tin paper trade).
- Trade thật: http://localhost:5000/live (đăng nhập bằng `LIVE_ADMIN_PASSWORD`); Telegram `/live` mở bảng điều khiển.

## Cấu hình (.env)

| Biến | Mô tả |
|------|--------|
| BINANCE_API_KEY / BINANCE_API_SECRET | Để trống. Key trade thật nhập trên web `/live` (mã hoá, lưu ở `data/live/`). |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | Bot Telegram của paper trade. |
| LIVE_ADMIN_PASSWORD | Mật khẩu trang `/live` (bắt buộc để dùng trade thật). |
| SYMBOL | Mặc định BTCUSDT |
| LEVERAGE | Đòn bẩy (mặc định 20) |

**Lưu ý:** `.env` và `data/` nằm trong .gitignore.

Chi tiết file: `FILES_AND_PLAN.md`.
