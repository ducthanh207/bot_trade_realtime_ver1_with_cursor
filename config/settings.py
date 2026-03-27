# -*- coding: utf-8 -*-
"""Đọc cấu hình từ .env và biến môi trường."""

import os
from datetime import timezone, timedelta
from pathlib import Path

# Múi giờ hiển thị / lưu: GMT+7 (Việt Nam)
GMT7 = timezone(timedelta(hours=7))
TZ_NAME = "Asia/Bangkok"

# Load .env nếu có (python-dotenv)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass

# ---------- Binance ----------
BINANCE_API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
BINANCE_API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()
BINANCE_TESTNET = os.environ.get("BINANCE_TESTNET", "false").lower() in ("1", "true", "yes")

# ---------- Telegram ----------
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

# ---------- Chế độ ----------
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() in ("1", "true", "yes")
# Không cần API key để lấy giá (dùng API công khai). API key chỉ cần khi bật trade thật.

# ---------- Trading ----------
SYMBOL = os.environ.get("SYMBOL", "BTCUSDT")
CAPITAL_START = float(os.environ.get("CAPITAL_START", "50.0"))
LEVERAGE = float(os.environ.get("LEVERAGE", "20.0"))
WALLET_PCT = float(os.environ.get("WALLET_PCT", "0.30"))

MAKER_FEE = float(os.environ.get("MAKER_FEE", "0.0002"))
TAKER_FEE = float(os.environ.get("TAKER_FEE", "0.0004"))
MAINT_MARGIN_RATE = float(os.environ.get("MAINT_MARGIN_RATE", "0.005"))

# Risk
MAX_STOP_CAPITAL_PCT = float(os.environ.get("MAX_STOP_CAPITAL_PCT", "0.30"))
ATR_MULTIPLIER = float(os.environ.get("ATR_MULTIPLIER", "1.5"))

# Early exit RSI
RSI_EARLY_EXIT = os.environ.get("RSI_EARLY_EXIT", "true").lower() in ("1", "true", "yes")
RSI_LONG_CUT = float(os.environ.get("RSI_LONG_CUT", "42"))
RSI_SHORT_CUT = float(os.environ.get("RSI_SHORT_CUT", "58"))

# Phương pháp: "1" = chiến lược cũ; "2" = thêm TP %change + lọc thoát 4H/early khi lãi + đảo chiều RSI 1H
TRADING_METHOD = (os.environ.get("TRADING_METHOD") or "1").strip()
LOOKBACK_TRADES = int(os.environ.get("LOOKBACK_TRADES", "15"))

# ---------- Loop ----------
LOOP_INTERVAL_SEC = float(os.environ.get("LOOP_INTERVAL_SEC", "5"))
STATUS_INTERVAL_MIN = int(os.environ.get("STATUS_INTERVAL_MIN", "15"))
STATUS_HOURLY_INTERVAL_MIN = int(os.environ.get("STATUS_HOURLY_INTERVAL_MIN", "60"))

# ---------- Web ----------
WEB_HOST = os.environ.get("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("WEB_PORT", "5000"))
