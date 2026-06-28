# % Change Avg - Logic Draft

Muc tieu:

- Do bien thien gia trung binh cua cac lenh lich su khop voi rule vao/ra co ban.
- Khong tinh ATR trailing va khong tinh early exit.
- Tra ve dai tren/duoi theo kieu Bollinger Bands, nhung dua tren `% change avg`.

## Dinh nghia `% change` cho moi lenh

Su dung:

- Gia mo cua nen vao lenh (entry candle open)
- Gia dong cua nen thoat lenh (exit candle close)

Cong thuc:

- LONG: `pct_change = (exit_close - entry_open) / entry_open * 100`
- SHORT: `pct_change = (entry_open - exit_close) / entry_open * 100`

Ghi chu:

- Cong thuc tren giu cung dau "thuan chieu lenh".
- Neu can gia tri do lech tuyet doi de ve dai doi xung, dung `abs(pct_change)`.

## Quy trinh tinh

1. Lay du lieu nen lich su theo khung gio dang xem.
2. Tinh indicator (RSI, EMA_RSI, WMA_RSI) bang `strategy.indicators.add_indicators`.
3. Chay lai logic phat hien lenh lich su:
   - Entry: `long_entry`/`short_entry`
   - Exit: `long_exit`/`short_exit`
4. Chi **cac lenh da dong** theo chiến lược (base entry/exit), không lấy từ “tổng số nến”.

5. Mỗi khi **một lệnh đóng** (thứ j, 0-based), tính **một lần** (chuẩn hóa **%**):
   - `half_width_pct = mean( abs(pct_change) )` trên tối đa `lookback_trades` lệnh đã đóng gần nhất (gồm lệnh vừa đóng).  
   - `pct_change` mỗi lệnh như mục “Định nghĩa % change” ở trên.

6. Giá trị `half_width_pct` **giữ nguyên** cho mọi nến sau đó cho đến khi **có lệnh đóng tiếp theo**.

7. Trên từng nến (vẫn là **giá** trên chart, bám nến):
   - `mid = close`
   - `upper = close * (1 + half_width_pct / 100)`
   - `lower = close * (1 - half_width_pct / 100)`

8. API: `band_half_width_pct` và `avg_abs_pct` (cùng ý — nửa độ rộng ± theo %); `band_half_width_usdt` = `current_close * band_half_width_pct / 100` (tiện đọc tại giá cuối).

## Input can custom

- `lookback_trades`: so luong lenh lich su dung de tinh trung binh.
- `timeframe`: khung nen (1m, 5m, 15m, 1h, 4h, 1d...).

Khi timeframe doi, bo phan goi ham chi can nap lai du lieu nen theo timeframe moi va goi lai ham tinh.

## Output de tich hop web/API sau nay

Ham logic tra ve:

- danh sach lenh da detect
- `% change avg` (signed + abs)
- gia tri `upper`, `mid`, `lower` tai nen hien tai
- series `upper` / `mid` / `lower` theo tung nen (khong con 3 duong ngang co dinh)

## Demo API + chart (dung Binance public data)

Da them:

- `api_demo.py`: API doc lap
- `dashboard_demo.html`: trang demo ve nen + bands
- `overlay_pct_change_avg_demo.js`: logic ve 3 line bands + duong doc net dut (vao / ra) tu `pct.trades`

API demo:

- `GET /api/pct-change-avg?symbol=BTCUSDT&interval=5m&lookback_trades=15&limit=600`

Gia tri mac dinh:

- `lookback_trades = 15`

### Cach chay nhanh

1. Mo terminal tai thu muc:
   - `D:\Bot_VPS_Realtime_ver1_11_3_26\idea_for_update\pct_change_avg`
2. Chay API:
   - `python api_demo.py`
3. Mo file:
   - `dashboard_demo.html`
4. Bam `Load` de lay du lieu Binance va ve bands.

## Tich hop production (khong doi file trong thu muc nay)

- Logic chinh nam o `strategy/pct_change_avg.py`.
- API Flask: `GET /api/klines?...&lookback_trades=15` tra them khoi `pct_change`; trang `/chart` ve indicator **%change** (3 duong + duong doc vao/ra).
