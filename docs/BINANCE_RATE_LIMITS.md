# Binance Public API – Gọi theo giây, real-time PnL

## Có bị chặn không?

- **Giới hạn:** Binance public REST ~**6.000 request weight / phút** (theo IP).
- **Klines** (giá, nến): mỗi request thường **1 weight**. Ví dụ: `GET /api/v3/klines?symbol=BTCUSDT&interval=1m&limit=1`.
- **Kết luận:** Gọi **1 lần/giây** (60 lần/phút) cho **một** endpoint nhẹ (klines limit=1) là **an toàn**, không bị chặn.

## Khuyến nghị

| Mục đích | Chu kỳ gợi ý | Ghi chú |
|----------|--------------|--------|
| **Cập nhật PnL / % PnL real-time** | 1–2 giây | Chỉ gọi `/api/price` hoặc klines 1m limit=1; đủ cho PnL, % PnL theo thời gian thực. |
| **Cập nhật full (klines + indicators)** | 5–10 giây | Nhiều nến + tính RSI/ATR tốn tài nguyên hơn; 5s như hiện tại là hợp lý. |
| **Nhiều symbol / nhiều tab** | Giảm tần suất | Cộng dồn weight; có thể 2–3s cho mỗi luồng. |

## Real-time “theo từng giây”

- **Khả thi:** Có. Có thể giảm interval xuống **1s hoặc 2s** cho **riêng** phần lấy giá (price) và orders để PnL / % PnL cập nhật gần theo từng giây.
- **Lưu ý:** Không nên gọi **toàn bộ** klines + indicators mỗi giây (dễ lãng phí weight và CPU). Nên tách:
  - **Luồng nhanh (1–2s):** chỉ giá hiện tại → tính PnL, % PnL.
  - **Luồng chậm (5s):** klines + indicators cho chart và logic chiến lược.

Nếu cần real-time hơn nữa (tick-by-tick), nên dùng **WebSocket** (stream giá) thay vì REST mỗi giây.
