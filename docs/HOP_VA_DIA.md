# Hộp và đĩa chiến lược

*(2026-11-21)*

## Ý tưởng

- **Hộp** là phần code chạy trên VPS: lấy nến Binance, tính chỉ báo, mô phỏng/đặt lệnh, trailing stop,
  Telegram, web. Hộp chứa sẵn các **khối** (khung PP1–PP4 và các khối bổ sung).
- **Đĩa** là một file `.md` mô tả chiến lược: dùng khung nào, bật khối nào, tham số bao nhiêu.
  Đĩa **không chứa code**. Hộp đọc đĩa, kiểm tra theo bảng tham số cho phép, rồi chạy bằng các khối có sẵn.

Vì vậy một chiến lược mới chỉ cần ghép khối + đổi tham số thì **chỉ cần nạp đĩa** (không phải sửa code,
không cần deploy). Nếu cần một khối mới (một kiểu lọc/thoát chưa có), phải thêm code qua PR rồi merge.

PP1–PP7 bây giờ đều là đĩa (thư mục `strategies/` trong repo). Kết quả backtest và paper của PP1–PP7 giống hệt
code cũ (đã so sánh từng lệnh; xem `tests/test_disks.py`). Riêng paper "7": trước đây bị rơi về PP1, nay chạy đúng PP7.

## Cấu trúc một đĩa

```
---
disk: 1
id: pp7-risk1
name: PP7 — rủi ro 1%
short: PP7r1
description: PP7 nhưng mỗi lệnh chỉ mất tối đa 1% vốn
base: pp4
blocks: [trend_filter_always, stop_atr_4h, risk_sizing]
params:
  M7_RISK_PCT: 0.01
author: Aster
created: 2026-11-21
---

# Giải thích (markdown tự do, chỉ để đọc)
```

| Khoá | Ý nghĩa |
|---|---|
| `disk` | Phiên bản định dạng, luôn là `1` |
| `id` | Mã đĩa. Đĩa nạp lên phải bắt đầu bằng chữ cái (vd `pp7-risk1`); `1`..`7`, `6.1` là đĩa có sẵn |
| `base` | Khung: `pp1`, `pp2`, `pp3`, `pp4` |
| `blocks` | Khối bổ sung (chỉ dùng được khi `base: pp4`) |
| `params` | Ghi đè tham số. Tên giống trong `.env` (`M3_…`..`M7_…`, `M61_…`, `ATR_MULTIPLIER`, `MAX_STOP_CAPITAL_PCT`, `RSI_EARLY_EXIT`, `RSI_LONG_CUT`, `RSI_SHORT_CUT`). Không ghi thì dùng giá trị trong `.env` |

### Các khối

| Khối | Dùng trong | Tác dụng |
|---|---|---|
| `regime_cut` | PP4 | Nhận diện giai đoạn (ER + EMA50), các kiểu cắt lỗ sớm A/B/D/E |
| `daily_cycle` | PP5 | Lọc chu kỳ ngày (EMA20 1D), đi ngang thì nới thoát + giảm size |
| `cvd` | PP6, PP6.1 | Lọc/thoát theo CVD 4H (và 1H) |
| `trend_filter_always` | PP7 | Lọc trend EMA50 luôn bật |
| `stop_atr_4h` | PP7 | Stop/trailing = `M7_ATR4H_MULT` × ATR 4H |
| `risk_sizing` | PP7 | Size theo % rủi ro vốn (bắt buộc đi cùng `stop_atr_4h`) |

Danh sách tham số đầy đủ và khoảng cho phép: trang **Chiến lược → Bảng tham số**, hoặc `GET /api/disks/schema`.

## An toàn

- Đĩa bị từ chối nếu: có HTML/`<script>`, có khối code (python/js/sh…), khoá lạ, khối lạ, tham số ngoài khoảng,
  hoặc file > 64 KB. Phần markdown chỉ hiển thị dạng chữ (đã escape).
- Nạp/xoá đĩa và bật paper cần đăng nhập mật khẩu admin (`LIVE_ADMIN_PASSWORD`, cùng mật khẩu trang /live).
- Đĩa nạp lên **chỉ chạy paper và backtest**. Trade thật vẫn chỉ PP1–PP5 và chỉ bật thủ công ở trang /live.
- Đĩa có sẵn (PP1–PP7) không sửa/xoá được trên web; thành phần của chúng được khoá trong code.
- Đĩa nạp lên được lưu ở `data/strategies/<id>.md` trên VPS (không vào git).

## Trang web mới

- **Chiến lược** (`/strategies`): xem các đĩa, đọc/tải file `.md`, nạp đĩa mới (có nút "Kiểm tra" trước khi lưu),
  bật/tạm dừng/dừng/reset paper cho đĩa (đĩa 1–5 vẫn dùng trang Paper riêng như cũ).
  Paper của đĩa mặc định **dừng**, trạng thái lưu ở `data/disk_paper.json`, Telegram gắn nhãn `[ĐĨA <tên>]`.
- **Backtest** (`/backtest`): chọn đĩa, nhiều cặp tiền (tối đa 10, mỗi cặp một job), khoảng thời gian,
  vốn/đòn bẩy, và tuỳ chọn ghi đè tham số (mỗi dòng `TÊN=giá trị`).
  - Nến 1m đã tải được lưu theo tháng ở `backtest/data_cache/`, lần sau chạy lại không tải lại.
  - Mọi kết quả được lưu (`data/backtests/`, giữ 300 lần gần nhất): xem lại ngay trên trang, tải Excel danh sách lệnh,
    kể cả sau khi khởi động lại bot.
- Thanh menu cuộn ngang trên điện thoại; các trang mới dùng thẻ, bảng cuộn ngang và khung chi tiết dạng trượt từ dưới lên.

Các trang cũ (Paper 1–5, /backtest7, /live, biểu đồ) giữ nguyên.

## Backtest bằng dòng lệnh

`--methods` nhận id của mọi đĩa (có sẵn và đã nạp):

```
python backtest/live_replay.py --methods 4 7 pp7-risk1 --symbols BTCUSDT SOLUSDT --start 2026-01-01 --end 2026-10-01
```

## Thêm chiến lược mới

1. Nếu chỉ ghép khối/đổi tham số: viết đĩa `.md` → trang Chiến lược → Nạp đĩa → backtest → paper.
2. Nếu cần khối mới: yêu cầu thêm khối (PR + đĩa `.md` mẫu), merge, rồi nạp đĩa.
