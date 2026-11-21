---
disk: 1
id: "3"
name: PP3 — Exit B + circuit breaker
description: Exit B (RSI vượt ngưỡng + slope), lọc EMA50 khi ADX>30, size theo vùng ADX/swing/chuỗi thua, circuit breaker.
base: pp3
---
# PP3

- **Vào lệnh:** như PP1, thêm vùng ADX (`M3_ADX_LOW/HIGH`), lọc EMA50 khi ADX > `M3_EMA_TREND_ADX_ABOVE`,
  giảm size khi swing ngược (`M3_SWING_DISAGREE_SIZE`) và theo chuỗi thua (`M3_SIZING_STEP`, `M3_SIZING_FLOOR`).
- **Circuit breaker:** 4 lệnh thua → nghỉ 8h; 7 lệnh thua hoặc sụt > `M3_CB_HEAVY_DD_PCT` → nghỉ 48h.
- **Thoát:** Exit B (tầng mạnh), ATR trailing grace `M3_ATR_MULTIPLIER_GRACE`.
