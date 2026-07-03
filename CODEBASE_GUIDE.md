# Hướng dẫn toàn bộ codebase — Bot Paper Trade Realtime

> Tài liệu này mô tả đầy đủ mục đích, phương pháp, kết nối giữa các file.
> Có thể gửi nguyên văn cho Claude để tái tạo lại toàn bộ code.

---

## 1. Tổng quan dự án

**Tên:** Bot Paper Trade Realtime — ATR Strategy  
**Mục đích:** Chạy 4 chiến lược giao dịch song song trên vốn ảo (paper trade), dùng giá thật từ Binance Futures (BTCUSDT). Không đặt lệnh thật trên sàn. Kết quả hiển thị qua web dashboard và Telegram.

**Slot → Method:** 1=PP1 (classic), 2=PP2 (%change TP), 3=PP3 (Exit B + CB), 4=PP4 (nâng cấp PP3).

**Ngôn ngữ:** Python 3.10+ (backend), Vanilla JS (frontend), HTML/CSS  
**Framework:** Flask (web server), python-binance (API), pandas-ta (indicators)  
**Deploy:** VPS Ubuntu, systemd service `bot-live`, port 5000  

---

## 2. Kiến trúc tổng thể

```
run_live.py          ← Entry point: khởi động tất cả
    ├── bot/paper_loop.py      ← Vòng lặp chính: chạy 3 slot song song, 5 giây/lần
    ├── bot/live_loop.py       ← Vòng lặp trade thật (chưa kích hoạt)
    ├── web/app.py             ← Flask API + serve HTML
    └── telegram/commands.py   ← Long-poll Telegram bot

Bot state (in-memory):
    bot/state.py               ← Module toàn cục, lưu trạng thái 3 slot

Persistence:
    bot/paper_persistence.py   ← Đọc/ghi paper_state.json khi có thay đổi

Exchange:
    exchange/binance_client.py ← Lấy klines từ Binance public API

Strategy layer:
    strategy/indicators.py     ← Tính RSI, EMA, ATR, WMA trên DataFrame
    strategy/signals.py        ← Tín hiệu vào/ra lệnh từ RSI
    strategy/exit_engine.py    ← Chọn điểm thoát tốt nhất
    strategy/risk.py           ← Tính size, trailing stop, max loss
    strategy/pct_change_avg.py ← Dải %change (TP target cho Method 2)
    strategy/exit_scenarios.py ← Ước tính điểm thoát để hiển thị Telegram
    strategy/advisory.py       ← Khuyến nghị LONG/SHORT cho Telegram /advise
    strategy/strategies/
        paper_slots.py         ← Map slot 1/2/3 → method 1/2/3
        registry.py            ← Đăng ký và mô tả các phương pháp

Backtest:
    bot/paper3_backtest.py     ← Backtest Method 3 trên dữ liệu lịch sử

Web frontend:
    web/templates/base.html    ← Layout chung (nav, CSS link)
    web/templates/paper.html   ← UI Paper trade slot 1
    web/templates/paper2.html  ← UI Paper trade slot 2
    web/templates/paper3.html  ← UI Paper trade slot 3 + backtest panel
    web/templates/chart.html   ← Biểu đồ nến TradingView-style
    web/templates/real.html    ← Placeholder "Trade thật"
    web/static/js/paper.js     ← Logic UI chung cho cả 3 slot paper trade
    web/static/js/paper_charts.js ← Mini chart vốn + profit (Canvas 2D)
    web/static/js/chart.js     ← Chart giá + indicator (LightweightCharts)
    web/static/css/dashboard.css ← Toàn bộ CSS

Telegram:
    telegram/notifier.py       ← Gửi thông báo (trade mở/đóng, status)
    telegram/commands.py       ← Nhận lệnh /status /advise /trade ...

Config:
    config/settings.py         ← Load .env → object settings

Tests/Tools:
    backtest/run_backtest.py   ← Backtest CLI ngoài
    tools/paper_reconcile_check.py ← Kiểm tra cân đối vốn
    bot/paper_fees.py          ← Tính phí giao dịch
    bot/paper_ledger_audit.py  ← Audit sổ cái
```

---

## 3. Luồng hoạt động

### Khởi động
```
run_live.py
  → load_paper_state()         # đọc paper_state.json → state.py
  → Thread 1: run_paper_loop() # vòng lặp 5 giây
  → Thread 2: run_web()        # Flask server port 5000
  → Thread 3: run_telegram_commands() # long-poll Telegram
```

### Vòng lặp paper_loop (mỗi 5 giây)
```
paper_loop.py → với mỗi slot (1, 2, 3):
  1. Kiểm tra slot status (stopped → skip, paused → chỉ exit)
  2. Lấy klines 4H (>=80 nến warm-up) + 1m + 1H từ binance_client
  3. Tính indicators (RSI, EMA, ATR...) qua add_indicators()
  4. Nếu đang có lệnh mở:
     a. exit_engine.check_exits() → trả về exit_result nếu cần thoát
     b. Nếu có exit: đóng lệnh, cập nhật balance, lưu vào state, persist
  5. Nếu không có lệnh mở + status=running + trong 4H boundary window (±5 phút):
     a. signals.should_enter_long/short() → tín hiệu vào
     b. risk.size_and_margin() → tính size + margin
     c. Mở lệnh mới, trừ phí vào, lưu vào state, persist
  6. Mỗi 15 phút: gửi Telegram status
  7. Mỗi 60 phút: gửi Telegram hourly status
```

### Web API → UI
```
Browser (paper.js)
  → setInterval 5s: fetch /api/status
  → render bảng lệnh, thống kê, chart mini
  → nút Kích hoạt: POST /api/paper/start
  → nút Ẩn lệnh: computeOverrides() tính lại PNL client-side
  → nút Xuất CSV: lọc hidden, tạo Blob và download
```

---

## 4. Chi tiết từng file

