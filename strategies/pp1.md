---
disk: 1
id: "1"
name: PP1 — thoát cổ điển
description: Vào theo RSI/EMA/WMA 4H; thoát khi tín hiệu 4H, early RSI, ATR trailing 1H, thanh lý hoặc trần lỗ.
base: pp1
---
# PP1

Phương pháp gốc của bot (Paper 1).

- **Vào lệnh:** đầu mỗi nến 4H, theo tín hiệu RSI cắt EMA/WMA của RSI trên nến 4H vừa đóng.
- **Thoát:** tín hiệu thoát 4H, thoát sớm theo RSI (`RSI_EARLY_EXIT`), ATR trailing `ATR_MULTIPLIER` × ATR 1H,
  thanh lý, trần lỗ `MAX_STOP_CAPITAL_PCT`.
- **Tham số:** lấy theo `.env`.
