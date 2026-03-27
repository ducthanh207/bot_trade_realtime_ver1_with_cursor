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
4. Lay `N` lenh gan nhat (custom lookback).
5. Tinh `% change avg`:
   - `avg_signed_pct = mean(pct_change)`
   - `avg_abs_pct = mean(abs(pct_change))`
6. Tao band quanh gia hien tai:
   - `upper = current_close * (1 + avg_abs_pct/100)`
   - `lower = current_close * (1 - avg_abs_pct/100)`
7. Xuat du lieu line ngang cho chart:
   - `mid_line`: line ngang tai `current_close`
   - `upper_line`: line ngang tai `upper`
   - `lower_line`: line ngang tai `lower`

## Input can custom

- `lookback_trades`: so luong lenh lich su dung de tinh trung binh.
- `timeframe`: khung nen (1m, 5m, 15m, 1h, 4h, 1d...).

Khi timeframe doi, bo phan goi ham chi can nap lai du lieu nen theo timeframe moi va goi lai ham tinh.

## Output de tich hop web/API sau nay

Ham logic tra ve:

- danh sach lenh da detect
- `% change avg` (signed + abs)
- gia tri `upper`, `mid`, `lower` tai nen hien tai
- series line ngang theo timeline de ve chart

## Demo API + chart (dung Binance public data)

Da them:

- `api_demo.py`: API doc lap
- `dashboard_demo.html`: trang demo ve nen + bands
- `overlay_pct_change_avg_demo.js`: logic ve 3 line bands

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