---

### `run_live.py` — Entry Point

**Mục đích:** Điểm khởi động duy nhất. Tạo 3 thread: trading loop, web server, Telegram bot.

**Kết nối:** Import `bot.paper_loop`, `web.app`, `telegram.commands`, `bot.paper_persistence`, `bot.state`

**Logic chính:**
```python
load_paper_state()  # khôi phục state từ JSON
Thread(target=run_paper_loop).start()
Thread(target=run_web).start()
Thread(target=run_telegram_commands).start()
```

---

### `config/settings.py` — Cấu hình

**Mục đích:** Load toàn bộ config từ file `.env` vào object `settings`. Mọi file khác đều `from config import settings`.

**Các tham số quan trọng:**
| Tên | Mặc định | Ý nghĩa |
|-----|----------|---------|
| `SYMBOL` | `BTCUSDT` | Cặp giao dịch |
| `LEVERAGE` | `20` | Đòn bẩy |
| `WALLET_PCT` | `0.30` | % vốn mỗi lệnh |
| `TAKER_FEE` | `0.0004` | Phí taker Binance |
| `MAKER_FEE` | `0.0002` | Phí maker |
| `MAINT_MARGIN_RATE` | `0.005` | Tỷ lệ margin duy trì (thanh lý) |
| `ATR_MULTIPLIER` | `1.5` | Hệ số ATR trail |
| `MAX_STOP_CAPITAL_PCT` | `0.30` | Max loss/vốn mỗi lệnh |
| `RSI_EARLY_EXIT` | `True` | Bật early exit |
| `RSI_LONG_CUT` | `42` | RSI ngưỡng early exit LONG |
| `RSI_SHORT_CUT` | `58` | RSI ngưỡng early exit SHORT |
| `TRADING_METHOD` | `"1"` | Method 1/2/3 (mặc định live) |
| `LOOP_INTERVAL` | `5` | Giây/lần lặp |
| `STATUS_INTERVAL_MINUTES` | `15` | Tần suất báo Telegram |
| `WEB_HOST` | `0.0.0.0` | Flask host |
| `WEB_PORT` | `5000` | Flask port |

**Method 3 params:** `M3_ADX_LOW=18` (chặn entry), `M3_ADX_HIGH=23` (dưới mức này size ×0.5), `M3_ATR_MULTIPLIER=2.2`, `M3_ATR_MULTIPLIER_GRACE=2.5` (12h đầu), `M3_CB_LIGHT_STREAK=4` (→8h), `M3_CB_HEAVY_STREAK=7` (→48h), `M3_CB_HEAVY_DD_PCT=28` / `M3_CB_HEAVY_DD_DAYS=14`, `M3_EMA_TREND_LEN=50` (filter khi ADX>30), `M3_SWING_LOOKBACK=6`, `M3_SWING_DISAGREE_SIZE=0.6`

**Method 4 (nâng cấp PP3 — slot 4):** giữ toàn bộ entry/filter/CB của PP3, thay đổi:
| Khác biệt | PP3 | PP4 |
|---|---|---|
| Early exit thường | Có (RSI<42 / cross 1 nến) | **Bỏ** — chỉ Exit B (RSI vượt ngưỡng + slope `M4_EARLY_EXIT_B_CONFIRM_BARS`=2 nến) |
| Grace ATR trail | 2.5 cố định suốt lệnh | 2.5 trong 12h đầu (`M4_ATR_GRACE_HOURS`) rồi **tự siết về 2.2** |
| Trần lỗ mỗi lệnh | 30% vốn (chỉ cap trên giấy) | **10% vốn** (`M4_MAX_STOP_CAPITAL_PCT`) — tầng HARD_STOP thoát thật khi giá chạm |
| Entry filter thêm | — | Chặn SHORT khi RSI<`M4_RSI_SHORT_FLOOR`(38) / LONG khi RSI>`M4_RSI_LONG_CEIL`(62); cần RSI 1H cùng hướng (`M4_REQUIRE_1H_CONFIRM`) |
| ADX exhaustion | ADX cao = full size | ADX≥`M4_ADX_EXHAUSTION`(45) → size ×`M4_ADX_EXHAUSTION_SIZE`(0.5) |

Backtest tham chiếu (vốn 1000, lev 20, wallet 30%, trail mô phỏng nến 1H):
- Jan–Jul 2026: M3 final 1069.6 (84 lệnh, WR 35.7%) vs **M4 final 1080.7 (47 lệnh, WR 46.8%)**
- May–Jun 2026: M3 final 659.3 (lỗ nặng) vs **M4 final 988.3 (gần hòa)**

---

### `exchange/binance_client.py` — Binance Client

**Mục đích:** Lấy klines từ Binance Futures public API. Không cần API key cho paper trade.

**Class `BinanceClient`:**
- `get_klines(symbol, interval, limit)` → DataFrame với index là timestamp GMT+7, cột: `open, high, low, close, volume`
- `get_price(symbol)` → float giá hiện tại
- `get_balance()`, `get_position()`, `place_market_order()`, `close_position()` → dùng cho live trade (cần API key)

**Kết nối:** Được gọi từ `paper_loop.py`, `live_loop.py`, `app.py` (qua `_get_client()`)

**Lưu ý:** Dùng `python-binance` với endpoint futures testnet hoặc mainnet tùy `BINANCE_TESTNET=True/False`

---

### `bot/state.py` — State Module (In-memory)

**Mục đích:** Lưu trữ toàn bộ trạng thái bot trong memory. Là "database" trung tâm được share giữa tất cả thread.

