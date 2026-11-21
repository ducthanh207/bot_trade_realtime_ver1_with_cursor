---
disk: 1
id: "7"
name: PP7 — rủi ro 2% + trend + stop 4H
description: PP4 + size theo rủi ro (mỗi lệnh chạm stop mất cố định % vốn) + lọc trend EMA50 luôn bật + stop/trailing theo ATR 4H.
base: pp4
blocks:
  trend_filter_always: true
  stop_atr_4h: true
  risk_sizing: true
---
# PP7 = PP4 + 3 sửa đổi chống sụt vốn

Chi tiết và bằng chứng: `docs/PP7_RISK_TREND_4H.md`.

| Vấn đề của PP4 | Khối của PP7 |
|---|---|
| Lệnh to gấp 6 lần vốn nên tiền lỗ phụ thuộc ATR (có lệnh mất 7–10% vốn) | `risk_sizing`: chạm stop ban đầu chỉ mất `M7_RISK_PCT` vốn (2%) |
| Stop 2.5 × ATR **1H** trong khi tín hiệu là khung **4H** → bị quét sớm | `stop_atr_4h`: stop và trailing = `M7_ATR4H_MULT` (1.5) × ATR 4H, không siết sau 12h |
| Lọc EMA50 chỉ khi ADX > 30 → vẫn LONG lúc giá giảm mạnh | `trend_filter_always`: LONG chỉ khi giá đóng 4H trên EMA50, SHORT khi dưới |

Còn lại như PP4: tín hiệu 4H, chặn RSI cực trị, xác nhận RSI 1H, vùng ADX, swing, chuỗi thua, circuit breaker, `4H_EXIT`.
Notional không vượt mức PP4. Hard stop an toàn `M7_MAX_STOP_CAPITAL_PCT` (5%).

| Tham số (.env) | Mặc định | Ý nghĩa |
|---|---|---|
| M7_RISK_PCT | 0.02 | % vốn mất khi chạm stop ban đầu |
| M7_ATR4H_MULT | 1.5 | hệ số ATR 4H cho stop + trailing |
| M7_TREND_FILTER | true | bật lọc trend EMA50 |
| M7_TREND_SLOPE_BARS | 0 | > 0: EMA50 phải dốc cùng hướng so với N nến 4H trước |
| M7_MAX_STOP_CAPITAL_PCT | 0.05 | hard stop an toàn |
| M7_EXIT_B | off | `fixed` = dùng Exit B đã sửa |

**Muốn thử biến thể** (vd rủi ro 1%): copy file, đổi `id: pp7-risk1`, `name`, thêm
```
params:
  M7_RISK_PCT: 0.01
```
rồi nạp ở trang Chiến lược.
