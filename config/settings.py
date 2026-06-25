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

# ---------- Method 3 (Plan B 3.0) ----------
M3_ATR_MULTIPLIER = float(os.environ.get("M3_ATR_MULTIPLIER", "2.2"))
M3_ATR_MULTIPLIER_GRACE = float(os.environ.get("M3_ATR_MULTIPLIER_GRACE", "2.5"))
M3_ATR_GRACE_HOURS = float(os.environ.get("M3_ATR_GRACE_HOURS", "12.0"))
M3_EARLY_EXIT_B_CONFIRM_BARS = int(os.environ.get("M3_EARLY_EXIT_B_CONFIRM_BARS", "2"))
M3_ADX_LOW = float(os.environ.get("M3_ADX_LOW", "18.0"))
M3_ADX_HIGH = float(os.environ.get("M3_ADX_HIGH", "23.0"))
M3_ADX_MID_SIZE = float(os.environ.get("M3_ADX_MID_SIZE", "0.5"))
M3_SIZING_STEP = float(os.environ.get("M3_SIZING_STEP", "0.15"))
M3_SIZING_FLOOR = float(os.environ.get("M3_SIZING_FLOOR", "0.25"))
M3_CB_LIGHT_STREAK = int(os.environ.get("M3_CB_LIGHT_STREAK", "4"))
M3_CB_LIGHT_BARS = int(os.environ.get("M3_CB_LIGHT_BARS", "2"))
M3_CB_HEAVY_STREAK = int(os.environ.get("M3_CB_HEAVY_STREAK", "7"))
M3_CB_HEAVY_DD_PCT = float(os.environ.get("M3_CB_HEAVY_DD_PCT", "28.0"))
M3_CB_HEAVY_DD_DAYS = int(os.environ.get("M3_CB_HEAVY_DD_DAYS", "14"))
M3_CB_HEAVY_BARS = int(os.environ.get("M3_CB_HEAVY_BARS", "12"))
M3_EMA_TREND_LEN = int(os.environ.get("M3_EMA_TREND_LEN", "50"))
M3_EMA_TREND_ADX_ABOVE = float(os.environ.get("M3_EMA_TREND_ADX_ABOVE", "30.0"))
M3_SWING_LOOKBACK = int(os.environ.get("M3_SWING_LOOKBACK", "6"))
M3_SWING_DISAGREE_SIZE = float(os.environ.get("M3_SWING_DISAGREE_SIZE", "0.6"))