**Cấu trúc dữ liệu:**
```
3 nhóm biến toàn cục (prefix _paper_, _paper2_, _paper3_):
  - _*_initial_capital: float — vốn ban đầu
  - _*_balance: float — số dư hiện tại
  - _*_status: "stopped"|"running"|"paused"
  - _*_started_at: datetime or None
  - _*_open_trade: dict or None — lệnh đang mở
  - _*_trades: list[dict] — lịch sử lệnh đã đóng
  - _*_last_trade: dict — lệnh đóng gần nhất
  - _*_leverage: float or None
  - _*_wallet_pct: float or None

Paper 3 thêm:
  - _paper3_consecutive_losses: int — chuỗi thua liên tiếp
  - _paper3_cb_light_until: datetime — circuit breaker nhẹ đến bao giờ
  - _paper3_cb_heavy_until: datetime — circuit breaker nặng đến bao giờ
```

**Hàm quan trọng:**
- `to_status_dict()` → trả về dict đầy đủ cho web API `/api/status`
- `paper_start(capital)` / `paper_clear_history()` / `paper_pause()` / `paper_stop()` — tương tự cho paper2_, paper3_
- `restore_paper_trades(trades)` — khôi phục sau load JSON

**Kết nối:** Được import bởi `paper_loop.py`, `live_loop.py`, `app.py`, `paper_persistence.py`, `telegram/`

---

### `bot/paper_persistence.py` — Lưu trữ JSON

**Mục đích:** Đọc/ghi file `paper_state.json` để state không mất khi restart service.

**Hàm:**
- `save_paper_state()` → serialize toàn bộ state của 3 slot ra JSON
- `load_paper_state()` → đọc JSON → gọi các `set_*` trong state.py để khôi phục

**Format JSON lưu:**
```json
{
  "paper_initial_capital": 1000.0,
  "paper_balance": 1234.56,
  "paper_status": "running",
  "paper_started_at": "2024-01-01T00:00:00+07:00",
  "paper_open_trade": {...},
  "paper_trades": [...],
  "paper_leverage": 20.0,
  "paper_wallet_pct": 0.30,
  "paper2_...": ...,
  "paper3_...": "... (đầy đủ: capital/balance/status/trades/open_trade/CB/hidden keys)",
  "paper4_...": "... (như paper3, cho Method 4)"
}
```
Cả 4 slot đều được lưu/khôi phục đầy đủ (kể cả circuit breaker và hidden trade keys của slot 3/4).

**Kết nối:** Gọi từ `run_live.py` (load), `paper_loop.py` (save sau mỗi trade)

---

### `bot/paper_fees.py` — Tính phí

**Mục đích:** Tính phí taker Binance theo công thức chuẩn. Paper trade mô phỏng đúng phí thực tế.

**Công thức:** `fee = |size| × entry_price × TAKER_FEE`  
(size tính bằng BTC, entry_price USDT/BTC → fee tính bằng USDT)

**Hàm:**
- `linear_taker_fee_usdt(size, price, fee_rate)` → phí 1 chiều
- `closed_trade_fee_entry_exit_usdt(trade, fee_rate)` → phí vào + ra của 1 lệnh
- `slot_total_fees_usdt(trades, open_trade, fee_rate)` → tổng phí cả slot
- `wallet_balance_after_replay(initial, trades, open_trade, fee_rate)` → tính lại balance từ đầu

**Phí thực tế:**
- Vào lệnh: trừ từ balance ngay khi mở
- Ra lệnh: đã trừ trong `profit` (profit = raw_pnl - exit_fee)
- Net PNL thực = `profit - entry_fee` mỗi lệnh

**Kết nối:** Dùng trong `state.py` (to_status_dict), `app.py` (orders JSON), `paper.js` (computeOverrides)

---

### `bot/paper_loop.py` — Vòng lặp Trading Chính

**Mục đích:** Chạy logic giao dịch cho cả 3 slot mỗi 5 giây. Đây là "não" của bot.

**Cấu trúc vòng lặp:**
```python
while not stop_requested:
    for slot in [1, 2, 3]:
        run_slot(slot, klines_4h, klines_1m, klines_1h)
    time.sleep(LOOP_INTERVAL)
```

**Điều kiện vào lệnh (4H boundary window):**
- Chỉ vào lệnh trong 5 phút đầu của nến 4H boundary (giờ 3, 7, 11, 15, 19, 23 **GMT+7**)
- Cần ≥80 nến 4H để warm-up indicator đủ dữ liệu
- Không vào nếu có lệnh đang mở

**Method 3 — Circuit Breaker:**
- Light CB: ≥4 thua liên tiếp (M3_CB_LIGHT_STREAK) → dừng 2 nến 4H = 8 giờ
- Heavy CB: ≥7 thua liên tiếp (M3_CB_HEAVY_STREAK) HOẶC drawdown ≥28% trong 14 ngày → dừng 12 nến 4H = 48 giờ
- Size giảm dần theo chuỗi thua: ×(1 − losses×0.15), sàn 0.25 (m3_streak_multiplier)
- Thắng 1 lệnh: reset consecutive_losses về 0

**Lệnh mở — dict structure:**
```python
{
  "side": "LONG"|"SHORT",
  "entry_price": float,
  "size": float,          # BTC
  "entry_time": ISO str,
  "trail_stop": float,    # ATR trailing stop price
  "capital_at_open": float,
  "leverage": int,
  "wallet_pct": float,
  "trading_method": "1"|"2"|"3",
  "atr": float,
  "pct_change_snapshot": {...}  # Method 2
}
```

**Lệnh đóng — dict thêm:**
```python
{
  ...open fields...,
  "exit_time": ISO str,
  "exit_price": float,
  "profit": float,        # raw_pnl - exit_fee
  "fee_exit": float,
  "pct_pnl": float,       # % PnL trên giá
  "pct_pnl_capital": float, # % PnL trên vốn
  "capital_after": float,
  "exit_reason": str,     # "liquidation"|"atr_trail"|"4h_signal"|"early_exit"|"exit_b"|"pct_change_tp"|"manual"
  "trade_key": str,       # unique key cho hide/show
  "replay_index": int     # thứ tự để sort
}
```

