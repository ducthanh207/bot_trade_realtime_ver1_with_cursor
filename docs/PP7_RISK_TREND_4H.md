# PP7: PP4 + size theo rủi ro + lọc trend + stop 4H (2026-11-20)

PP7 sửa 3 nguyên nhân chính gây sụt vốn lớn và liên tục của PP4. Ba nguyên nhân này được tìm ra khi phân tích backtest SOL, BNB và ETH từ 01/01 đến 20/11/2026:

| Vấn đề của PP4 | Bằng chứng | Cách PP7 sửa |
|---|---|---|
| Lệnh to gấp 6 lần vốn (20x × 30%), nên tiền lỗ phụ thuộc ATR | Lệnh thua chỉ đi ngược 1% giá nhưng mất 3.6–4.1% vốn, có lệnh mất 7–10% | **Size theo rủi ro:** chạm stop ban đầu chỉ mất `M7_RISK_PCT` vốn (mặc định 2%) |
| Stop 2.5 × ATR **1H** trong khi tín hiệu là khung **4H** | Một nửa số lệnh thua bị quét trong 8 giờ đầu, chiếm khoảng 60% tổng tiền lỗ | **Stop và trailing = 1.5 × ATR 4H** của nến tín hiệu, cố định, không siết sau 12h |
| Lọc EMA50 chỉ bật khi ADX > 30 | SOL giảm từ 103 xuống 73 (cuối tháng 10, giữa tháng 11) mà bot vẫn LONG. ETH: LONG -461, SHORT +1138 | **Lọc trend luôn bật:** LONG chỉ khi giá đóng 4H trên EMA50, SHORT khi dưới |

Các phần còn lại giữ nguyên như PP4: tín hiệu RSI/EMA/WMA 4H, chặn RSI cực trị, xác nhận RSI 1H, vùng ADX (dưới 18 thì bỏ lệnh, ADX quá cao thì giảm size), swing, giảm size theo chuỗi thua, circuit breaker và thoát `4H_EXIT`. Các hệ số giảm size (ADX, swing, chuỗi thua) giờ làm giảm **rủi ro**. Ví dụ, sau 2 lệnh thua, hệ số 0.7 nghĩa là lệnh sau chỉ rủi ro 1.4% vốn.

**Trần size:** notional không vượt mức PP4 (vốn × % vốn × đòn bẩy × hệ số size). Khi ATR 4H rất nhỏ, stop rất hẹp, rủi ro thực tế sẽ dưới 2%.

**Hard stop:** đặt ở `M7_MAX_STOP_CAPITAL_PCT` (mặc định 5% vốn), xa hơn stop thường. Nó chỉ là lớp an toàn.

**PP7 chỉ chạy backtest.** Bot paper và bot trade thật không dùng PP7, và `TRADING_METHOD=7` không được nhận. Khi kết quả tốt, ta mới làm thêm Paper 7 và tùy chọn PP7 trong /live.

## Cách chạy

**Trên web:** vào menu "Backtest PP7" (trang `/backtest7`), nhập cặp, ngày và vốn, rồi bấm "Chạy backtest". Đòn bẩy và % vốn lấy theo quy tắc vốn của Paper 4, đây là mức trần size của PP7. Kết quả có popup, biểu đồ và nút Xuất Excel giống các trang Paper khác. Cần `git pull` và khởi động lại web/bot trên VPS thì menu này mới hiện.

**Trên máy (so sánh trực tiếp PP4 và PP7 cùng lúc):**

```powershell
python -m backtest.live_replay --methods 4 7 --symbols SOLUSDT BNBUSDT ETHUSDT BTCUSDT --start 2026-01-01 --capital 1000
```

So sánh hai dòng PP4 và PP7 trong `backtest/results/<thời điểm>/summary.csv`, cụ thể là `return_pct`, `max_drawdown_pct` và `profit_factor`.

Để thử tham số khác, dùng `--set`, ví dụ:

```powershell
# rủi ro 1.5% mỗi lệnh, stop 2 × ATR 4H
python -m backtest.live_replay --methods 7 --symbols SOLUSDT --start 2026-01-01 --set M7_RISK_PCT=0.015 M7_ATR4H_MULT=2.0
# thêm điều kiện EMA50 phải dốc cùng hướng trong 3 nến 4H
python -m backtest.live_replay --methods 7 --symbols SOLUSDT --start 2026-01-01 --set M7_TREND_SLOPE_BARS=3
# bật Exit B đã sửa (RSI nến 4H đã đóng)
python -m backtest.live_replay --methods 7 --symbols SOLUSDT --start 2026-01-01 --set M7_EXIT_B=fixed
```

## Tham số (`config/settings.py`, khối [2026-11-20])

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| M7_RISK_PCT | 0.02 | % vốn mất nếu chạm stop ban đầu |
| M7_ATR4H_MULT | 1.5 | Stop và trailing = hệ số × ATR14 nến 4H lúc vào lệnh |
| M7_TREND_FILTER | true | Lọc trend EMA50 4H luôn bật |
| M7_TREND_SLOPE_BARS | 0 | Nếu lớn hơn 0, EMA50 phải dốc cùng hướng so với N nến 4H trước |
| M7_MAX_STOP_CAPITAL_PCT | 0.05 | Hard stop an toàn, tính theo % vốn |
| M7_EXIT_B | off | `off` giữ như PP4 (Exit B không chạy). `fixed` dùng Exit B đã sửa |

Code: `strategy/pp7.py` (lọc trend, khoảng stop, size). Cách vào lệnh nằm trong `backtest/live_replay.py` (`SlotSim.try_enter`). Trailing nằm trong `strategy/risk.py` (`check_atr_trailing`, nhánh PP7). Test: `tests/test_m7.py`.
