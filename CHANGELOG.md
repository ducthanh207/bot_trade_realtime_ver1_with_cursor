# Nhật ký cập nhật

## 2026-11-01 — PP4: nhận diện giai đoạn thị trường + cắt lỗ sớm

Mọi tùy chọn đều mặc định TẮT, nên bot đang chạy không đổi hành vi. Chi tiết và lệnh backtest: `docs/PP4_REGIME_EARLY_CUT.md`.

- Thêm bộ phân loại giai đoạn UP / DOWN / RANGE (ER Kaufman + độ dốc EMA50 trên 20 nến 4H) — `M4_REGIME_ENABLED`.
  Lệnh vào lúc đi ngang hoặc ngược trend dùng stop chặt 1.5×ATR thay cho 2.5→2.2.
- (A) Thoát khi tín hiệu thất bại: nến 1H đóng phá đáy/đỉnh nến 4H tín hiệu — `M4_INVALIDATION_EXIT`.
- (B) Dừng theo thời gian: sau 4h vẫn lỗ thì đóng ở mốc 4H — `M4_TIME_STOP`.
- (D) Grace ATR mượt: giảm dần 2.5→2.2 trong 12h — `M4_SMOOTH_GRACE`.
- (E) Bỏ lệnh khi RANGE — `M4_RANGE_SKIP_ENTRY`; chặn lệnh ngược trend — `M4_COUNTER_TREND_BLOCK`.
- Backtest `backtest/live_replay.py` mô phỏng đầy đủ các tùy chọn trên; bật bằng `--set`.
- File mới: `strategy/regime.py`, `tests/test_m4_regime.py`, `docs/PP4_REGIME_EARLY_CUT.md`.

## 2026-11-01 — Sửa lỗi nút "Chạy backtest" trên web (PP3/PP4)

- `web/app.py`: `/api/paper3/backtest` và `/api/paper4/backtest` dùng `state` nhưng chưa import → lỗi
  `name 'state' is not defined`. Thêm `import bot.state as state` trong hai hàm. Lỗi có từ trước, không do bản cập nhật PP4.

## 2026-11-01 — Nút "Chạy backtest" trên web không còn ghi đè paper trade thật

- Trước đây nút Chạy backtest ở trang Paper 3/Paper 4 luôn gửi `load_to_state: true`: xoá lịch sử, lệnh đang mở và vốn
  của paper thật, rồi thay bằng kết quả backtest.
- Giờ mặc định chỉ hiện kết quả. Server chỉ ghi đè khi request gửi cả `load_to_state: true` và `confirm_overwrite: true`.

## 2026-11-01 — Backtest trên web chạy giống bot live, cho cả PP1–PP4

- Nút "Chạy backtest" (Paper 1, 2, 3, 4) giờ dùng chung engine với `backtest/live_replay.py`
  (`backtest/web_backtest.py`): phát lại từng phút đúng hàm chiến lược của bot, cùng tham số `.env`, chỉ dùng nến đã đóng.
  Trước đây web dùng `bot/paper3_backtest.py` (chỉ PP3/PP4): quét stop trên nến 1H, đọc cả nến chưa đóng
  (nhìn trước tương lai) và tải cả nến đang chạy → cùng khoảng ngày chạy ở hai lúc khác nhau ra kết quả khác nhau.
- Chạy nền trong process Python riêng (không làm chậm bot), web hỏi kết quả mỗi 2 giây; hiện bảng lệnh, lý do thoát, DD max.
- Dữ liệu 1m cache theo tháng trong `backtest/data_cache/` → lần chạy sau nhanh hơn, cùng khoảng ngày luôn cùng kết quả.
- Khung backtest dùng chung: `web/templates/_backtest_panel.html`. Không ghi gì vào paper trade thật.
