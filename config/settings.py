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

# ---------- Method 4 (nâng cấp PP3: entry/exit/stop) ----------
# ATR trailing: grace rộng lúc mở lệnh, tự siết lại sau M4_ATR_GRACE_HOURS (khác PP3: PP3 giữ nguyên hệ số lúc mở)
M4_ATR_MULTIPLIER = float(os.environ.get("M4_ATR_MULTIPLIER", "2.2"))
M4_ATR_MULTIPLIER_GRACE = float(os.environ.get("M4_ATR_MULTIPLIER_GRACE", "2.5"))
M4_ATR_GRACE_HOURS = float(os.environ.get("M4_ATR_GRACE_HOURS", "12.0"))
# Hard stop: lỗ tối đa mỗi lệnh tính trên vốn (thay MAX_STOP_CAPITAL_PCT=0.30 của PP1-3)
M4_MAX_STOP_CAPITAL_PCT = float(os.environ.get("M4_MAX_STOP_CAPITAL_PCT", "0.10"))
# Entry filter: chặn SHORT khi RSI nến tín hiệu < floor (đã quá bán), chặn LONG khi RSI > ceil (đã quá mua)
M4_RSI_SHORT_FLOOR = float(os.environ.get("M4_RSI_SHORT_FLOOR", "38.0"))
M4_RSI_LONG_CEIL = float(os.environ.get("M4_RSI_LONG_CEIL", "62.0"))
# Entry filter: cần RSI 1H (2 nến đã đóng) cùng hướng lệnh — SHORT cần RSI 1H đang giảm, LONG cần đang tăng
M4_REQUIRE_1H_CONFIRM = os.environ.get("M4_REQUIRE_1H_CONFIRM", "true").lower() in ("1", "true", "yes")
# ADX exhaustion: ADX quá cao thường là cuối trend → giảm size
M4_ADX_EXHAUSTION = float(os.environ.get("M4_ADX_EXHAUSTION", "45.0"))
M4_ADX_EXHAUSTION_SIZE = float(os.environ.get("M4_ADX_EXHAUSTION_SIZE", "0.5"))
# Exit B confirm bars (giống PP3)
M4_EARLY_EXIT_B_CONFIRM_BARS = int(os.environ.get("M4_EARLY_EXIT_B_CONFIRM_BARS", "2"))

