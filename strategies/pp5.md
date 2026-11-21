---
disk: 1
id: "5"
name: PP5 — PP4 + chu kỳ ngày
description: PP4 + lọc chu kỳ nến ngày (EMA20 1D): tăng chỉ LONG, giảm chỉ SHORT, đi ngang thì thoát nới.
base: pp4
blocks:
  daily_cycle: true
---
# PP5

Chi tiết: `docs/PP5_DAILY_CYCLE.md`.

- Chu kỳ theo giá đóng nến 1D so với EMA (`M5_DAILY_EMA_LEN`): 2 nến đóng trên EMA → TĂNG (chỉ LONG), dưới → GIẢM (chỉ SHORT).
- Đi ngang (3 nến sát EMA trong X = `M5_SIDEWAYS_ATR_K` × ATR ngày): vào theo phía nến đóng gần nhất, gói thoát nới
  (trailing `M5_WIDE_ATR_MULTIPLIER`, size × `M5_WIDE_SIZE_MULT`, chốt lời dải %change, Exit B đã sửa).
- Lệnh ngược chu kỳ: `M5_COUNTER_LONG_SIZE`, `M5_COUNTER_SHORT_SIZE` (0 = chặn).
