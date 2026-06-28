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
