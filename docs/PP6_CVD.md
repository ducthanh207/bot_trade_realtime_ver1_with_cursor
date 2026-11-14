# PP6 và PP6.1: thêm CVD vào PP4 / PP5 (2026-11-14)

- **PP6 = PP4 + CVD.** Giữ nguyên toàn bộ PP4 (tín hiệu 4H, xác nhận RSI 1H, lọc RSI cực trị, ADX/EMA50/swing/streak,
  circuit breaker, hard stop 10% vốn, trailing 2.5 → 2.2 ATR sau 12h), thêm 2 lớp CVD.
- **PP6.1 = PP5 + CVD.** Giữ nguyên toàn bộ PP5 (chu kỳ nến ngày EMA20, gói thoát nới khi đi ngang, tuỳ chọn lệnh ngược chu kỳ),
  thêm 2 lớp CVD như PP6 và dùng CVD để chọn phía khi chu kỳ ngày đi ngang.

Code: `strategy/cvd.py`. Hiện **chỉ chạy trong backtest** (`backtest/live_replay.py --methods 6 6.1`). Chưa có Paper 6 / Paper 6.1,
chưa chọn được ở `/live`, bot đang chạy trên VPS không đổi gì. PP1–PP5 giữ nguyên kết quả (có test kiểm tra).

## CVD lấy từ đâu

Nến Binance Futures có sẵn cột *taker buy base volume* (khối lượng lệnh mua chủ động). Từ đó:

```
delta = mua chủ động − bán chủ động = 2 × taker_buy − volume
CVD   = cộng dồn delta
```

CVD cộng dồn từ một mốc tuỳ ý nên chỉ **độ dốc** có ý nghĩa. Độ dốc trên N nến đã đóng:

```
độ dốc = tổng delta N nến / tổng volume N nến     (từ −1 đến +1)
```

Lớn hơn 0 nghĩa là bên mua chủ động áp đảo trong N nến đó, nhỏ hơn 0 là bên bán. Chia cho volume để so được giữa BTC/ETH/SOL và
giữa lúc volume to/nhỏ. Mọi phép tính chỉ dùng nến **đã đóng** (không nhìn trước).

## Quy tắc

| Lớp | Áp dụng | Quy tắc | Tham số mặc định |
|---|---|---|---|
| 1. Xác nhận vào lệnh (4H) | PP6, PP6.1 | LONG chỉ vào khi độ dốc CVD 6 nến 4H (24h) > 0; SHORT khi < 0. Ngược chiều thì bỏ lệnh. | `M6_4H_BARS=6`, `M6_4H_MIN_RATIO=0` |
| 1b. Timing 1H (tuỳ chọn) | PP6, PP6.1 | Thêm điều kiện độ dốc 8 nến 1H cùng chiều lệnh | `M6_1H_ENTRY_CONFIRM=false` |
| 2. Thoát / siết theo 1H | PP6, PP6.1 | Mỗi nến 1H đóng: nếu độ dốc 8 nến 1H ngược lệnh **2 nến liên tiếp** (và lệnh đã giữ ≥ 2h) → siết trailing về **1.5 × ATR 1H** (stop chỉ đi về phía có lợi). | `M6_EXIT_MODE=tighten`, `M6_1H_BARS=8`, `M6_EXIT_CONFIRM_BARS=2`, `M6_EXIT_MIN_HOURS=2`, `M6_TIGHT_ATR_MULT=1.5`, `M6_EXIT_AGAINST_RATIO=0` |
| 3. Phía khi đi ngang | Chỉ PP6.1 | Chu kỳ ngày đi ngang: PP5 chọn phía theo nến ngày đóng gần nhất. PP6.1 chọn theo dấu độ dốc CVD 12 nến 4H (2 ngày). Lệnh vẫn dùng gói thoát nới của PP5. | `M61_SIDEWAYS_BIAS=cvd`, `M61_SIDE_CVD_BARS=12` |

