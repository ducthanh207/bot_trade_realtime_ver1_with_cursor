#!/bin/bash
# Chạy 1 lần trên VPS sau khi đã clone repo và cài .env
# Cách dùng (trong thư mục gốc project): bash scripts/setup-systemd.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="bot-live"

echo ">>> Project dir: $PROJECT_DIR"
echo ">>> Copying bot-live.service to /etc/systemd/system/ ..."
sudo cp "$SCRIPT_DIR/bot-live.service" /etc/systemd/system/

# Sửa đường dẫn trong file service nếu project không nằm ở /root/Bot_VPS_Realtime_ver1_11_3_26
if [ "$PROJECT_DIR" != "/root/Bot_VPS_Realtime_ver1_11_3_26" ]; then
  echo ">>> Project không nằm ở /root/... Đang sửa đường dẫn trong service..."
  sudo sed -i "s|/root/Bot_VPS_Realtime_ver1_11_3_26|$PROJECT_DIR|g" /etc/systemd/system/bot-live.service
fi

echo ">>> Reloading systemd..."
sudo systemctl daemon-reload
echo ">>> Enabling bot-live (tự chạy khi VPS khởi động)..."
sudo systemctl enable "$SERVICE_NAME"
echo ">>> Starting bot-live..."
sudo systemctl start "$SERVICE_NAME"
echo ""
echo ">>> Xong. Kiểm tra: sudo systemctl status $SERVICE_NAME"
echo ">>> Xem log: journalctl -u $SERVICE_NAME -f"
echo ">>> Dừng: sudo systemctl stop $SERVICE_NAME | Khởi động lại: sudo systemctl restart $SERVICE_NAME"
