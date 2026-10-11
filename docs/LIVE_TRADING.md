# Trade thật: Binance Futures + Telegram + dashboard /live

Mọi kết nối (tài khoản sàn, bot Telegram, cặp coin × chiến lược) đều nhập trên web, **không sửa code, không nhét key vào .env**.
Chỉ cần một dòng mật khẩu trong `.env` để khoá trang `/live`.

## 1. Cách hoạt động

- `run_live.py` chạy song song: paper trade PP1–PP4 (như cũ) + **engine trade thật** (`live/engine.py`).
- Mỗi **bot** = 1 tài khoản sàn × 1 cặp coin × 1 chiến lược (PP1–PP4) × vốn phân bổ / đòn bẩy / % vốn mỗi lệnh.
- Bot dùng **đúng logic vào/ra lệnh của paper** (`bot/slot_engine.py`, dùng chung cho cả hai), chỉ khác là đặt lệnh MARKET thật và ghi sổ theo **giá khớp + phí thật** từ Binance.
- Vào lệnh chỉ trong 5 phút đầu mỗi nến 4H (03h, 07h, 11h, 15h, 19h, 23h giờ VN), giống paper.
- Vốn bot = vốn phân bổ, cộng dồn lãi/lỗ của bot (giống paper). Size = vốn bot × % vốn × đòn bẩy, làm tròn xuống theo bước khối lượng của sàn.

### Ba lớp công tắc (mặc định đều TẮT)

| Công tắc | Ở đâu | Khi TẮT |
|---|---|---|
| **Trade thật** (tổng) | đầu trang `/live`, Telegram `/live` | Không bot nào mở lệnh mới. Lệnh đang mở **vẫn được quản lý thoát**. Có tín hiệu thì báo "📡 Tín hiệu … KHÔNG đặt lệnh". |
| **Tài khoản** | tab Tài khoản sàn | Bot của tài khoản đó không mở lệnh mới. |
| **Bot**: Chạy / Tạm dừng / Dừng | bảng bot, Telegram | Tạm dừng / Dừng: không mở lệnh mới; nếu còn lệnh thì vẫn quản lý thoát. |

Nút **Đóng tất cả vị thế** (web) / **🛑 Đóng tất cả** (Telegram): tắt công tắc tổng + đóng MARKET mọi lệnh của bot.

### An toàn

- **Stop dự phòng trên sàn** (mặc định "theo trailing stop"): ngay khi vào lệnh, bot đặt lệnh `STOP_MARKET closePosition` trên Binance tại mức chặt hơn giữa trailing stop và mức lỗ tối đa (hard stop), rồi dời theo trailing. Nếu VPS/bot tắt, vị thế vẫn được bảo vệ.
- Lệnh bị đóng ngoài bot (stop trên sàn khớp, thanh lý, bạn đóng tay trên app) → bot phát hiện sau ~10 giây và ghi sổ theo giá khớp thật (lý do `EXCHANGE_STOP` / `EXCHANGE_CLOSED`).
- Mỗi tài khoản chỉ 1 bot / cặp coin. Nếu tài khoản đang có vị thế cặp đó **không do bot mở**, bot bỏ qua tín hiệu và báo Telegram.
- Lệnh quá nhỏ (dưới mức tối thiểu sàn, vd BTCUSDT cần ≥ 100 USDT giá trị lệnh) hoặc không đủ số dư khả dụng → bỏ qua + báo.
- API key / secret / token Telegram được mã hoá (Fernet) trong `data/live/config.json`; khoá ở `data/live/secret.key` (quyền 600). Web chỉ hiện 4 ký tự đầu/cuối. Thư mục `data/` nằm trong `.gitignore`.
- Trang `/live` bắt buộc đăng nhập (sai 5 lần → khoá 10 phút), mọi thao tác có CSRF token.

## 2. Telegram

Thêm kết nối ở tab **Telegram** (có thể thêm nhiều bot / nhiều chat):
- **Báo mở / đóng lệnh**: giá khớp, khối lượng, PnL, lý do thoát.
- **Báo cáo mỗi giờ** (đầu giờ): số dư từng tài khoản + % thay đổi so với 1 giờ trước, từng bot: vốn, % /1h, tổng PnL, % từ đầu, PnL hôm nay, vị thế đang mở + uPnL.
- **Báo lỗi**: lỗi API, không đặt được stop, …
- **Cho phép điều khiển**: gõ `/live` → bảng nút bấm (bật/tắt trade thật, chạy/tạm dừng từng bot, đóng lệnh có bước xác nhận, xem status). Lệnh khác: `/live_status`, `/live_on`, `/live_off`, `/live_closeall`.
  Bot chỉ nhận lệnh từ đúng Chat ID đã nhập.

Có thể dùng **lại bot Telegram của paper** (token trong `.env`): nhập cùng token trên web, lệnh `/live…` sẽ chạy qua luồng sẵn có, lệnh paper (`/status`, `/trade`, …) giữ nguyên.

