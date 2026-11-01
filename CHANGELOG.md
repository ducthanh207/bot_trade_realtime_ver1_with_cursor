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
