# Tự động deploy bot lên VPS khi merge PR

Sau khi cài xong, mỗi lần bạn **merge PR vào `main`** (bấm Merge trên app GitHub là đủ),
GitHub sẽ tự SSH vào VPS, lấy code mới và restart bot. Không cần mở terminal nữa.

## Mỗi lần deploy, hệ thống làm gì

1. Sao lưu `paper_state.json` và thư mục `data/` vào `~/deploy_backups/<ngày_giờ>/` (giữ 10 bản gần nhất).
2. Lấy code mới từ `main`. Chỉ cập nhật khi không có xung đột:
   nếu VPS có file sửa tay thì **dừng lại, không restart**, bot vẫn chạy code cũ.
3. Nếu `requirements.txt` đổi thì tự `pip install`.
4. Kiểm tra cú pháp các file Python vừa đổi. Lỗi thì quay về code cũ, không restart.
5. Restart `bot-live`, chờ 20 giây, kiểm tra bot còn chạy và không bị crash.
   Có vấn đề thì **tự quay về commit cũ** và restart lại.

Không bao giờ đụng tới `.env`, `paper_state.json`, `data/` (API key, lệnh đang mở).
PR chỉ sửa tài liệu (`*.md`, `docs/`) thì không restart bot.

---

## Cài đặt một lần (làm được hoàn toàn bằng điện thoại)

Cần: app SSH (**Termius** cho iOS/Android) đã vào được VPS, và trình duyệt điện thoại.

### Bước 1 — Kiểm tra VPS sạch sẽ

Trong Termius, vào VPS rồi chạy:
```
cd ~/Bot_VPS_Realtime_ver1_11_3_26 && git status --short && git log --oneline -1
```
- Không in ra dòng nào bắt đầu bằng ` M` là ổn (các dòng `??` không sao).
- Có dòng ` M ten_file`: VPS đang có file sửa tay, deploy tự động sẽ dừng lại.
  Lưu lại rồi bỏ sửa tay: `git diff > ~/sua_tay.patch && git stash`.

### Bước 2 — Tạo SSH key riêng cho GitHub (trên VPS)

```
ssh-keygen -t ed25519 -N "" -C github-deploy -f ~/.ssh/github_deploy
cat ~/.ssh/github_deploy.pub >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

Xem private key để copy:
```
cat ~/.ssh/github_deploy
```
Copy **toàn bộ** từ dòng `-----BEGIN OPENSSH PRIVATE KEY-----` đến hết dòng
`-----END OPENSSH PRIVATE KEY-----` (trong Termius: nhấn giữ màn hình, chọn vùng chữ, Copy).

Xem host key của VPS (để chống giả mạo VPS, không bắt buộc nhưng nên làm):
```
cat /etc/ssh/ssh_host_ed25519_key.pub
```

> Key này **chỉ dán vào GitHub Secrets**, không gửi vào chat, Telegram hay bất kỳ đâu khác.

### Bước 3 — Thêm Secrets trên GitHub

App GitHub trên điện thoại chưa có mục Secrets, nên dùng **trình duyệt** (Chrome/Safari):

1. Mở `https://github.com/ducthanh207/bot_trade_realtime_ver1_with_cursor/settings/secrets/actions`
   (nếu giao diện bị thu gọn, bật "Trang web cho máy tính" / "Request Desktop Website").
2. Bấm **New repository secret**, thêm lần lượt:

| Name | Secret (giá trị) |
|---|---|
| `VPS_HOST` | IP của VPS (VPS mới thì dùng IP mới) |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | toàn bộ private key đã copy ở bước 2 |
| `VPS_HOST_KEY` | dòng `ssh-ed25519 AAAA...` ở bước 2 (không bắt buộc) |
| `VPS_PORT` | chỉ thêm nếu SSH không dùng cổng 22 |

Khi đã dán xong vào GitHub, có thể xoá private key khỏi VPS cho gọn:
`rm ~/.ssh/github_deploy` (giữ file `.pub` và dòng trong `authorized_keys`).

### Bước 4 — Mở firewall cho GitHub

GitHub chạy deploy từ nhiều IP khác nhau, nên cổng SSH phải mở cho mọi IP.
Nếu trước đây bạn đã SSH được từ nhà bằng `ssh root@IP` thì thường đã mở rồi. Kiểm tra:
```
sudo ufw status | grep -E "22|OpenSSH"
```
Thấy `22/tcp ALLOW Anywhere` hoặc `OpenSSH ALLOW Anywhere` là được. Nếu chỉ cho phép IP nhà bạn:
```
sudo ufw allow OpenSSH
```
Đăng nhập bằng key vẫn an toàn; fail2ban vẫn chặn kẻ dò mật khẩu.
Nhà cung cấp VPS có firewall riêng trên web thì cũng phải mở cổng 22 ở đó.

### Bước 5 — Chạy thử

1. Trên GitHub (app hoặc web): tab **Actions** → **Deploy VPS** → **Run workflow** → **Run workflow**.
2. Đợi khoảng 1 phút, thấy dấu ✓ xanh là xong. Bấm vào để xem log, dòng cuối là `>>> Deploy xong: ...`.

Từ giờ, cứ merge PR là bot tự cập nhật. GitHub gửi email/thông báo cho bạn nếu deploy thất bại.

---

## Deploy báo lỗi (dấu ✗ đỏ)

Bấm vào lần chạy đó, mở bước **Deploy** để xem dòng `!!!`:

| Thông báo | Ý nghĩa và cách xử lý |
|---|---|
| `Thiếu secret: ...` | Chưa thêm đủ secrets ở bước 3. |
| `Không kết nối được cổng SSH` / `Connection timed out` | Sai `VPS_HOST`, hoặc firewall chặn (bước 4). |
| `Permission denied (publickey)` | `VPS_SSH_KEY` copy thiếu dòng, hoặc chưa thêm `.pub` vào `authorized_keys`. |
| `Host key verification failed` | `VPS_HOST_KEY` sai, hoặc đã đổi VPS: cập nhật lại secret này. |
| `VPS có file trong git bị sửa tay` | Bot **vẫn chạy code cũ**. Vào VPS làm như bước 1, rồi bấm Run workflow lại. |
| `Không fast-forward được` | Lịch sử git trên VPS lệch với GitHub. Bot vẫn chạy code cũ; cần xem tay trên VPS. |
| `Code mới lỗi cú pháp` / `Bot không chạy sau khi restart` / `Bot bị crash` | Đã **tự quay về code cũ**. Xem log phía trên dòng lỗi rồi sửa code trong PR mới. |

Bản sao lưu nằm ở `~/deploy_backups/`. Cần khôi phục trạng thái:
```
sudo systemctl stop bot-live
cp ~/deploy_backups/<ngày_giờ>/paper_state.json ~/Bot_VPS_Realtime_ver1_11_3_26/
sudo systemctl start bot-live
```

## Khi chuyển sang VPS mới

Trên VPS mới làm lại bước 2 và bước 4, rồi sửa `VPS_HOST`, `VPS_SSH_KEY`, `VPS_HOST_KEY` trên GitHub.
Nhớ tắt bot trên VPS cũ trước để không chạy hai bot cùng lúc.

## Tạm tắt tự động deploy

GitHub → tab **Actions** → **Deploy VPS** → nút **⋯** → **Disable workflow**. Bật lại bằng **Enable workflow**.