**Kết nối:** Import `state`, `binance_client`, `indicators`, `signals`, `exit_engine`, `risk`, `paper_fees`, `paper_persistence`, `notifier`, `pct_change_avg`, `paper_slots`

---

### `strategy/indicators.py` — Tính Indicator

**Mục đích:** Thêm các cột indicator vào DataFrame klines.

**Hàm:**
```python
add_indicators(df, rsi_period=14, ema_period=20, ema_rsi_period=9,
               wma_rsi_period=45, atr_period=14) → DataFrame
```
Thêm cột: `RSI`, `EMA_RSI` (WMA của RSI), `WMA_RSI` (WMA chậm của RSI), `ATR`, `EMA`, `WMA`

```python
add_indicators_m3(df, ema_trend_len=50, swing_lookback=6, adx_length=14) → DataFrame
```
Thêm thêm: `ADX`, `DI_PLUS`, `DI_MINUS`, `EMA_TREND`, `swing_low`, `swing_high`, `higher_low`, `lower_high`

**Dùng pandas-ta:** `ta.rsi()`, `ta.wma()`, `ta.ema()`, `ta.atr()`, `ta.adx()`

**Kết nối:** Gọi từ `paper_loop.py`, `app.py` (API /api/klines)

---

### `strategy/signals.py` — Tín hiệu Vào/Ra

**Mục đích:** Dựa trên RSI, EMA_RSI, WMA_RSI để tạo tín hiệu entry/exit.

**LONG Entry (bất kỳ 1 trong 3 điều kiện):**
1. RSI cắt lên từ dưới EMA_RSI (crossover), RSI < 50
2. RSI tăng mạnh từ vùng oversold (RSI trước < 35, hiện > 38)
3. RSI > WMA_RSI sau khi vừa dưới WMA_RSI (xác nhận xu hướng)

**SHORT Entry (ngược lại):**
1. RSI cắt xuống từ trên EMA_RSI, RSI > 50
2. RSI giảm mạnh từ overbought
3. RSI < WMA_RSI sau khi vừa trên WMA_RSI

**Exit signals:**
- `should_exit_long()`: RSI cắt xuống dưới EMA_RSI
- `should_exit_short()`: RSI cắt lên trên EMA_RSI
- `should_early_exit_long()`: RSI < RSI_LONG_CUT (42) HOẶC RSI cắt xuống EMA_RSI
- `should_early_exit_short()`: RSI > RSI_SHORT_CUT (58) HOẶC RSI cắt lên EMA_RSI
- `should_exit_b_long()` (Method 3): RSI < 45 VÀ giảm N bar liên tiếp (strong reversal)
- `should_exit_b_short()` (Method 3): RSI > 55 VÀ tăng N bar liên tiếp

**Kết nối:** Gọi từ `paper_loop.py`, `exit_engine.py`

---

### `strategy/exit_engine.py` — Chọn Điểm Thoát

**Mục đích:** Từ trạng thái lệnh + klines hiện tại → trả về exit_result (nếu cần thoát) hoặc None.

**Hàm chính:** `check_exits(open_trade, df_4h, df_1m, df_1h, method) → dict|None`

**Thứ tự kiểm tra:**
1. **Liquidation:** nếu ATR trail chạm liquidation price → exit ngay
2. **ATR Trailing:** nếu giá 1m chạm trail_stop → exit
3. **4H Signal:** nếu nến 4H mới có tín hiệu exit (method 1: luôn; method 2: chỉ nếu PnL>0 + RSI 1H xác nhận)
4. **Early Exit:** RSI ngưỡng sớm (nếu RSI_EARLY_EXIT=True)
5. **Exit B** (method 3): RSI reversal mạnh
6. **%change TP** (method 2): giá chạm dải %change + RSI 1H xác nhận

**ATR Trailing update:** Mỗi nến 1m, trail_stop di chuyển theo hướng có lợi (ratchet - chỉ dịch để bảo vệ thêm, không dịch ngược).

**Exit result dict:**
```python
{
  "exit_price": float,
  "exit_time": ISO str,
  "profit": float,    # raw_pnl - exit_fee
  "fee_exit": float,
  "exit_reason": str
}
```

**Kết nối:** Gọi từ `paper_loop.py`, `live_loop.py`

---

### `strategy/risk.py` — Quản lý Rủi ro

**Mục đích:** Tính size lệnh, trailing stop, giới hạn max loss.

**Hàm:**
- `size_and_margin(capital, entry_price, leverage, wallet_pct)` → `(size_btc, margin_usdt)`
- `initial_trail_stop(entry_price, atr, side, multiplier)` → price của trail stop ban đầu
- `update_trail_stop(current_stop, current_price, atr, side, multiplier)` → new stop (chỉ dịch có lợi)
- `max_loss_from_capital(open_trade)` → USDT tối đa có thể mất (MAX_STOP_CAPITAL_PCT × capital)
- `atr_multiplier_for_trade(open_trade)` → hệ số ATR (grace period 2.5x → 2.2x sau 12h với method 3)

**Method 3 specific:**
- `adx_zone_size_factor(adx_val)` → 0 (ADX<18), 0.5 (18-23), 1.0 (>23)
- `streak_size_multiplier(consecutive_losses)` → max(0.25, 1 - losses×0.25)

**Kết nối:** Gọi từ `paper_loop.py` (khi mở lệnh), `exit_engine.py` (khi tính liquidation)

---

### `strategy/pct_change_avg.py` — Dải %Change (Method 2)

**Mục đích:** Tính dải biến động giá trung bình dựa trên lịch sử lệnh đã đóng. Dùng làm TP target cho Method 2.

**Cách tính:**
1. Lấy `lookback_trades` lệnh đóng gần nhất
2. Tính |% thay đổi| mỗi lệnh = |exit_price - entry_price| / entry_price × 100
3. `avg_abs_pct` = trung bình các |%|
4. `band_half_width_pct` = avg_abs_pct / 2
5. Dải: `mid = close hiện tại`, `upper = mid × (1 + half_width/100)`, `lower = mid × (1 - half_width/100)`

