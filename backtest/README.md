# Backtest phát lại live — `live_replay.py` (khuyên dùng)

Chạy lại **đúng vòng lặp `bot/paper_loop.py`** trên dữ liệu lịch sử Binance Futures, cho cả 4 phương pháp
(PP1–PP4, tương ứng Paper 1–4) và nhiều cặp coin trong một lần chạy. Dùng thẳng code chiến lược của bot
(`strategy/*`, `bot/paper_fees.py`, `config/settings.py` + `.env`), nên đổi tham số trong `.env` thì backtest đổi theo.

## Cài đặt & chạy (Windows)

```bash
cd D:\bot_trade_realtime_ver1_with_cursor-main
pip install -r requirements.txt

# Chiến lược 4, nhiều cặp chạy song song, khoảng thời gian tự chọn
python backtest/live_replay.py --methods 4 --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT --start 2026-01-01 --end 2026-10-01

# Mặc định: SYMBOL trong .env, 365 ngày gần nhất, cả 4 phương pháp
python backtest/live_replay.py

# Thử tham số khác mà không sửa .env
python backtest/live_replay.py --methods 4 --set M4_MAX_STOP_CAPITAL_PCT=0.08 M4_ATR_MULTIPLIER=2.0
```

Tuỳ chọn hay dùng: `--workers 4` (số cặp chạy song song, mặc định số nhân CPU - 1), `--download-workers 3`,
`--max-weight 1200`, `--source vision` (tải zip, nhanh hơn API), `--fast` (nhanh ~4 lần, cùng kết quả).

## Không nhìn trước tương lai (look-ahead)

Mặc định chạy chế độ **strict**: thời gian đi tuần tự từng phút, từng ngày. Tại mỗi thời điểm t, code chiến lược chỉ nhận
các nến đã đóng trước t (cửa sổ 200 nến như bot live lấy từ Binance) và chỉ báo được tính lại trên đúng cửa sổ đó:

- Vào/thoát 4H ở phút đầu nến 4H mới, dùng nến 4H vừa đóng; giá khớp = giá mở phút đó, không dùng high/low/close của nến đang chạy.
- Trailing/thanh lý: nến 1m vừa đóng được dùng đủ high/low, nến đang chạy chỉ có giá mở. ATR lấy từ nến 1H đã đóng.
- Tải dữ liệu chỉ lưu nến 1m đã đóng (bỏ nến đang chạy API trả về).
- `tests/test_live_replay.py::test_no_lookahead_data_cut_at_t` xoá toàn bộ dữ liệu sau t rồi so sánh: mọi giá trị bot thấy tại t phải giữ nguyên.

## Không bị lỗi request quá nhiều

- Bước tải chạy trước, nhiều luồng nhưng dùng chung một bộ đếm weight (mặc định 1200 trong giới hạn 2400 weight/phút của Binance, mỗi lần lấy 1500 nến tốn 10 weight).
- Đọc header `X-MBX-USED-WEIGHT-1M`, tự nghỉ khi gần ngưỡng; gặp 429/418 thì nghỉ đúng `Retry-After` rồi thử lại.
- Cache theo tháng trong `backtest/data_cache/`; tháng đang chạy chỉ tải phần còn thiếu. Bước backtest song song chỉ đọc cache, không gửi request.
- Một năm 1 cặp ≈ 350 request ≈ 3 phút ở lần tải đầu; các lần sau gần như tức thì.

## Kết quả (`backtest/results/<thời điểm chạy>/`)

- `summary.csv`: mỗi dòng = 1 cặp × 1 phương pháp: số lệnh, % thắng, vốn cuối, % lời, drawdown lớn nhất, profit factor, số lần thanh lý, lý do thoát.
- `monthly.csv`: % lời/lỗ từng tháng theo cặp × phương pháp → so sánh cặp nào tốt nhất theo từng giai đoạn.
- `trades.csv`: toàn bộ lệnh (giờ vào/ra giờ VN, giá, size, phí vào, PnL sau phí thoát, vốn trước/sau, lý do thoát, RSI).

## Mô phỏng giống live đến đâu

- Mỗi phút là một tick: nến 1m vừa đóng được quét đủ high/low, nến đang chạy chỉ có giá mở (đúng như vòng lặp 5 giây).
  Thanh lý, hard stop PP4, ATR trailing (ATR 1H đã đóng gần nhất) chạy qua chính `check_atr_trailing`, `limit_pnl_and_exit_price`...
  `tests/test_live_replay.py` kiểm tra tầng này cho cùng kết quả với `compute_exit_candidates`.
- Đầu mỗi nến 4H (03/07/11/15/19/23h giờ VN): thoát 4H/early/%change gọi thẳng `compute_exit_candidates`; vào lệnh theo đúng các bộ lọc
  của `paper_loop` (circuit breaker, ADX, EMA50, swing, streak, RSI 1H, RSI extreme). Giá vào/ra = giá mở nến 1m đầu tiên.
- Phí taker vào + ra như paper. **Chưa tính** funding fee và trượt giá (paper live cũng không tính).
- Lệnh còn mở cuối dữ liệu được đóng theo giá cuối (`END_OF_DATA`).

---

# Backtest – Chiến lược 4H (RSI, ATR, Early Exit)

Chạy backtest trên dữ liệu CSV local, dùng **cùng chiến lược vào/ra và quản lý vốn** như bot live.

## Dữ liệu

- **4H:** `D:\Botbacktest\BTC_4h_VN.csv`
- **1m:** `D:\Botbacktest\BTC_1m_VN.csv`

Định dạng CSV: cột `Open Time`, `Open`, `High`, `Low`, `Close`, `Volume`.

## Cách chạy

Từ thư mục gốc project:

```bash
cd D:\Bot_VPS_Realtime_ver1_11_3_26
python backtest/run_backtest.py
```

## Tham số (giống bot live)

- Vốn ban đầu: **50 USD**
- Đòn bẩy: 20x, % ví mỗi lệnh: 30%
- Fee: Taker 0.04%
- Max lỗ theo vốn: 30%, ATR multiplier: 1.5
- Early exit RSI: bật, LONG cut 42, SHORT cut 58

## Kết quả

1. **Console:** Tổng hợp PnL, số lệnh, tỉ lệ thắng (in không dấu để tránh lỗi encoding Windows).
2. **`D:\Botbacktest\backtest_summary.txt`:** Bản tóm tắt (UTF-8, tiếng Việt).
3. **`D:\Botbacktest\backtest_trades.csv`:** Toàn bộ lệnh với:
   - Thời điểm vào/ra, side, giá vào/ra, PnL, % PnL (margin & vốn), vốn sau lệnh
   - Lý do thoát (4H_EXIT, 4H_EARLY_EXIT, ATR_TRAIL, LIQUIDATION, END_OF_DATA)
   - RSI, EMA_RSI, WMA_RSI lúc vào và lúc ra
