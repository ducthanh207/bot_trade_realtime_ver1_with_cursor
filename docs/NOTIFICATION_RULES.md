# Quy tắc thông báo Telegram

Mọi thay đổi trạng thái lệnh và sự cố đều gửi tin nhắn Telegram (dùng chung cho paper và sau này ví Binance thật).

## Khi nào gửi

| Sự kiện | Hàm | Nguồn gọi |
|--------|-----|-----------|
| **Mở lệnh** | `notify_trade_opened(open_trade, source)` | paper_loop, Telegram, (sau này) web/live |
| **Đóng lệnh** | `notify_trade_closed(closed, source)` | paper_loop, web (Chốt lệnh), Telegram |
| **Lỗi app/loop** | `notify_error(message, context="app")` | paper_loop exception |
| **Lỗi Binance / API** | `notify_error(message, context="binance")` | warm-up không kết nối, (sau này) API bị chặn |
| **Lỗi server** | `notify_error(message, context="server")` | (sau này) health check, mất kết nối |

## Nội dung đóng lệnh (thống nhất)

- Nguồn: Web / Telegram / Tự động (Loop)
- Side, trạng thái đã đóng
- PnL (USDT), % vốn, vốn sau
- Thời điểm và giá vào/ra, lý do đóng

## Module

- `telegram.notifier`: `send_message`, `notify_trade_opened`, `notify_trade_closed`, `notify_error`, `get_status_update_text`, `send_status_15m`