**Hàm:**
- `build_pct_change_avg_bands(df, lookback_trades)` → dict `{upper, mid, lower, lines: {...}}`
- `build_pct_change_avg_bands_series(df, lookback_trades)` → dict cho từng điểm thời gian

**Dải "lines":** Mảng `{time, value}` cho mỗi nến → dùng để vẽ lên chart

**Kết nối:** Gọi từ `paper_loop.py` (khi mở lệnh Method 2), `app.py` (API /api/klines), `exit_engine.py` (TP check), `exit_scenarios.py`

---

### `strategy/exit_scenarios.py` — Ước tính Điểm Thoát

**Mục đích:** Tính xấp xỉ các mức thoát để hiển thị trong Telegram (không dùng để thoát thật).

**Trả về dict:**
```python
{
  "atr_trail_px": float,      # giá trail stop hiện tại
  "pct_upper": float,         # %change upper band
  "pct_lower": float,         # %change lower band
  "early_exit_hint": str,     # mô tả điều kiện early exit
  "stoploss_px": float,       # giá max loss
  "method": str
}
```

**Kết nối:** Gọi từ `telegram/notifier.py` (hourly status)

---

### `strategy/advisory.py` — Khuyến nghị LONG/SHORT

**Mục đích:** Đánh giá điều kiện LONG/SHORT từ indicator hiện tại → trả lời Telegram /advise.

**Trả về:**
```python
{
  "long_conditions": [{"name": str, "met": bool}, ...],
  "short_conditions": [...],
  "long_pct": float,   # % điều kiện LONG thỏa
  "short_pct": float,
  "risk_pct": float    # ATR/price × 100
}
```

**Kết nối:** Gọi từ `telegram/commands.py`

---

### `strategy/strategies/paper_slots.py` — Map Slot → Method

**Mục đích:** Định nghĩa mỗi slot paper trade dùng phương pháp nào.

```python
SLOT_METHOD = {1: "1", 2: "2", 3: "3", 4: "4"}

def method_for_paper_slot(slot_id: int) -> str:
    return SLOT_METHOD.get(int(slot_id), "1")
```

**Kết nối:** Gọi từ `paper_loop.py`

---

### `strategy/strategies/registry.py` — Đăng ký Phương pháp

**Mục đích:** Metadata về các phương pháp giao dịch.

```python
METHODS = {"1": "Classic", "2": "%change TP", "3": "Exit B + CB"}

def uses_pct_change_bands(method) -> bool:  # True chỉ với method "2"
def describe_method(method) -> str          # mô tả chi tiết
```

**Kết nối:** Gọi từ `exit_engine.py`, `exit_scenarios.py`, `paper_loop.py`

---

### `bot/paper3_backtest.py` — Backtest Method 3

**Mục đích:** Chạy lại Method 3 trên dữ liệu lịch sử Binance để đánh giá chiến lược.

**Hàm:** `run_backtest(symbol, start_dt, end_dt, initial_capital, leverage, wallet_pct, taker_fee) → dict`

**Kết quả:**
```python
{
  "total_trades": int,
  "wins": int, "losses": int,
  "winrate": float,
  "total_pnl": float,
  "final_balance": float,
  "trades": [...]
}
```

**Logic:**
1. `_fetch_klines_range()` → phân trang lấy klines từ Binance theo `startTime/endTime`
2. Lặp qua từng nến 4H boundary
3. Áp dụng đầy đủ logic Method 3: ADX zone, EMA trend, swing structure, circuit breaker, streak multiplier
4. Force close lệnh cuối ở nến cuối cùng

**Kết nối:** Gọi từ `app.py` endpoint `/api/paper3/backtest`

---

### `bot/live_loop.py` — Vòng lặp Trade Thật

**Mục đích:** Tương tự paper_loop nhưng gọi exchange API thật để đặt lệnh. **Chưa kích hoạt trong production.**

**Khác paper_loop:**
- Gọi `place_market_order()`, `close_position()` thực sự
- Sync state với exchange (xử lý trường hợp bot restart giữa chừng)
- Có flag `DRY_RUN` để test không đặt lệnh thật

**Kết nối:** Giống paper_loop, thêm `live_loop → exchange/binance_client (order placement)`

---

### `telegram/notifier.py` — Gửi Thông báo

**Mục đích:** Gửi tin nhắn Telegram về các sự kiện giao dịch và status định kỳ.

**Hàm:**
- `send_message(text)` → gửi tin nhắn cơ bản
- `notify_trade_opened(slot, trade, method)` → thông báo vào lệnh
- `notify_trade_closed(slot, trade, method)` → thông báo đóng lệnh (kèm PnL, lý do)
- `send_status_15m(status)` → báo 15 phút (slot 1+2 position info)
- `send_status_hourly(status)` → báo giờ (kèm exit scenarios ước tính)

**Format thông báo mở lệnh:**
```
🟢 LONG vào 60234.50
Method: 2 | Slot: 2
Size: 0.0498 BTC | Đòn bẩy: 20x
Vốn dùng: 300 USDT (30%)
ATR trail: 59800.00
```

**Kết nối:** Gọi từ `paper_loop.py`, `live_loop.py`

---

### `telegram/commands.py` — Nhận Lệnh Telegram

**Mục đích:** Bot Telegram long-poll nhận lệnh người dùng.

**Commands:**
| Lệnh | Chức năng |
|------|-----------|
| `/start`, `/ping` | Kiểm tra bot còn sống |
| `/status` | Hiện status tổng (vốn, PnL, lệnh mở) |
| `/now` | Chi tiết lệnh đang mở (PnL live, điểm thoát) |
| `/pnl` | Tổng PnL |
| `/advise` | Khuyến nghị LONG/SHORT theo signal hiện tại |
| `/trade` | Vào lệnh thủ công (có inline button LONG/SHORT) |
| `/stop` | Dừng paper trading |

