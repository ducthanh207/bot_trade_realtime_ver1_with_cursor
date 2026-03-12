# Bot VPS Realtime – ATR Strategy

Bot paper trade futures BTCUSDT (chiến lược 4H + RSI/EMA/WMA + ATR trailing), chạy trên VPS hoặc máy.

- **Giá:** Lấy từ Binance qua **API công khai** (https://fapi.binance.com) – **không cần bật profile hay tạo API key**.
- **Paper trade:** Chạy hoàn toàn trên code (VPS/máy), **không dùng** chương trình paper trade của Binance. Lệnh ảo, vốn ảo do bạn đặt trên web.
- **Trade thật sau:** Khi sẵn sàng, cấu hình BINANCE_API_KEY/SECRET và đổi sang `run_live_loop` để đặt lệnh thật trên sàn.

## Cài đặt nhanh

```bash
cd D:\Bot_VPS_Realtime_ver1_11_3_26
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux
pip install -r requirements.txt
cp .env.example .env
# .env.example đã có Telegram. Không cần Binance API key để chạy paper (chỉ cần Telegram).
```

## Chạy

```bash
python run_live.py
```

- Web: http://localhost:5000 — nhập vốn ảo, bấm Kích hoạt, xem lệnh và thống kê.
- Telegram: gửi `/status`, `/pnl`, `/stop` (thông tin paper trade).

## Cấu hình (.env)

| Biến | Mô tả |
|------|--------|
| BINANCE_API_KEY / BINANCE_API_SECRET | **Để trống** khi chỉ paper. Chỉ điền khi bật trade thật. |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | Đã điền sẵn trong .env.example. |
| SYMBOL | Mặc định BTCUSDT |
| LEVERAGE | Đòn bẩy (mặc định 20) |

**Lưu ý:** `.env` nằm trong .gitignore. Sau clone: `cp .env.example .env` là chạy được (chỉ cần Telegram).

Chi tiết file: `FILES_AND_PLAN.md`.
