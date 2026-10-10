# Backtest phát lại live — `live_replay.py` (khuyên dùng)

Chạy lại **đúng vòng lặp `bot/paper_loop.py`** trên dữ liệu lịch sử Binance Futures, cho cả 4 phương pháp
(PP1–PP4, tương ứng Paper 1–4) và nhiều cặp coin trong một lần chạy. Dùng thẳng code chiến lược của bot
(`strategy/*`, `bot/paper_fees.py`, `config/settings.py` + `.env`), nên đổi tham số trong `.env` thì backtest đổi theo.

## Cài đặt & chạy (Windows)

```bash
cd D:\bot_trade_realtime_ver1_with_cursor-main
pip install -r requirements.txt

# Mặc định: SYMBOL trong .env (BTCUSDT), 365 ngày gần nhất, cả 4 phương pháp
python backtest/live_replay.py

# Nhiều cặp + khoảng thời gian tự chọn
python backtest/live_replay.py --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT --start 2025-10-01 --end 2026-10-01

# Chỉ PP3, PP4 và thử tham số khác mà không sửa .env
python backtest/live_replay.py --methods 3 4 --set M4_MAX_STOP_CAPITAL_PCT=0.08 M4_ATR_MULTIPLIER=2.0
```

Lần đầu tải nến 1m từ `data.binance.vision` (dự phòng: API `fapi.binance.com`), lưu vào `backtest/data_cache/`;
các lần sau chạy không cần mạng. Một năm 1 cặp ≈ 525k nến 1m, chạy 4 phương pháp mất khoảng 1 phút.

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