Chu kỳ TĂNG/GIẢM của PP6.1 vẫn như PP5: tăng chỉ LONG, giảm chỉ SHORT, rồi thêm lớp 1 (CVD 4H phải cùng chiều).

**Vì sao chọn như vậy:**
- Điểm yếu của PP4 là thua liên tiếp bằng ATR_TRAIL khi thị trường đi ngang (BTC 17–31/10: 2 thắng / 10 thua). Lúc đi ngang,
  tín hiệu RSI 4H hay đảo qua lại nhưng dòng tiền chủ động không nghiêng hẳn về phía nào. Lớp 1 bỏ các lệnh mà dòng tiền 24h
  đang đi ngược.
- Lệnh thua thường đi ngược ngay sau khi vào và trôi tới 2.5 ATR. Lớp 2 thấy bên bán (với LONG) áp đảo 2 giờ liền thì kéo stop
  về 1.5 ATR, nên lệnh sai cắt sớm hơn, lệnh đang lãi khoá được nhiều lãi hơn khi dòng tiền quay đầu.
- Dùng độ dốc nhiều nến (6 nến 4H, 8 nến 1H) để một nến đột biến không quyết định.

`M6_EXIT_MODE=close` thì đóng lệnh ngay (lý do `CVD_EXIT`) thay vì siết. `off` tắt lớp 2.
`M61_SIDEWAYS_BIAS=both`: đi ngang phải cả nến ngày lẫn CVD cùng phía mới vào. `close`: như PP5.

## Backtest (chạy trên máy anh)

Cần code của nhánh `claude/project-thread-1xbhje` (PR PP6). Lần đầu chạy PP6/PP6.1 script tự tải thêm nến 1H có taker buy
(khoảng 1 request cho mỗi 62 ngày mỗi cặp) vào `backtest/data_cache/<SYMBOL>/1h_taker.csv.gz`. Cache nến 1m cũ vẫn dùng lại.

```
# 1) So sánh chính: PP4 với PP6, PP5 với PP6.1, cùng một lần chạy
python backtest/live_replay.py --methods 4 6 5 6.1 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --out backtest/results/pp6_main

# 2) Chỉ lọc vào lệnh (tắt lớp 2) → biết lớp 1 tốt hay xấu
python backtest/live_replay.py --methods 6 6.1 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M6_EXIT_MODE=off --out backtest/results/pp6_filter_only

# 3) Đóng lệnh ngay thay vì siết
python backtest/live_replay.py --methods 6 6.1 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M6_EXIT_MODE=close --out backtest/results/pp6_close

# 4) Ngưỡng độ dốc 4H chặt hơn (0.01 = bên mua hơn bên bán 1% volume)
python backtest/live_replay.py --methods 6 6.1 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M6_4H_MIN_RATIO=0.01 --out backtest/results/pp6_t001

# 5) PP6.1 chọn phía đi ngang như PP5 (để tách tác dụng của lớp 3)
python backtest/live_replay.py --methods 6.1 --symbols BTCUSDT ETHUSDT SOLUSDT --start 2026-01-01 --end 2026-11-01 --fast --set M61_SIDEWAYS_BIAS=close --out backtest/results/pp61_close
```

Kết quả nằm trong `summary.csv` (dòng `PP4`, `PP6`, `PP5`, `PP6.1`). `trades.csv` có thêm cột `cvd4_ratio`, `cvd1_ratio`,
`cvd_side_ratio` (độ dốc lúc vào lệnh), `cvd_tight` và `cvd_tight_at` (lệnh có bị siết theo CVD 1H không, lúc nào).
Gửi `summary.csv` và `trades.csv` của lần chạy 1 và 2 để chỉnh ngưỡng.

## Bước sau (khi backtest tốt)

Paper 6 / Paper 6.1 trên web, Telegram `[PAPER6]`, chọn PP6 ở `/live`. Phần này cần thêm cột taker buy vào dữ liệu nến của bot
(`exchange/binance_client.py`); `bot/slot_engine.py` đã đọc sẵn cột `taker_buy` khi có.
