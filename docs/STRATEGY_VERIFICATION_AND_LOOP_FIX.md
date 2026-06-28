# Xác minh chiến lược & nguyên nhân lệnh loop (4H_EARLY)

## 1. Đối chiếu lý do vào / thoát với code

### 1.1. Vào lệnh (entry) – dùng 2 nến 4h đã đóng

| Loại | Điều kiện trong code | Mô tả ngắn |
|------|----------------------|------------|
| **LONG** | `long_entry(prev_row_closed, row_closed)` | 3 trường hợp (OR), chỉ cần 1 đúng: (1) EMA>RSI>WMA → RSI>EMA>WMA; (2) WMA>EMA>RSI → RSI>WMA>EMA; (3) WMA>EMA>RSI → WMA>RSI>EMA |
| **SHORT** | `short_entry(prev_row_closed, row_closed)` | 3 trường hợp (OR): (1) EMA<RSI<WMA → RSI<EMA<WMA; (2) WMA<EMA<RSI → RSI<WMA<EMA; (3) WMA<EMA<RSI → WMA<RSI<EMA |

- `prev_row_closed` = nến 4h iloc[-3], `row_closed` = nến 4h iloc[-2] (nến đã đóng gần nhất).
- Chỉ kiểm tra khi `in_4h_window` = True (5 phút đầu sau đóng nến 4h: 03, 07, 11, 15, 19, 23 GMT+7).

### 1.2. Thoát lệnh (exit) – cùng 2 nến 4h + nến 1m

| Lý do thoát trong log/UI | Trong code | Điều kiện |
|--------------------------|------------|-----------|
| **4H_EXIT** | `"4H_EXIT"` | LONG: `long_exit(prev, row)` = prev RSI>EMA>WMA và row WMA<RSI<EMA. SHORT: `short_exit(prev, row)` = prev RSI<EMA<WMA và row WMA>RSI>EMA. |
| **4H_EARLY** / **4H_EARLY_EXIT** | `"4H_EARLY_EXIT"` | Early exit RSI (khi `RSI_EARLY_EXIT=true`). LONG: `long_exit_early` = RSI cắt xuống EMA_RSI hoặc RSI < RSI_LONG_CUT (42). SHORT: `short_exit_early` = RSI cắt lên EMA_RSI hoặc **RSI > RSI_SHORT_CUT (58)**. |
| **ATR_TRAIL** | `"ATR_TRAIL"` | Trailing stop 1m: khoảng cách = ATR × ATR_MULTIPLIER; LONG: low ≤ trail_stop; SHORT: high ≥ trail_stop. |
| **LIQUIDATION** | `"LIQUIDATION"` | Giá chạm mức thanh lý (maintenance margin). |

- Số đứng trước "4H_EARLY" trong log của bạn là **giá thoát (exit_price)**, không phải lý do khác.

---

## 2. Nguyên nhân loop: cùng một nến vừa vào vừa thoát early

- Entry và exit 4H (gồm cả early) đều dùng **cùng cặp nến**: `prev_row_closed` (iloc[-3]), `row_closed` (iloc[-2]).
- Trong cửa sổ 5 phút đầu khung 4h, dữ liệu không đổi: mỗi vòng lặp vẫn là cùng `row_closed`.

**Với SHORT:**

- Vào lệnh: một trong 3 điều kiện short entry thỏa; trong cả 3 trường hợp đều có **row RSI < row EMA_RSI**.
- Thoát early SHORT: `short_exit_early` = (RSI cắt lên EMA_RSI) **hoặc** (row **RSI > RSI_SHORT_CUT**). Trên **cùng** `row_closed`, RSI < EMA_RSI nên “cắt lên” = False. Chỉ còn điều kiện **row RSI > 58**.

Kết quả: nếu tại nến vào lệnh mà **RSI nằm trong khoảng (58, EMA_RSI)** (ví dụ RSI = 59, EMA_RSI = 62):

1. Short entry = True (RSI < EMA_RSI) → mở SHORT.
2. Ngay cùng vòng lặp, `short_exit_early` = True vì RSI (59) > 58 → thêm candidate "4H_EARLY_EXIT" → đóng lệnh.
3. Vòng sau: vẫn cùng `row_closed`, short entry vẫn True → vào lại → lại thoát early → **loop**.

Các cột số giống hệt nhau (67.05624, 67.06988, 59.73…) ở mọi lệnh loop là **entry/exit RSI, EMA_RSI, WMA_RSI** của cùng một nến 4h vì vào và thoát luôn trên cùng một bar.

---

## 3. Cách sửa đề xuất

- **Chỉ áp dụng early exit khi đã có nến 4h mới đóng sau lúc vào lệnh.**  
  Tức là: không xét `long_exit_early` / `short_exit_early` khi `row_closed` vẫn là **đúng nến 4h dùng để vào lệnh** (cùng bar với entry).

Cách làm trong code:

1. Khi mở lệnh, lưu vào `open_trade` thêm **timestamp nến 4h dùng để vào**: `entry_4h_ts = df_4h.index[-2]` (index của `row_closed` lúc vào).
2. Trong nhánh EXIT, khi gọi `long_exit_early` / `short_exit_early`:  
   chỉ gọi nếu **index của `row_closed` hiện tại khác `entry_4h_ts`** (đã có ít nhất một nến 4h đóng sau khi vào).  
   Nếu `df_4h.index[-2] == entry_4h_ts` thì **bỏ qua** early exit (vẫn giữ 4H_EXIT và ATR_TRAIL như cũ).

Như vậy early exit chỉ chạy khi đã sang bar 4h mới, tránh cùng một nến vừa cho vào vừa cho thoát → hết loop.
