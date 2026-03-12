#!/bin/bash
# Trên VPS: git pull và restart service bot
# Cách dùng: ./scripts/deploy.sh   hoặc  bash scripts/deploy.sh

set -e
cd "$(dirname "$0")/.."
echo ">>> Pulling latest code..."
git pull
echo ">>> Restarting bot service..."
sudo systemctl restart bot-live
echo ">>> Done. Check: sudo systemctl status bot-live"