**Flow /trade:**
```
User: /trade
Bot: [inline buttons: Vào LONG | Vào SHORT | Đóng lệnh]
User: Vào LONG
Bot: Nhập % vốn (1-100):
User: 30
Bot: Vào lệnh LONG, size 0.049 BTC, trail 59800...
```

**Kết nối:** Gọi `state`, `binance_client`, `indicators`, `signals`, `risk`, `advisory`, `notifier`

---

### `web/app.py` — Flask Web Server

**Mục đích:** Serve HTML pages + cung cấp JSON API cho frontend.

**Routes HTML:**
| Route | Template | nav_active |
|-------|----------|-----------|
| `/` | redirect → `/paper` | |
| `/paper` | paper.html | "paper" |
| `/paper2` | paper2.html | "paper2" |
| `/paper3` | paper3.html | "paper3" |
| `/chart` | chart.html | "chart" |
| `/real` | real.html | "real" |

**API Endpoints:**

`GET /api/status` → Trả về toàn bộ state dict + tính PnL_Open, fee_open, capital_open cho lệnh đang mở:
```python
{
  # từ state.to_status_dict()...
  "paper_pnl_open": float,     # PnL lệnh đang mở
  "paper_fee_open": float,     # phí vào lệnh đang mở
  "paper_capital_open": float, # balance + pnl_open
  # tương tự paper2_, paper3_
}
```

`GET /api/orders?slot=1|2|3` → Danh sách lệnh cho UI table:
```python
{
  "orders": [{
    "id": int,
    "side": "LONG"|"SHORT",
    "entry_time": ISO str,
    "entry_price": float,
    "exit_time": ISO str,
    "exit_price": float,
    "pnl": float,        # profit (= raw_pnl - exit_fee)
    "entry_fee": float,
    "fee_exit": float,
    "fee": float,        # total fee
    "pct_pnl": float,
    "pct_pnl_capital": float,
    "capital_after": float,
    "exit_reason": str,
    "size": float,
    "symbol": str,
    "is_open": bool,
    "trade_key": str,
    "replay_index": int
  }, ...]
}
```

`POST /api/paper/start` body: `{initial_capital: float}` → Kích hoạt slot 1  
`POST /api/paper/pause` → Tạm dừng  
`POST /api/paper/stop` → Dừng  
`POST /api/paper/clear-history` → Xóa toàn bộ  
`POST /api/paper/set-initial-capital` body: `{initial_capital: float}` → Lưu mốc vốn  
`POST /api/paper/capital-rules` body: `{leverage, wallet_pct}` → Cập nhật đòn bẩy/%vốn  
`POST /api/paper/close` body: `{slot, exit_price?}` → Đóng lệnh thủ công  

*(Tương tự cho /api/paper2/... và /api/paper3/...)*

`POST /api/paper3/backtest` body:
```json
{"start_date": "2024-01-01", "end_date": "2024-06-01",
 "initial_capital": 1000, "load_to_state": true}
```

`GET /api/klines?interval=5m&limit=500&lookback_trades=15&ema_period=20&rsi_period=14&ema_rsi_period=9&wma_rsi_period=45&atr_period=14`  
→ OHLC + indicators + %change bands cho chart

`GET /api/price` → giá hiện tại

**Kết nối:** Import `state`, `paper_persistence`, `binance_client`, `indicators`, `pct_change_avg`, `paper3_backtest`, `paper_fees`

---

### `web/templates/base.html` — Layout Chung

**Mục đích:** Template cha cho tất cả trang. Chứa nav bar, link CSS.

**Nav links:** Paper trade | Paper trade 2 | Paper trade 3 | Biểu đồ | Trade thật

**Block:** `{% block content %}`, `{% block scripts %}`, `{% block title %}`, `{% block head_extra %}`

**CSS:** Load `dashboard.css`. Chart page thêm LightweightCharts CDN trong `head_extra`.

---

### `web/templates/paper.html` / `paper2.html` / `paper3.html` — UI Paper Trade

**Mục đích:** Trang paper trade cho mỗi slot. Cấu trúc giống nhau, chỉ khác `window.PAPER_UI`.

**Điểm khác biệt:**
```javascript
// paper.html
window.PAPER_UI = { slot: 1, prefix: "paper", apiBase: "/api/paper" };

// paper2.html
window.PAPER_UI = { slot: 2, prefix: "paper2", apiBase: "/api/paper2" };

// paper3.html
window.PAPER_UI = { slot: 3, prefix: "paper3", apiBase: "/api/paper3" };
```

**paper3.html thêm:** Panel backtest với date picker + nút "Chạy backtest" → gọi `/api/paper3/backtest`

**Cấu trúc HTML:**
```
<section class="paper-layout">
  <header class="overview">        ← Vốn, nút Kích hoạt/Dừng/Pause/Xóa, thống kê
    <div class="overview-rules">   ← Đòn bẩy, % vốn
  <aside class="orders-panel">
    <div class="paper-charts-row"> ← Chart vốn (line) + chart profit (bar)
    <table class="orders-table">   ← Danh sách lệnh
```

**Scripts:** Load `paper_charts.js` → `paper.js` (theo thứ tự)

---

### `web/templates/chart.html` — Biểu đồ

**Mục đích:** Hiển thị chart nến BTCUSDT với indicators, markers lệnh, đồng bộ 2 panel.

**Cấu trúc:**
```
<div class="chart-tv-toolbar">   ← Khung thời gian, Lookback, Live/Playback buttons
<div class="chart-legend-ohlc">  ← O H L C Delta (hover crosshair)
<div class="chart-tv-body">
  <aside class="chart-tv-sidebar">  ← Toggles Vol/EMA/%change/RSI/P1/P2/P3 + Chu kỳ inputs
  <div class="chart-tv-main">
    <div class="chart-tv-price-wrap">  ← Chart giá + Volume + EMA + %change bands
    <div class="chart-tv-ind-wrap">    ← Chart RSI + EMA_RSI + WMA_RSI
```