Lấy Chat ID: nhắn cho bot một tin bất kỳ → mở `https://api.telegram.org/bot<TOKEN>/getUpdates` → xem `"chat":{"id": …}`.

## 3. Tạo API key Binance

1. Binance → **API Management** → Create API (System generated).
2. Quyền: bật **Enable Futures**. **Không** bật Withdrawals.
3. **Restrict access to trusted IPs only** → nhập IP VPS (`103.179.188.159`).
4. Muốn thử trước: tạo key ở testnet (https://testnet.binancefuture.com) và chọn môi trường *Testnet* khi thêm tài khoản (hoặc *Demo trading* nếu key tạo ở demo.binance.com).
   Lưu ý: tín hiệu luôn tính trên giá Binance thật; trên testnet giá khớp có thể lệch một chút.
5. Bot hỗ trợ cả One-way và Hedge mode, Cross hoặc Isolated (dùng cài đặt sẵn của tài khoản cho từng cặp).

## 4. Deploy lên VPS

VPS hiện chạy ở `/root/Bot_VPS_Realtime_ver1_11_3_26`, service `bot-live`.

```bash
ssh root@103.179.188.159
cd ~/Bot_VPS_Realtime_ver1_11_3_26

# 0) Sao lưu trạng thái paper + .env (phòng khi cần quay lại)
cp paper_state.json ~/paper_state.backup.$(date +%Y%m%d%H%M).json
cp .env ~/env.backup.$(date +%Y%m%d%H%M)
git rev-parse HEAD > ~/commit_truoc_khi_update.txt

# 1) Lấy code mới (sau khi merge PR vào main)
git fetch origin
git status            # nếu có file sửa tay trên VPS, git sẽ báo — xem lại trước khi pull
git pull origin main

# 2) Cài thư viện mới (cryptography)
source .venv/bin/activate
pip install -r requirements.txt

# 3) Đặt mật khẩu trang /live (đổi chuỗi bên dưới)
echo 'LIVE_ADMIN_PASSWORD=doi_mat_khau_dai_o_day' >> .env
# Nếu web đã chạy HTTPS (nginx + certbot):
# echo 'WEB_COOKIE_SECURE=true' >> .env

# 4) Khởi động lại và xem log
sudo systemctl restart bot-live
journalctl -u bot-live -f
# Thấy dòng: [LIVE] Engine trade thật đã khởi động (công tắc tổng: TẮT)  → OK. Ctrl+C để thoát log.
```

Nếu muốn chạy thử nhánh trước khi merge: thay bước 1 bằng
`git fetch origin claude/live-trading-dashboard-0vg26h && git checkout claude/live-trading-dashboard-0vg26h`.

Quay lại bản cũ nếu có vấn đề: `git checkout $(cat ~/commit_truoc_khi_update.txt) && sudo systemctl restart bot-live`
(dữ liệu trong `data/live/` và `paper_state.json` không bị đụng tới).

**Nên bật HTTPS trước khi nhập API key** (xem `docs/WEB_DOMAIN_SETUP.md`). Nếu vào web bằng `http://…:5000`, mật khẩu và key đi qua mạng dạng không mã hoá.

## 5. Bật trade thật lần đầu

1. Mở `https://roadtopeace.duckdns.org/live` (hoặc `http://103.179.188.159:5000/live`) → đăng nhập.
2. Tab **Telegram** → thêm token + Chat ID → **Gửi thử**.
3. Tab **Tài khoản sàn** → thêm tài khoản, dán API key + secret → **Kiểm tra** (phải hiện số dư) → **Bật**.
4. **+ Thêm bot** → chọn tài khoản, cặp (vd `BTCUSDT`), chiến lược (vd PP4), vốn phân bổ, đòn bẩy, % vốn → **Lưu bot** → bấm **Chạy**.
5. Bật công tắc **Trade thật** ở đầu trang (hoặc `/live` trên Telegram).
6. Đợi cửa sổ nến 4H kế tiếp. Lệnh mở/đóng sẽ báo Telegram và hiện trong bảng.

## 6. Sao lưu

Sao lưu cả thư mục `data/live/` (đặc biệt `secret.key`). Mất `secret.key` → phải nhập lại API key / token trên web; lịch sử lệnh vẫn còn trong `state.json`.

## 7. File liên quan

| File | Vai trò |
|---|---|
| `bot/slot_engine.py` | Một bước chiến lược (vào/ra lệnh) dùng chung cho paper và trade thật |
| `live/engine.py` | Vòng lặp trade thật, đặt lệnh, stop trên sàn, đối chiếu vị thế, báo cáo giờ |
| `live/store.py` | Lưu cấu hình + trạng thái vào `data/live/` |
| `live/secrets_box.py` | Mã hoá key |
| `live/telegram_ctl.py` | Thông báo + bảng điều khiển Telegram |
| `exchange/binance_futures.py` | Client Binance USDⓈ-M có ký HMAC (mainnet / testnet / demo) |
| `web/live_routes.py`, `web/templates/live.html`, `web/static/js/live.js` | Trang `/live` |
