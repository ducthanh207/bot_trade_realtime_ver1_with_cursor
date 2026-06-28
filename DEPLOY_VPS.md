# Hướng dẫn deploy bot lên VPS

Từ bước cài Python trên VPS → push code lên GitHub → clone và chạy bot trên VPS.

---

## Bước 1: Trên máy local – Đẩy code lên GitHub

1. Mở terminal tại thư mục project: `D:\Bot_VPS_Realtime_ver1_11_3_26`
2. Nếu chưa có git:
   ```bash
   git init
   git add .
   git commit -m "Initial: bot paper trade + telegram + web"
   ```
3. Tạo repo trên GitHub (New repository), **không** tick "Add README".
4. Thêm remote và push:
   ```bash
   git remote add origin https://github.com/<USERNAME>/<REPO>.git
   git branch -M main
   git push -u origin main
   ```
   (Thay `<USERNAME>` và `<REPO>` bằng tên user GitHub và tên repo của bạn.)

**Lưu ý:** File `.env` đã nằm trong `.gitignore` nên sẽ không bị đẩy lên (đúng, vì chứa key). Trên VPS bạn sẽ tạo file `.env` riêng từ `.env.example`.

---

## Bước 2: Trên VPS – Cài Python và công cụ

SSH vào VPS: `ssh root@103.179.188.159`

### 2.1 Cập nhật và cài Python3 + pip + venv (Ubuntu 24.04)

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git
```

Kiểm tra:

```bash
python3 --version
pip3 --version
```

### 2.2 (Tùy chọn) Cài thêm nếu thiếu build tool

```bash
apt install -y python3-dev build-essential
```

---

## Bước 3: Trên VPS – Clone repo và cài dependencies

### 3.1 Clone repo

Thay URL bằng repo GitHub thật của bạn:

```bash
cd ~
git clone https://github.com/<USERNAME>/<REPO>.git Bot_VPS_Realtime_ver1_11_3_26
cd Bot_VPS_Realtime_ver1_11_3_26
```

### 3.2 Tạo virtualenv và cài package

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.3 Tạo file .env

```bash
cp .env.example .env
nano .env
```

Điền đúng:

- `TELEGRAM_BOT_TOKEN` – token từ BotFather  
- `TELEGRAM_CHAT_ID` – ID Telegram của bạn  
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` – để trống nếu chỉ chạy paper trade (chỉ lấy giá).

Lưu: `Ctrl+O`, Enter, thoát: `Ctrl+X`.

---

## Bước 4: Trên VPS – Chạy bot

### 4.1 Chạy thử bằng tay (để kiểm tra)

```bash
cd ~/Bot_VPS_Realtime_ver1_11_3_26
source .venv/bin/activate
python run_live.py
```

Nếu chạy ổn (Flask + Telegram), dừng bằng `Ctrl+C` rồi chuyển sang chạy nền hoặc systemd.

### 4.2 Chạy nền bằng nohup (đơn giản, tắt SSH vẫn chạy)

```bash
cd ~/Bot_VPS_Realtime_ver1_11_3_26
nohup .venv/bin/python run_live.py > bot.log 2>&1 &
```

Xem log: `tail -f ~/Bot_VPS_Realtime_ver1_11_3_26/bot.log`  
**Lưu ý:** VPS reboot thì bot không tự chạy lại. Dùng systemd (bước 4.3) để chắc chắn chạy 24/7.

### 4.3 (Khuyến nghị) Chạy bằng systemd – bot luôn chạy, tự khởi động khi VPS reboot

Trong repo đã có sẵn file `scripts/bot-live.service` và script `scripts/setup-systemd.sh`. Trên VPS chạy **một lần**:

```bash
cd ~/Bot_VPS_Realtime_ver1_11_3_26
bash scripts/setup-systemd.sh
```

Script sẽ: copy service vào `/etc/systemd/system/`, bật tự chạy khi khởi động, và start bot ngay.

**Nếu bạn clone repo vào thư mục khác** (không phải `~/Bot_VPS_Realtime_ver1_11_3_26`), script sẽ tự sửa đường dẫn trong file service.

**Kiểm tra bot đang chạy:**

```bash
sudo systemctl status bot-live
```

**Các lệnh thường dùng:**

| Lệnh | Mô tả |
|------|--------|
| `sudo systemctl status bot-live` | Xem trạng thái |
| `journalctl -u bot-live -f` | Xem log realtime |
| `sudo systemctl restart bot-live` | Khởi động lại (sau khi git pull) |
| `sudo systemctl stop bot-live` | Dừng bot |
| `sudo systemctl start bot-live` | Chạy lại |

---

## Tóm tắt thứ tự

| Bước | Nơi    | Việc |
|------|--------|------|
| 1    | Local  | Push code lên GitHub |
| 2    | VPS    | Cài Python3, pip, venv, git |
| 3    | VPS    | Clone repo → venv → pip install -r requirements.txt → tạo .env |
| 4    | VPS    | Chạy thử `python run_live.py` → rồi **`bash scripts/setup-systemd.sh`** để bot chạy 24/7 |

**Đảm bảo bot chạy trên VPS:** dùng systemd (chạy một lần `bash scripts/setup-systemd.sh`). Bot sẽ tự chạy khi VPS bật và tự restart nếu bị lỗi. Kiểm tra: `sudo systemctl status bot-live`; xem log: `journalctl -u bot-live -f`.

Sau khi sửa code: trên local commit → push; trên VPS: `cd ~/Bot_VPS_Realtime_ver1_11_3_26 && git pull && sudo systemctl restart bot-live` (hoặc dùng `bash scripts/deploy.sh`).