**Sidebar toggles:** Vol, EMA, %change, RSI, E↗RSI, W↗RSI, ATR, P1, P2, P3 (markers)

**Sidebar params:** EMA chu kỳ, RSI chu kỳ, E↗RSI chu kỳ, W↗RSI chu kỳ, ATR chu kỳ → nút "Áp dụng"

**Script:** `chart.js` + LightweightCharts v4.1.0 CDN

---

### `web/static/js/paper.js` — Logic UI Paper Trade

**Mục đích:** Script chung cho 3 trang paper trade. Đọc `window.PAPER_UI` để biết dùng slot nào.

**Khởi tạo:**
```javascript
window.PAPER_UI = { slot: 1, prefix: "paper", apiBase: "/api/paper" }
// paper.js đọc: var slot = cfg.slot, var apiBase = cfg.apiBase, ...
```

**Vòng lặp refresh (5 giây):**
```
fetch /api/status → renderStatus() → cập nhật thống kê header
fetch /api/orders?slot=N → renderOrders() → vẽ bảng + chart
```

**Hidden orders (ẩn lệnh):**
- `hiddenMap`: object `{trade_key: true}` lưu trong localStorage
- Khi toggle ẩn: `hiddenMap[trade_key] = true/false` → `computeOverrides()` → cập nhật UI
- `computeOverrides()`: tính lại PNL, winrate, balance, fees chỉ từ lệnh không ẩn (replay từ đầu)
- Cách tính: `sumPnl += profit - linearFeeUsdt(size, entry_price, taker)` (true net PNL)

**CSV Export:**
```javascript
// Lọc: bỏ lệnh ẩn + lệnh đang mở
var visible = lastOrders.filter(o => !orderIsOpen(o) && !hiddenMap[o.trade_key]);
// Tạo Blob CSV + download
```

**Buttons:**
- Kích hoạt → POST /api/.../start
- Tạm dừng → POST /api/.../pause
- Dừng → POST /api/.../stop
- Xóa toàn bộ → POST /api/.../clear-history (chỉ slot hiện tại)
- Lưu mốc vốn → POST /api/.../set-initial-capital
- Cập nhật quy tắc vốn → POST /api/.../capital-rules

**Kết nối:** Đọc từ `/api/status`, `/api/orders`, gọi các `/api/paper*/...`. Dùng `PaperMiniCharts` từ `paper_charts.js`.

---

### `web/static/js/paper_charts.js` — Mini Charts

**Mục đích:** Vẽ 2 chart nhỏ cho mỗi trang paper trade: đường vốn theo thời gian + cột profit từng lệnh. Dùng Canvas 2D thuần (không thư viện).

**API:**
```javascript
window.PaperMiniCharts.update(orders, statusDict, {
  prefix: "paper",       // "paper" | "paper2" | "paper3"
  hiddenMap: {},         // lệnh ẩn
  onOrderSelect: fn      // callback khi click lệnh trên chart
})
```

**Chart vốn (line):**
- X axis: thời gian exit của lệnh
- Y axis: `capital_after` mỗi lệnh đã đóng
- Điểm đầu: `started_at`, vốn ban đầu
- Điểm cuối (nếu có lệnh mở): balance hiện tại
- Hover → đường dọc + tooltip ID lệnh

**Chart profit (bar):**
- Mỗi cột = 1 lệnh (xanh = lãi, đỏ = lỗ)
- Click → highlight lệnh tương ứng trong bảng

**Kết nối:** Gọi từ `paper.js`. Không gọi API.

---

### `web/static/js/chart.js` — Biểu đồ LightweightCharts

