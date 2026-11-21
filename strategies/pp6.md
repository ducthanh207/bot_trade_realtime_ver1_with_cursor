---
disk: 1
id: "6"
name: PP6 — PP4 + CVD
description: PP4 + CVD: CVD 4H phải cùng chiều lệnh, CVD 1H đi ngược 2 giờ liền thì siết trailing về 1.5 ATR.
base: pp4
blocks:
  cvd: true
---
# PP6 = PP4 + CVD

Chi tiết và lý do: `docs/PP6_CVD.md`. Giữ toàn bộ PP4, thêm 2 lớp CVD (dòng tiền mua/bán chủ động).

**CVD lấy từ nến Binance:** `delta = 2 × taker_buy − volume`; độ dốc N nến = tổng delta / tổng volume (−1 đến +1).
Chỉ dùng nến đã đóng.

| Lớp | Quy tắc | Tham số (.env) |
|---|---|---|
| 1. Vào lệnh | LONG chỉ khi độ dốc CVD 6 nến 4H > 0, SHORT khi < 0 | `M6_4H_BARS=6`, `M6_4H_MIN_RATIO=0` |
| 1b. Tuỳ chọn | thêm điều kiện CVD 8 nến 1H cùng chiều | `M6_1H_ENTRY_CONFIRM=false` |
| 2. Đang giữ lệnh | CVD 1H ngược lệnh 2 nến liền (đã giữ ≥ 2h) → siết trailing về 1.5 ATR 1H | `M6_EXIT_MODE=tighten`, `M6_1H_BARS=8`, `M6_EXIT_CONFIRM_BARS=2`, `M6_EXIT_MIN_HOURS=2`, `M6_TIGHT_ATR_MULT=1.5` |

`M6_EXIT_MODE=close` thì đóng lệnh ngay (lý do `CVD_EXIT`), `off` tắt lớp 2.

**Dữ liệu:** cần cột taker buy của nến 1H/4H. Backtest tự tải và lưu vào `backtest/data_cache/<COIN>/1h_taker.csv.gz`;
paper lấy thẳng từ nến Binance.

**Muốn thử biến thể:** copy file này, đổi `id` (vd `pp6-close`), đổi `name`, thêm
```
params:
  M6_EXIT_MODE: close
```
rồi nạp ở trang Chiến lược.
