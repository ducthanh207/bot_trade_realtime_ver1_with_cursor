#!/bin/bash
# Cập nhật IP hiện tại lên DuckDNS
# Trong .env hoặc biến môi trường: DUCKDNS_TOKEN=xxx, DUCKDNS_DOMAIN=mybot.duckdns.org

DOMAIN="${DUCKDNS_DOMAIN:-}"
TOKEN="${DUCKDNS_TOKEN:-}"
if [ -z "$DOMAIN" ] || [ -z "$TOKEN" ]; then
  echo "Set DUCKDNS_DOMAIN and DUCKDNS_TOKEN"
  exit 1
fi
curl -s "https://www.duckdns.org/update?domains=$DOMAIN&token=$TOKEN&ip="
echo ""
