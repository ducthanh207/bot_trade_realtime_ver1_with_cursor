# Truy cập web qua https://roadtopeace.duckdns.org/

## Vì sao URL chưa dùng được?

- Trình duyệt mở **https://roadtopeace.duckdns.org/** sẽ kết nối tới **cổng 443** (HTTPS).
- Trên VPS hiện chỉ có **Flask chạy cổng 5000**, không có dịch vụ nào lắng nghe **80** và **443**.
- Nên dù DuckDNS đã trỏ đúng IP, vẫn không có gì trả nội dung khi vào `https://...` hoặc `http://...` (cổng 80).

**Cách tạm thời (không HTTPS):** Nếu chỉ cần xem nhanh và mở port 5000 trên firewall, có thể dùng:
`http://roadtopeace.duckdns.org:5000/` (phải gõ đúng `:5000`).

---

## Cần làm gì để https://roadtopeace.duckdns.org/ dùng được?

1. **DuckDNS** trỏ tên miền về IP VPS (103.179.188.159).
2. Trên **VPS**: cài **Nginx** (hoặc Caddy) làm reverse proxy: lắng nghe 80/443, chuyển request tới Flask (127.0.0.1:5000).
3. Cài **SSL** (Let's Encrypt) để dùng HTTPS.
4. **Firewall** mở cổng 80 và 443.

---

## Bước 1: Kiểm tra DuckDNS

- Vào https://www.duckdns.org/ → đăng nhập → domain **roadtopeace**.
- Kiểm tra IP hiển thị = **103.179.188.159** (IP VPS của bạn).
- Nếu khác, cập nhật IP (hoặc chạy script trong repo):
  ```bash
  # Trong .env thêm (hoặc export):
  # DUCKDNS_DOMAIN=roadtopeace
  # DUCKDNS_TOKEN=<token của bạn từ duckdns.org>
  bash scripts/update_duckdns.sh
  ```

---

## Bước 2: Trên VPS – Cài Nginx và Certbot

SSH vào VPS: `ssh root@103.179.188.159`

```bash
apt update
apt install -y nginx certbot python3-certbot-nginx
```

---

## Bước 3: Cấu hình Nginx (reverse proxy sang Flask)

Tạo file cấu hình:

```bash
sudo nano /etc/nginx/sites-available/bot-web
```

Dán nội dung (thay `roadtopeace.duckdns.org` nếu bạn dùng tên khác):

```nginx
server {
    listen 80;
    server_name roadtopeace.duckdns.org;
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Kích hoạt site và kiểm tra:

```bash
sudo ln -sf /etc/nginx/sites-available/bot-web /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

Lúc này **http://roadtopeace.duckdns.org/** (cổng 80) sẽ mở được (chưa HTTPS).

---

## Bước 4: Bật HTTPS với Let's Encrypt

```bash
sudo certbot --nginx -d roadtopeace.duckdns.org
```

Làm theo hướng dẫn (nhập email, đồng ý điều khoản). Certbot sẽ tự cấu hình Nginx cho HTTPS và redirect HTTP → HTTPS.

Sau bước này, **https://roadtopeace.duckdns.org/** sẽ dùng được.

---

## Bước 5: Firewall (nếu đang bật ufw)

```bash
sudo ufw allow 80
sudo ufw allow 443
sudo ufw allow 22
sudo ufw enable
sudo ufw status
```

---

## Tóm tắt

| Việc | Mục đích |
|------|----------|
| DuckDNS trỏ đúng IP | Tên miền → VPS |
| Nginx reverse proxy | Cổng 80/443 → Flask :5000 |
| Certbot | SSL cho https:// |
| Mở 80, 443 | Trình duyệt kết nối được |

Sau khi xong, bạn chỉ cần mở **https://roadtopeace.duckdns.org/** là xem được bản web (không cần gõ :5000).
