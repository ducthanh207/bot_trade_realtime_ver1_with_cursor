---
disk: 1
id: "2"
name: PP2 — chốt lời %change
description: Như PP1, nhưng thoát 4H/early chỉ khi đang lãi và RSI 1H đảo chiều; thêm chốt lời ở dải %change.
base: pp2
---
# PP2

- Giữ thanh lý / ATR trailing / trần lỗ như PP1.
- Tín hiệu thoát 4H và early chỉ được dùng khi lệnh **đang lãi** và **RSI 1H đảo chiều**.
- Chốt lời `PCT_CHANGE_TP` khi giá chạm dải %change trong nến 4H đang chạy (cùng lúc RSI 1H đảo chiều).
- Số lệnh tính dải %change: `LOOKBACK_TRADES` (Paper 2 chỉnh riêng trên web).
