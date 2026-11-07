# PP5 — PP4 + lọc chu kỳ nến ngày (2026-11-07)

PP5 giữ nguyên toàn bộ PP4 (tín hiệu 4H, xác nhận RSI 1H, lọc RSI cực trị, ADX/EMA50/swing/streak,
circuit breaker, hard stop 10% vốn, ATR trailing 2.5 → 2.2 sau 12h) và thêm bộ lọc chu kỳ theo nến 1D.
Code: `strategy/daily_cycle.py`. Thiết kế đầy đủ: tài liệu "Thiết kế PP5: PP4 + chu kỳ nến ngày".

**Chạy ở đâu:**
- **Paper trade 5** (menu web "Paper trade 5", trang `/paper5`): slot paper riêng, mặc định *stopped*.
  Bấm "Kích hoạt" để bắt đầu. Trang hiển thị chu kỳ ngày hiện tại, có nút backtest PP5 (chỉ xem,
  không đổi paper thật). Telegram báo mở/đóng lệnh với tag `[PAPER5]` và chu kỳ lúc vào lệnh.
- **Trade thật** (`/live`): chọn chiến lược "PP5" khi tạo bot. Vẫn chịu công tắc trade thật chung
  (mặc định TẮT) và stop dự phòng trên sàn như các PP khác.
- PP1–PP4 không đổi. `TRADING_METHOD=5` trong .env không được nhận (không dùng chế độ cũ).

## Quy tắc (mọi phép xét dùng giá đóng của nến 1D đã đóng)

d = (close − EMA20 ngày) / EMA20.

| Chu kỳ | Khi nào | Được vào | Thoát lệnh |
|---|---|---|---|
| TĂNG | 2 nến đóng trên EMA, hoặc đột biến (đường lower %change nằm trên EMA). Kết thúc khi 2 nến đóng dưới EMA | Chỉ LONG | Như PP4 |
| GIẢM | Ngược lại | Chỉ SHORT | Như PP4 |
| ĐI NGANG thiên LONG | 3 nến gần nhất đều có \|d\| ≤ X, nến đóng gần nhất trên EMA | Chỉ LONG | Thoát nới |
| ĐI NGANG thiên SHORT | Như trên, nến đóng gần nhất dưới EMA | Chỉ SHORT | Thoát nới |
| TRUNG TÍNH | Từ đầu dữ liệu chưa có tín hiệu nào | Cả hai | Như PP4 |

X = 1 × ATR14(1D) / close (mặc định). Đi ngang kết thúc khi có nến đóng với |d| > X, lúc đó bot quay về
trạng thái TĂNG/GIẢM. Lệnh đang mở khi chu kỳ đổi được giữ nguyên.

**Thoát nới** (chỉ cho lệnh vào lúc đi ngang): trailing 3.5 × ATR 1H cố định (không siết sau 12h),
size × 0.6 (hard stop tính theo % vốn nên tự giãn ra, số tiền lỗ tối đa không đổi), chốt lời ở dải
%change 4H như PP2, Exit B đã sửa (tính RSI trên nến 4H đã đóng).

## Tham số (config/settings.py, khối [2026-11-07])

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| M5_DAILY_EMA_LEN | 20 | EMA nến ngày (giống tab Biểu đồ) |
| M5_DAILY_KLINES | 1000 | Số nến ngày đã đóng dùng để tính |
| M5_CONFIRM_BARS | 2 | Số nến đóng liên tiếp để vào/kết thúc chu kỳ |
| M5_SPIKE_ENABLED | true | Bật đột biến theo %change |
| M5_PCT_LOOKBACK_TRADES | 15 | Lookback %change trên nến ngày |
| M5_SIDEWAYS_BARS | 3 | Số nến sát EMA để coi là đi ngang |
| M5_SIDEWAYS_MODE | atr | atr: X = k × ATR ngày; pct: X cố định |
| M5_SIDEWAYS_ATR_K | 1.0 | k |
| M5_SIDEWAYS_PCT | 3.0 | X (%) khi MODE=pct |
| M5_SIDEWAYS_MIXED | latest | Nến lẫn hai phía EMA: latest (theo nến gần nhất) / both / skip |
| M5_WIDE_ATR_MULTIPLIER | 3.5 | Trailing khi đi ngang |
| M5_WIDE_SIZE_MULT | 0.6 | Hệ số size khi đi ngang |
| M5_WIDE_PCT_TP | true | Chốt lời dải %change khi đi ngang |
| M5_EXIT_B | wide | Exit B đã sửa: wide (lệnh đi ngang) / all / off |

## Backtest (chạy trên máy anh)

PP5 cần nến ngày từ khoảng 1000 ngày trước `--start`. Script tự tải bằng 1 request mỗi cặp và lưu
vào `backtest/data_cache/<SYMBOL>/1d.csv.gz`.

```
# So sánh PP4 với PP5 mặc định
python backtest/live_replay.py --methods 4 5 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast

# X cố định 3% thay vì theo ATR
python backtest/live_replay.py --methods 5 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M5_SIDEWAYS_MODE=pct M5_SIDEWAYS_PCT=3 --out backtest/results/pp5_x3pct

# k = 0.75 / 1.25
python backtest/live_replay.py --methods 5 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M5_SIDEWAYS_ATR_K=0.75 --out backtest/results/pp5_k075

# Chỉ lọc hướng, không dùng gói thoát nới (để tách tác dụng của từng phần)
python backtest/live_replay.py --methods 5 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M5_WIDE_ATR_MULTIPLIER=2.5 M5_WIDE_SIZE_MULT=1.0 M5_WIDE_PCT_TP=false M5_EXIT_B=off --out backtest/results/pp5_filter_only
```

`trades.csv` có thêm cột `cycle`, `cycle_wide`, `cycle_d_pct`, `cycle_x_pct` cho biết mỗi lệnh PP5
vào lúc chu kỳ nào.
