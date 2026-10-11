# Bảo mật web + chống DDoS nhẹ (roadtopeace.duckdns.org)

Mục tiêu, phù hợp VPS nhỏ:
- Chỉ nginx (HTTPS) được nói chuyện với Flask; cổng 5000 đóng với Internet.
- Toàn bộ web có thêm 1 lớp mật khẩu (trang paper hiện chưa có đăng nhập, ai biết link đều bấm Dừng/Đóng lệnh được).
- Giới hạn request mỗi IP, cắt kết nối chậm, chặn bot quét lỗ hổng.
- fail2ban tự khoá IP dò mật khẩu SSH / web.

File cấu hình có sẵn trong repo: `deploy/nginx/bot-web.conf`, `deploy/nginx/bot-ratelimit.conf`, `deploy/fail2ban/jail.local`.

Mọi lệnh dưới đây chạy **trong VPS** (`ssh root@103.179.188.159`), gõ từng khối.

## Bước 0. Sao lưu + lấy code mới

```bash
cd ~/Bot_VPS_Realtime_ver1_11_3_26
cp -r /etc/nginx ~/backup_nginx_$(date +%Y%m%d_%H%M)
git pull origin main
ls /etc/letsencrypt/live/          # phải thấy roadtopeace.duckdns.org
ls /etc/nginx/sites-enabled/       # xem đang bật file nào
```

## Bước 1. Flask chỉ nghe nội bộ + cookie an toàn + mật khẩu mạnh

```bash
nano .env
```
Thêm / sửa các dòng (mật khẩu /live nên ≥ 16 ký tự, không dùng lại ở chỗ khác):
```
WEB_HOST=127.0.0.1
WEB_COOKIE_SECURE=true
LIVE_ADMIN_PASSWORD=mat-khau-moi-dai-it-nhat-16-ky-tu
```
Ctrl+O, Enter để lưu, Ctrl+X để thoát. Rồi:
```bash
sudo systemctl restart bot-live
sleep 10
ss -ltnp | grep 5000               # phải thấy 127.0.0.1:5000, KHÔNG phải 0.0.0.0:5000
```
Từ giờ `http://103.179.188.159:5000` không vào được nữa, chỉ vào qua `https://roadtopeace.duckdns.org`.

## Bước 2. Tạo mật khẩu lớp ngoài (nginx)

Thay `aster` bằng tên đăng nhập bạn muốn. Lệnh sẽ hỏi mật khẩu 2 lần (không hiện ký tự):
```bash
printf "aster:$(openssl passwd -apr1)\n" | sudo tee /etc/nginx/.htpasswd
sudo chown root:www-data /etc/nginx/.htpasswd
sudo chmod 640 /etc/nginx/.htpasswd
```

## Bước 3. Cài cấu hình nginx mới

```bash
sudo cp deploy/nginx/bot-ratelimit.conf /etc/nginx/conf.d/
sudo cp deploy/nginx/bot-web.conf /etc/nginx/sites-available/bot-web
grep -l roadtopeace /etc/nginx/sites-enabled/*
```
Nếu lệnh `grep` hiện file nào **khác** `bot-web` (vd `default`), gỡ nó ra để không trùng:
`sudo rm /etc/nginx/sites-enabled/default` (thay `default` bằng tên file hiện ra).

```bash
sudo ln -sf /etc/nginx/sites-available/bot-web /etc/nginx/sites-enabled/bot-web
sudo nginx -t
```
- Thấy `syntax is ok` và `test is successful` → `sudo systemctl reload nginx`.
- Báo lỗi → **không reload**, chụp lỗi gửi lại. Quay về bản cũ:
  `sudo rm /etc/nginx/conf.d/bot-ratelimit.conf && sudo cp ~/backup_nginx_*/sites-available/* /etc/nginx/sites-available/ && sudo nginx -t && sudo systemctl reload nginx`

## Bước 4. Tường lửa

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5000/tcp
sudo ufw enable                    # hỏi y/n → gõ y
sudo ufw status
```
(Luôn để dòng `allow 22` trước `enable`, nếu không sẽ tự khoá SSH.)

## Bước 5. fail2ban

```bash
sudo apt update && sudo apt install -y fail2ban
sudo cp deploy/fail2ban/jail.local /etc/fail2ban/jail.local
sudo systemctl enable --now fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status
```
Sai mật khẩu SSH/web 5 lần trong 10 phút → IP bị khoá 1 giờ. Nếu lỡ tự khoá mình: đợi 1 giờ, hoặc vào console web của nhà cung cấp VPS và gõ `sudo fail2ban-client unban --all`.

## Bước 6. Kiểm tra

1. Mở `https://roadtopeace.duckdns.org` → trình duyệt hỏi tên + mật khẩu (Bước 2) → vào trang paper bình thường.
2. Mở `/live` → đăng nhập bằng `LIVE_ADMIN_PASSWORD` mới.
3. Trên máy Windows, mở `http://103.179.188.159:5000` → phải **không** vào được.
4. Telegram vẫn hoạt động (bot Telegram không đi qua web).

## Mức bảo vệ này chặn được gì

| Mối nguy | Cách chặn |
|---|---|
| Người lạ vào link bấm Dừng/Đóng lệnh paper | Mật khẩu nginx cho toàn web |
| Dò mật khẩu /live | 10 lần/phút/IP + khoá 10 phút trong app + fail2ban |
| Spam request / flood nhẹ từ vài IP | 10 req/s/IP, 20 kết nối/IP, fail2ban khoá IP vượt ngưỡng |
| Slowloris (kết nối treo) | Timeout 10s cho header/body |
| Bot quét `.env`, `.git`, wordpress | Trả 444 (cắt kết nối) |
| Bỏ qua nginx, đánh thẳng cổng 5000 | Flask chỉ nghe 127.0.0.1 + ufw chặn 5000 |
| Dò mật khẩu SSH | fail2ban sshd |

**Không chặn được DDoS lớn** (hàng nghìn IP, băng thông lớn). Muốn chống loại đó cần đưa tên miền riêng của bạn lên Cloudflare (miễn phí, bật proxy mây cam) và chỉ cho phép IP Cloudflare vào cổng 443. DuckDNS không dùng được với Cloudflare proxy.

## Nên làm thêm (tuỳ chọn)

- Đăng nhập SSH bằng khoá thay vì mật khẩu (`ssh-keygen` trên Windows, `ssh-copy-id`), rồi tắt đăng nhập mật khẩu. Chỉ làm khi đã chắc chắn vào được bằng khoá.
- API key Binance: chỉ bật Futures, tắt Withdraw, giới hạn IP VPS (xem `docs/LIVE_TRADING.md`).
- `sudo apt install unattended-upgrades` để VPS tự vá bảo mật.