# ---------- [2026-11-01] Method 4: nhận diện giai đoạn thị trường + cắt lỗ sớm ----------
# Tất cả MẶC ĐỊNH TẮT → bot đang chạy không đổi hành vi cho tới khi bật trong .env.
# Giải thích chi tiết: docs/PP4_REGIME_EARLY_CUT.md
def _env_bool(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


# Bộ phân loại giai đoạn (ER Kaufman + độ dốc EMA50) trên N nến 4H đã đóng: UP / DOWN / RANGE
M4_REGIME_ENABLED = _env_bool("M4_REGIME_ENABLED")
M4_REGIME_LOOKBACK = int(os.environ.get("M4_REGIME_LOOKBACK", "20"))           # N nến 4H
M4_REGIME_ER_TREND = float(os.environ.get("M4_REGIME_ER_TREND", "0.2"))        # ER >= ngưỡng → có trend
M4_REGIME_SLOPE_ATR = float(os.environ.get("M4_REGIME_SLOPE_ATR", "1.0"))      # |EMA50 dốc| trong N nến, tính theo số lần ATR 4H
# Lệnh "chặt" = vào khi đi ngang hoặc ngược trend → trailing dùng hệ số này thay vì 2.5→2.2
M4_TIGHT_ATR_MULTIPLIER = float(os.environ.get("M4_TIGHT_ATR_MULTIPLIER", "1.5"))
M4_RANGE_SKIP_ENTRY = _env_bool("M4_RANGE_SKIP_ENTRY")            # (E) bỏ hẳn lệnh khi RANGE
M4_COUNTER_TREND_BLOCK = _env_bool("M4_COUNTER_TREND_BLOCK")      # chặn LONG khi DOWN / SHORT khi UP
# (A) Thoát khi tín hiệu thất bại: nến 1H đóng vượt đáy (LONG) / đỉnh (SHORT) nến 4H tín hiệu ± buffer×ATR
M4_INVALIDATION_EXIT = _env_bool("M4_INVALIDATION_EXIT")
M4_INVALIDATION_HOURS = float(os.environ.get("M4_INVALIDATION_HOURS", "12.0"))
M4_INVALIDATION_BUFFER_ATR = float(os.environ.get("M4_INVALIDATION_BUFFER_ATR", "0.3"))
# (B) Dừng theo thời gian: tới mốc 4H sau ít nhất N giờ mà lệnh vẫn lỗ → đóng
M4_TIME_STOP = _env_bool("M4_TIME_STOP")
M4_TIME_STOP_HOURS = float(os.environ.get("M4_TIME_STOP_HOURS", "4.0"))
# A và B chỉ áp cho lệnh "chặt" (RANGE / ngược trend). false → áp cho mọi lệnh PP4
M4_EARLY_CUT_ONLY_TIGHT = _env_bool("M4_EARLY_CUT_ONLY_TIGHT", "true")
# (D) Grace mượt: hệ số ATR giảm dần tuyến tính 2.5→2.2 trong M4_ATR_GRACE_HOURS thay vì tụt một lần
M4_SMOOTH_GRACE = _env_bool("M4_SMOOTH_GRACE")

# ---------- [2026-11-07] Method 5 = PP4 + lọc chu kỳ nến ngày (1D) ----------
# PP5 chạy ở Paper trade 5 (/paper5), bot trade thật /live (chọn PP5) và backtest (--methods 5). PP1–PP4 không đổi.
# Giải thích: docs/PP5_DAILY_CYCLE.md, code: strategy/daily_cycle.py
M5_DAILY_EMA_LEN = int(os.environ.get("M5_DAILY_EMA_LEN", "20"))          # EMA nến ngày (giống tab Biểu đồ)
M5_DAILY_KLINES = int(os.environ.get("M5_DAILY_KLINES", "1000"))          # số nến ngày đã đóng dùng để tính
M5_CONFIRM_BARS = int(os.environ.get("M5_CONFIRM_BARS", "2"))             # số nến đóng liên tiếp trên/dưới EMA để vào/kết thúc chu kỳ
M5_SPIKE_ENABLED = _env_bool("M5_SPIKE_ENABLED", "true")                  # đột biến: dải %change cắt qua EMA → vào chu kỳ ngay
M5_PCT_LOOKBACK_TRADES = int(os.environ.get("M5_PCT_LOOKBACK_TRADES", "15"))  # lookback %change trên nến ngày
# Đi ngang: N nến gần nhất đều có |close − EMA| / EMA <= X
M5_SIDEWAYS_BARS = int(os.environ.get("M5_SIDEWAYS_BARS", "3"))
M5_SIDEWAYS_MODE = os.environ.get("M5_SIDEWAYS_MODE", "atr").strip().lower()  # atr: X = k × ATR14(1D)/close | pct: X cố định
M5_SIDEWAYS_ATR_K = float(os.environ.get("M5_SIDEWAYS_ATR_K", "1.0"))
M5_SIDEWAYS_PCT = float(os.environ.get("M5_SIDEWAYS_PCT", "3.0"))         # % (khi MODE=pct)
# Đi ngang mà nến nằm lẫn hai phía EMA: latest = theo giá đóng nến gần nhất | both = vào cả hai phía | skip = bỏ lệnh
M5_SIDEWAYS_MIXED = os.environ.get("M5_SIDEWAYS_MIXED", "latest").strip().lower()
# Gói "thoát nới" cho lệnh vào lúc đi ngang
M5_WIDE_ATR_MULTIPLIER = float(os.environ.get("M5_WIDE_ATR_MULTIPLIER", "3.5"))  # trailing cố định, không siết sau 12h
M5_WIDE_SIZE_MULT = float(os.environ.get("M5_WIDE_SIZE_MULT", "0.6"))            # giảm size → hard stop % vốn tự giãn ra
M5_WIDE_PCT_TP = _env_bool("M5_WIDE_PCT_TP", "true")                             # chốt lời ở dải %change 4H (như PP2)
# Exit B đã sửa (dùng RSI nến 4H đã đóng): wide = chỉ lệnh đi ngang | all = mọi lệnh PP5 | off = như PP4 (không chạy)
M5_EXIT_B = os.environ.get("M5_EXIT_B", "wide").strip().lower()
# [2026-11-08] Lệnh ngược chu kỳ: thay vì chặn hẳn thì cho vào với size × hệ số này. 0 = chặn (như cũ).
# LONG khi chu kỳ GIẢM / đi ngang thiên SHORT; SHORT khi chu kỳ TĂNG / đi ngang thiên LONG.
# Ví dụ M5_COUNTER_LONG_SIZE=1.0 → chỉ còn chặn SHORT khi chu kỳ tăng; 0.5 → LONG đánh hồi với nửa size.
M5_COUNTER_LONG_SIZE = float(os.environ.get("M5_COUNTER_LONG_SIZE", "0"))
M5_COUNTER_SHORT_SIZE = float(os.environ.get("M5_COUNTER_SHORT_SIZE", "0"))
