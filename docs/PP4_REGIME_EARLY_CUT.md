# PP4: nhận diện giai đoạn thị trường + cắt lỗ sớm

**Ngày cập nhật:** 2026-11-01
**Trạng thái:** mọi tùy chọn đều MẶC ĐỊNH TẮT. Bot đang chạy (paper và trade thật) giữ nguyên hành vi cũ cho tới khi bạn bật trong `.env`.

## Vì sao có bản cập nhật này

Từ 17 đến 31/10/2026, PP4 trên BTCUSDT có 2 lệnh thắng và 10 lệnh thua, vốn giảm 17%. Lệnh nào thua cũng bị ATR_TRAIL cắt sau khi giá đi ngược 0.3–1.3%, tức 2.5×ATR 1H, và thường đã nằm lỗ 2–12 tiếng. Thời gian này BTC đi ngang trong vùng 79.7k–82.2k. Kiểu đánh theo đà với stop rộng của PP4 bị bào mòn trong vùng đi ngang, vì lúc vào lệnh nó không biết thị trường đang ở giai đoạn nào.

## Phần đã thêm

### 1. Bộ phân loại giai đoạn — `M4_REGIME_ENABLED`

File `strategy/regime.py`, hàm `classify_regime`. Tính trên N nến 4H đã đóng (`M4_REGIME_LOOKBACK`, mặc định 20):

- **ER (Efficiency Ratio)** = |giá đóng hiện tại − giá đóng N nến trước| / tổng |thay đổi giá từng nến|. ER gần 1 nghĩa là giá đi thẳng, gần 0 nghĩa là giá chạy loanh quanh.
- **Độ dốc EMA50** = (EMA50 hiện tại − EMA50 N nến trước) / ATR 4H.
- **UP** khi ER ≥ `M4_REGIME_ER_TREND` (0.2), EMA50 dốc lên ≥ `M4_REGIME_SLOPE_ATR` (1.0 ATR) và giá nằm trên EMA50. **DOWN** là trường hợp ngược lại. Mọi trường hợp khác là **RANGE**.

Lúc vào lệnh, nếu giai đoạn là RANGE, hoặc lệnh ngược trend (LONG khi DOWN, SHORT khi UP), lệnh được đánh dấu **"chặt"** (`m4_tight`):

- Trailing dùng hệ số cố định `M4_TIGHT_ATR_MULTIPLIER` (1.5), thay cho 2.5 → 2.2. Stop ban đầu cũng tính theo 1.5.
- Các cách cắt sớm A và B chỉ áp cho lệnh "chặt" (khi `M4_EARLY_CUT_ONLY_TIGHT=true`, là mặc định).

Lệnh cùng chiều trend giữ nguyên như PP4 gốc.

Tùy chọn đi kèm:
- `M4_RANGE_SKIP_ENTRY=true` (phương án E): bỏ hẳn lệnh khi RANGE.
- `M4_COUNTER_TREND_BLOCK=true`: chặn lệnh ngược trend.

### 2. (A) Thoát khi tín hiệu thất bại — `M4_INVALIDATION_EXIT`

Trong `M4_INVALIDATION_HOURS` (12h) đầu, nếu một nến 1H đóng dưới đáy nến 4H tín hiệu − `M4_INVALIDATION_BUFFER_ATR` (0.3) × ATR 1H thì đóng lệnh LONG. Lệnh SHORT thì xét nến 1H đóng trên đỉnh + buffer. Lý do thoát ghi là `M4_INVALIDATION`. Live xét ở mọi vòng lặp, backtest xét ở đầu mỗi giờ.

### 3. (B) Dừng theo thời gian — `M4_TIME_STOP`

Tại mốc 4H, nếu đã giữ lệnh ít nhất `M4_TIME_STOP_HOURS` (4h) mà lệnh vẫn lỗ thì đóng. Lý do thoát ghi là `M4_TIME_STOP`.

### 4. (D) Grace mượt — `M4_SMOOTH_GRACE`

Hệ số ATR giảm dần tuyến tính từ 2.5 xuống 2.2 trong 12h, thay vì tụt một lần ở giờ thứ 12. Lệnh BTC ngày 19–20/10 bị cắt đúng lúc 12h03 vì cú tụt này.

## Code đã sửa

| File | Thay đổi |
|---|---|
| `config/settings.py` | Thêm khối tham số `[2026-11-01]` (đều mặc định tắt) |
| `strategy/regime.py` | File mới: phân loại giai đoạn, quyết định vào lệnh, A, B, hệ số trailing |
| `strategy/risk.py` | `check_atr_trailing` của PP4 lấy hệ số qua `m4_trailing_multiplier`; khi tắt hết tùy chọn thì kết quả y hệt cũ |
| `strategy/exit_engine.py` | Thêm ứng viên thoát `M4_INVALIDATION` và `M4_TIME_STOP` |
| `bot/slot_engine.py` | Tính giai đoạn khi vào lệnh PP4; lưu `regime`, `regime_er`, `regime_slope_atr`, `signal_high/low`, `m4_tight` vào lệnh |
| `backtest/live_replay.py` | Mô phỏng y như trên (giai đoạn lúc vào lệnh, A xét mỗi giờ) |
| `tests/test_m4_regime.py` | Test mới |

## Cách backtest so sánh (chạy trên máy bạn)

Bản backtest vẫn dùng `--set`, không cần sửa `.env`. Ví dụ:

```bash
# 0. PP4 gốc (để so sánh)
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --out backtest/results/v0_goc

# 1. Có nhận diện giai đoạn: lệnh RANGE/ngược trend dùng stop 1.5 ATR
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --out backtest/results/v1_regime --set M4_REGIME_ENABLED=true

# 2. Bản 1 + A + B + D
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --out backtest/results/v2_regime_ABD --set M4_REGIME_ENABLED=true M4_INVALIDATION_EXIT=true M4_TIME_STOP=true M4_SMOOTH_GRACE=true

# 3. Phương án E: đứng ngoài khi RANGE
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --out backtest/results/v3_skip_range --set M4_REGIME_ENABLED=true M4_RANGE_SKIP_ENTRY=true

# 4. Chỉ D (grace mượt)
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --out backtest/results/v4_smooth --set M4_SMOOTH_GRACE=true
```

Mỗi thư mục có file `summary.csv`, `monthly.csv`, `trades.csv`. Trong `trades.csv`, cột `exit_reason` cho biết lệnh thoát theo cách nào (`M4_INVALIDATION`, `M4_TIME_STOP`, ...). Có thể thử thêm các ngưỡng khác, ví dụ `M4_REGIME_LOOKBACK=12` hoặc `M4_REGIME_ER_TREND=0.25`.

## Bật cho bot thật (chỉ sau khi backtest thắng rõ)

Thêm các dòng sau vào `.env` trên VPS rồi khởi động lại service, ví dụ `M4_REGIME_ENABLED=true`. Lưu ý: `.env` áp cho **mọi** bot PP4, cả paper lẫn trade thật. Lệnh đang mở không bị ảnh hưởng, vì giai đoạn chỉ được xác định lúc vào lệnh.