**Mục đích:** Render 2 chart đồng bộ: chart giá + chart indicator. Dùng [LightweightCharts v4](https://tradingview.github.io/lightweight-charts/).

**2 Chart:**
- `chartPrice`: Nến OHLC + Volume + EMA + %change bands (upper/mid/lower) + ATR (trục trái ẩn)
- `chartIndicator`: RSI + EMA_RSI + WMA_RSI (0-100)

**Đồng bộ 2 chart:** `subscribeVisibleLogicalRangeChange` → `syncPeerLogicalRange()` (dùng logical range để tránh lệch)

**Markers (điểm vào/ra lệnh):**
```javascript
// Mỗi slot có màu/hình riêng:
P1: arrowUp/arrowDown  màu #26a69a/#ef5350 (xanh/đỏ)
P2: circle/circle      màu #00bcd4/#ff9800 (cyan/cam)
P3: square/square      màu #ffeb3b/#9c27b0 (vàng/tím)
```
Fetch `/api/orders?slot=1`, `/api/orders?slot=2`, `/api/orders?slot=3` mỗi giây.

**Fix zoom/pan:** `restoreAfterPoll()` chỉ restore logical range, KHÔNG reset `barSpacing`/`rightOffset` → user zoom/pan được giữ nguyên sau poll.

**Playback:** Double-click nến → playback từ điểm đó. Nút +1 nến, ▶ Play, ⏸ Pause, Live.

**Indicator params:** Inputs EMA/RSI/E↗RSI/W↗RSI/ATR → gửi qua query string tới `/api/klines` → backend tính lại.

**Settings persistence:** `localStorage` lưu timeframe, lookback, toggles, logical range (zoom vị trí).

**Kết nối:** Fetch `/api/klines`, `/api/orders?slot=1/2/3`. LightweightCharts CDN.

---

### `web/static/css/dashboard.css` — CSS

**Mục đích:** Toàn bộ styling cho web dashboard.

**Layout chính:**
```
.layout-root (flex column, 100vh)
  .top-nav (flex, height 44px)
  .paper-layout (flex column, flex:1)
    .overview (header, flex wrap)
    .orders-panel (flex column, flex:1, overflow hidden)
      .paper-charts-row (2 chart boxes)
      .orders-table-wrap (scroll)
  .chart-tv-root
    .chart-tv-toolbar
    .chart-tv-body (flex row)
      .chart-tv-sidebar (88px)
      .chart-tv-main (flex column)
        .chart-tv-pane--price (height 60%)
        .chart-tv-pane--ind (height 40%)
```

**Dark theme:** Background `#131722`, text `#d1d4dc`, border `#2a2e39`

**Mobile responsive:** `@media (max-width: 768px)` — layout chuyển sang vertical, overflow visible để cuộn được.

**Sidebar indicator params:** `.chart-ind-params`, `.ind-param-label`, `.ind-apply-btn`

---

## 5. Dữ liệu lưu trữ

### `paper_state.json` (195KB+)
File JSON lưu toàn bộ state của 3 slot. Được ghi sau mỗi lần mở/đóng lệnh.

### `localStorage` (browser)
- `atrChartTv_settings_v1` — chart settings (timeframe, zoom, toggles)
- `paper_hidden_orders_{prefix}` — danh sách trade_key bị ẩn

---

## 6. Quy trình deploy lên VPS

```bash
# 1. Clone repo
git clone https://github.com/ducthanh207/bot_trade_realtime_ver1_with_cursor /root/Bot_VPS_Realtime_ver1_11_3_26

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Tạo .env từ .env.example
cp .env.example .env
# Điền BINANCE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ...

# 4. Cài systemd service
cp scripts/bot-live.service /etc/systemd/system/
systemctl enable bot-live
systemctl start bot-live

# 5. Cập nhật code
git pull
systemctl restart bot-live
```

**Service:** Chạy `python run_live.py` từ `/root/Bot_VPS_Realtime_ver1_11_3_26/`

---

## 7. Hướng dẫn cho Claude tái tạo code

Nếu muốn Claude viết lại toàn bộ project từ đầu, gửi prompt sau:

```
Hãy tạo một Python bot paper trading với các đặc điểm sau:

TỔNG QUAN:
- Chạy 3 slot paper trade song song (vốn ảo, giá thật từ Binance Futures BTCUSDT)
- 3 phương pháp (Method 1/2/3), mỗi slot dùng 1 method
- Web dashboard Flask port 5000 + Telegram bot
- Deploy VPS Ubuntu với systemd

CẤU TRÚC FILE (theo đúng thứ tự dependency):
1. config/settings.py — load .env variables
2. exchange/binance_client.py — get_klines() public API, chuyển sang DataFrame GMT+7
3. bot/state.py — global variables cho 3 slot, getter/setter, to_status_dict()
4. bot/paper_fees.py — linear_taker_fee_usdt(size, price, rate)
5. bot/paper_persistence.py — save/load paper_state.json
6. strategy/indicators.py — add_indicators(df, rsi_period, ema_period, ...) dùng pandas-ta
7. strategy/signals.py — should_enter_long/short(), should_exit_*(), should_exit_b_*()
8. strategy/risk.py — size_and_margin(), update_trail_stop(), max_loss_from_capital()
9. strategy/pct_change_avg.py — build_pct_change_avg_bands() → upper/mid/lower bands
10. strategy/exit_engine.py — check_exits() → priority: liquidation > ATR trail > 4H signal > early exit > exit_b > pct_change_tp
11. strategy/exit_scenarios.py — build_exit_scenarios_dict() cho Telegram display
12. strategy/advisory.py — evaluate long/short conditions cho /advise
13. strategy/strategies/paper_slots.py — SLOT_METHODS = {1:"1", 2:"2", 3:"3"}
14. strategy/strategies/registry.py — uses_pct_change_bands(), describe_method()
15. bot/paper_loop.py — main loop 5s, 3 slots, 4H boundary window, circuit breaker
16. bot/paper3_backtest.py — backtest Method 3 trên Binance historical klines
17. telegram/notifier.py — notify_trade_opened/closed(), send_status_15m/hourly()
18. telegram/commands.py — long-poll: /status /advise /trade /stop
19. web/app.py — Flask: /api/status, /api/orders?slot=N, /api/paper*/..., /api/klines, /api/paper3/backtest
20. web/templates/base.html — dark theme layout, top nav
21. web/templates/paper.html (slot 1), paper2.html (slot 2), paper3.html (slot 3 + backtest panel)
22. web/templates/chart.html — LightweightCharts v4, sidebar toggles + indicator params
23. web/static/js/paper_charts.js — Canvas 2D: line chart vốn + bar chart profit
24. web/static/js/paper.js — UI logic: refresh 5s, hidden orders, computeOverrides(), CSV export
25. web/static/js/chart.js — LightweightCharts: 2 panel sync, markers P1/P2/P3, zoom fix
26. web/static/css/dashboard.css — dark theme, flex layout, mobile responsive
27. run_live.py — entry point: 3 threads (paper_loop, web, telegram)

LOGIC QUAN TRỌNG:
- Fee: fee = size × price × 0.0004 (taker). Entry fee trừ balance khi mở. Exit fee nằm trong profit.
- True net PNL = profit - entry_fee (mỗi lệnh)
- ATR trailing: chỉ dịch để bảo vệ thêm, không dịch ngược
- 4H boundary window: chỉ vào lệnh ±5 phút của giờ 3,7,11,15,19,23 UTC
- Circuit breaker M3: 3 thua → light CB 24h, drawdown >28%/14d → heavy CB 72h
- Hidden orders: tính lại PNL client-side bằng replay balance từ đầu
- Chart zoom fix: restoreAfterPoll KHÔNG reset barSpacing để giữ zoom user
- Markers: P1=arrow green/red, P2=circle cyan/orange, P3=square yellow/purple
```
