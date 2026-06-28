# -*- coding: utf-8 -*-
"""
Backtest: dùng chiến lược vào/ra và quản lý vốn giống bot live,
chạy trên CSV local 4h + 1m. Vốn ban đầu 50 USD, quy tắc vào vốn giống bot.
Xuất: tổng hợp PnL/win rate, file CSV các lệnh (entry/exit, thời điểm, indicator lúc vào/ra).
"""

import sys
from pathlib import Path
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

# Config backtest (giống bot live)
DATA_DIR = Path(r"D:\Botbacktest")
CSV_4H = DATA_DIR / "BTC_4h_VN.csv"
CSV_1M = DATA_DIR / "BTC_1m_VN.csv"
OUTPUT_CSV = DATA_DIR / "backtest_trades.csv"
OUTPUT_SUMMARY = DATA_DIR / "backtest_summary.txt"

CAPITAL_START = 50.0
LEVERAGE = 20.0
WALLET_PCT = 0.30
TAKER_FEE = 0.0004
MAINT_MARGIN_RATE = 0.005
MAX_STOP_CAPITAL_PCT = 0.30
ATR_MULTIPLIER = 1.5
RSI_EARLY_EXIT = True
RSI_LONG_CUT = 42.0
RSI_SHORT_CUT = 58.0

# Cửa sổ vào/ra 4H: giờ đóng nến 4h (03,07,11,15,19,23) + 5 phút đầu
FOUR_H_BOUNDARY_HOURS = (3, 7, 11, 15, 19, 23)
FOUR_H_BOUNDARY_WINDOW_MINUTES = 15


def load_ohlc(path: Path, timeframe_minutes: int) -> pd.DataFrame:
    """Load CSV OHLC, chuẩn hóa cột và index datetime."""
    df = pd.read_csv(path)
    # Chuẩn hóa tên cột (Open Time, Open, High, Low, Close)
    rename = {
        "Open Time": "open_time",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    if "open_time" not in df.columns:
        raise ValueError(f"Missing Open Time in {path}")
    df["open"] = pd.to_numeric(df["open"], errors="coerce")
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    # Parse datetime (M/D/YYYY H:MM hoặc tương đương)
    df["dt"] = pd.to_datetime(df["open_time"])
    df = df.set_index("dt")
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close"]].astype(float)


def add_indicators_4h(df: pd.DataFrame):
    """Thêm RSI, EMA_RSI, WMA_RSI, ATR như strategy/indicators."""
    import pandas_ta as ta
    out = df.copy()
    out["RSI"] = ta.rsi(out["close"], length=14)
    out["EMA_RSI"] = ta.wma(out["RSI"], length=9)
    out["WMA_RSI"] = ta.wma(out["RSI"], length=45)
    out["ATR"] = ta.atr(out["high"], out["low"], out["close"], length=14)
    out["EMA"] = ta.ema(out["close"], length=20)
    out["WMA"] = ta.wma(out["close"], length=20)
    return out.dropna()


def _ensure_series(row):
    if isinstance(row, pd.DataFrame):
        return row.iloc[0]
    return row


def first_1m_after(ts_4h: pd.Timestamp, df_1m: pd.DataFrame):
    """Timestamp nến 1m đầu tiên sau ts_4h (giống helper trong test_chien_luoc_ATR_ver_6)."""
    if df_1m.empty:
        return None
    idx = df_1m.index.searchsorted(ts_4h, side="right")
    if idx >= len(df_1m):
        return None
    return df_1m.index[idx]


def in_4h_window(decision_time: pd.Timestamp) -> bool:
    """True nếu decision_time nằm trong window đầu sau đóng nến 4H (03,07,11,15,19,23)."""
    return decision_time.hour in FOUR_H_BOUNDARY_HOURS and decision_time.minute < FOUR_H_BOUNDARY_WINDOW_MINUTES


# Import strategy (sau khi có ROOT trong path). Thiết lập env để dùng đúng config, bao gồm early-exit.
def _import_strategy():
    import os
    os.environ.setdefault("RSI_EARLY_EXIT", "true")
    os.environ.setdefault("RSI_LONG_CUT", "42")
    os.environ.setdefault("RSI_SHORT_CUT", "58")
    os.environ.setdefault("MAX_STOP_CAPITAL_PCT", "0.30")
    os.environ.setdefault("ATR_MULTIPLIER", "1.5")
    from strategy import (
        long_entry,
        short_entry,
        long_exit,
        short_exit,
        long_exit_early,
        short_exit_early,
        size_and_margin,
        check_atr_trailing,
        max_loss_from_capital,
        limit_pnl_and_exit_price,
    )
    return {
        "long_entry": long_entry,
        "short_entry": short_entry,
        "long_exit": long_exit,
        "short_exit": short_exit,
        "long_exit_early": long_exit_early,
        "short_exit_early": short_exit_early,
        "size_and_margin": size_and_margin,
        "check_atr_trailing": check_atr_trailing,
        "max_loss_from_capital": max_loss_from_capital,
        "limit_pnl_and_exit_price": limit_pnl_and_exit_price,
    }


def run_backtest():
    strat = _import_strategy()
    long_entry = strat["long_entry"]
    short_entry = strat["short_entry"]
    long_exit = strat["long_exit"]
    short_exit = strat["short_exit"]
    long_exit_early = strat["long_exit_early"]
    short_exit_early = strat["short_exit_early"]
    size_and_margin = strat["size_and_margin"]
    check_atr_trailing = strat["check_atr_trailing"]
    max_loss_from_capital = strat["max_loss_from_capital"]
    limit_pnl_and_exit_price = strat["limit_pnl_and_exit_price"]

    # Load data
    df_4h_raw = load_ohlc(CSV_4H, 240)
    df_1m = load_ohlc(CSV_1M, 1)
    df_4h = add_indicators_4h(df_4h_raw)
    if len(df_4h) < 3:
        raise RuntimeError("Không đủ nến 4h sau khi thêm indicator.")

    balance = CAPITAL_START
    open_trade = None
    trades = []
    # Index 4h: bar i đóng tại index[i] + 4h
    period_4h = timedelta(hours=4)

    for i in range(2, len(df_4h)):
        row_closed = _ensure_series(df_4h.iloc[i])
        prev_row_closed = _ensure_series(df_4h.iloc[i - 1])
        bar_open_ts = df_4h.index[i]
        decision_time = bar_open_ts + period_4h  # thời điểm “đóng nến 4h”
        if not in_4h_window(decision_time):
            continue

        # ---------- EXIT ----------
        if open_trade is not None:
            entry = open_trade["entry_price"]
            size = open_trade["size"]
            side = open_trade["side"]
            max_loss = max_loss_from_capital(open_trade)
            candidates = []

            # 1m từ entry_time đến decision_time để ATR / liquidation
            entry_time = open_trade["entry_time"]
            mask = (df_1m.index > entry_time) & (df_1m.index <= decision_time)
            df_1m_slice = df_1m.loc[mask]
            margin = open_trade["margin"]
            notional = open_trade["notional"]
            maint = MAINT_MARGIN_RATE * notional
            ot_copy = dict(open_trade)

            for ts_1m, m1 in df_1m_slice.iterrows():
                if side == "LONG":
                    liq_px = entry + (maint - margin) / size
                    if m1["low"] <= liq_px:
                        candidates.append((ts_1m, -margin, liq_px, "LIQUIDATION"))
                        break
                else:
                    liq_px = entry - (maint - margin) / size
                    if m1["high"] >= liq_px:
                        candidates.append((ts_1m, -margin, liq_px, "LIQUIDATION"))
                        break
                pnl_raw, exit_px = check_atr_trailing(ot_copy, m1)
                if pnl_raw is not None:
                    pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                    if px_lim is not None:
                        exit_px = px_lim
                    fee_out = size * exit_px * TAKER_FEE
                    candidates.append((ts_1m, pnl_lim - fee_out, exit_px, "ATR_TRAIL"))
                    break

            exit_px_ref = float(row_closed["close"])
            if long_exit(prev_row_closed, row_closed) if side == "LONG" else short_exit(prev_row_closed, row_closed):
                pnl_raw = (exit_px_ref - entry) * size if side == "LONG" else (entry - exit_px_ref) * size
                pnl_lim, px_lim = limit_pnl_and_exit_price(side, entry, size, pnl_raw, max_loss)
                exit_px = px_lim if px_lim is not None else exit_px_ref
                fee_out = size * exit_px * TAKER_FEE
                candidates.append((decision_time, pnl_lim - fee_out, exit_px, "4H_EXIT"))

            # Early exit RSI: giống logic trong test_chien_luoc_ATR_ver_6, thoát tại nến 1m đầu sau decision_time
            sig_early = long_exit_early(prev_row_closed, row_closed) if side == "LONG" else short_exit_early(prev_row_closed, row_closed)
            if sig_early:
                ts1 = first_1m_after(decision_time, df_1m)
                if ts1 is not None:
                    raw = df_1m.loc[ts1]["open"]
                    exit_px_early = float(raw)
                    pnl_raw_early = (exit_px_early - entry) * size if side == "LONG" else (entry - exit_px_early) * size
                    pnl_limited, px_limited = limit_pnl_and_exit_price(
                        side, entry, size, pnl_raw_early, max_loss
                    )
                    if px_limited is not None:
                        exit_px_early = px_limited
                    fee_out = size * exit_px_early * TAKER_FEE
                    pnl_net_early = pnl_limited - fee_out
                    candidates.append((ts1, pnl_net_early, exit_px_early, "4H_EARLY_EXIT"))

            if candidates:
                best_time, best_pnl, best_px, reason = min(candidates, key=lambda x: (x[0], -x[1]))
                capital_after = balance + best_pnl
                def _f(v):
                    try:
                        x = float(v)
                        return x if pd.notna(x) else None
                    except (TypeError, ValueError):
                        return None
                closed = {
                    "entry_time": open_trade["entry_time"],
                    "exit_time": best_time,
                    "entry_price": entry,
                    "exit_price": best_px,
                    "side": side,
                    "size": open_trade["size"],
                    "margin": open_trade["margin"],
                    "profit": best_pnl,
                    "capital_before": balance,
                    "capital_after": capital_after,
                    "exit_reason": reason,
                    "entry_rsi": open_trade.get("entry_rsi"),
                    "entry_ema_rsi": open_trade.get("entry_ema_rsi"),
                    "entry_wma_rsi": open_trade.get("entry_wma_rsi"),
                    "exit_rsi": _f(row_closed.get("RSI")),
                    "exit_ema_rsi": _f(row_closed.get("EMA_RSI")),
                    "exit_wma_rsi": _f(row_closed.get("WMA_RSI")),
                }
                trades.append(closed)
                balance = capital_after
                open_trade = None
            continue

        # ---------- ENTRY ----------
        sig_long = long_entry(prev_row_closed, row_closed)
        sig_short = short_entry(prev_row_closed, row_closed)
        if not (sig_long or sig_short):
            continue

        side = "LONG" if sig_long else "SHORT"

        # Entry tại nến 1m đầu tiên sau thời điểm decision_time (giống test_chien_luoc_ATR_ver_6)
        ts_1m = first_1m_after(decision_time, df_1m)
        if ts_1m is None:
            continue
        entry_px = float(df_1m.loc[ts_1m]["open"])

        size, margin, notional = size_and_margin(
            balance, entry_px, leverage=LEVERAGE, wallet_pct=WALLET_PCT
        )
        if size <= 0 or margin > balance:
            continue
        fee_in = size * entry_px * TAKER_FEE
        balance_after_fee = balance - fee_in
        atr_now = row_closed["ATR"]
        trail_dist = atr_now * ATR_MULTIPLIER
        init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist

        def _f(v):
            try:
                x = float(v)
                return x if pd.notna(x) else None
            except (TypeError, ValueError):
                return None

        open_trade = {
            "side": side,
            "entry_time": ts_1m,
            "entry_price": entry_px,
            "size": size,
            "margin": margin,
            "capital_before": balance,
            "atr": atr_now,
            "notional": notional,
            "trail_stop": init_stop,
            "entry_rsi": _f(row_closed.get("RSI")),
            "entry_ema_rsi": _f(row_closed.get("EMA_RSI")),
            "entry_wma_rsi": _f(row_closed.get("WMA_RSI")),
        }
        balance = balance_after_fee

    # Đóng lệnh còn mở ở cuối dữ liệu (mark to market)
    if open_trade is not None:
        last_close = float(df_4h["close"].iloc[-1])
        entry = open_trade["entry_price"]
        size = open_trade["size"]
        side = open_trade["side"]
        pnl_raw = (last_close - entry) * size if side == "LONG" else (entry - last_close) * size
        fee_out = size * last_close * TAKER_FEE
        best_pnl = pnl_raw - fee_out
        capital_after = balance + best_pnl
        row_closed = _ensure_series(df_4h.iloc[-1])
        def _f(v):
            try:
                x = float(v)
                return x if pd.notna(x) else None
            except (TypeError, ValueError):
                return None
        trades.append({
            "entry_time": open_trade["entry_time"],
            "exit_time": df_4h.index[-1] + period_4h,
            "entry_price": entry,
            "exit_price": last_close,
            "side": side,
            "size": size,
            "margin": open_trade["margin"],
            "profit": best_pnl,
            "capital_before": balance,
            "capital_after": capital_after,
            "exit_reason": "END_OF_DATA",
            "entry_rsi": open_trade.get("entry_rsi"),
            "entry_ema_rsi": open_trade.get("entry_ema_rsi"),
            "entry_wma_rsi": open_trade.get("entry_wma_rsi"),
            "exit_rsi": _f(row_closed.get("RSI")),
            "exit_ema_rsi": _f(row_closed.get("EMA_RSI")),
            "exit_wma_rsi": _f(row_closed.get("WMA_RSI")),
        })
        balance = capital_after

    return balance, trades


def main():
    print("Loading 4h and 1m CSV...")
    final_balance, trades = run_backtest()

    # Tổng hợp
    n = len(trades)
    total_pnl = final_balance - CAPITAL_START
    wins = sum(1 for t in trades if t["profit"] > 0)
    losses = sum(1 for t in trades if t["profit"] <= 0)
    win_rate = (wins / n * 100) if n else 0
    pnl_pct = (total_pnl / CAPITAL_START * 100) if CAPITAL_START else 0

    summary_lines = [
        "========== BACKTEST SUMMARY ==========",
        f"Von ban dau:     {CAPITAL_START:.2f} USD",
        f"Von cuoi:        {final_balance:.2f} USD",
        f"Tong PnL:        {total_pnl:.2f} USD ({pnl_pct:+.2f}%)",
        f"So lenh:         {n}",
        f"Thang:           {wins}",
        f"Thua:            {losses}",
        f"Ti le win:       {win_rate:.1f}%",
        "=======================================",
    ]
    summary_lines_utf8 = [
        "========== BACKTEST SUMMARY ==========",
        f"Vốn ban đầu:      {CAPITAL_START:.2f} USD",
        f"Vốn cuối:        {final_balance:.2f} USD",
        f"Tổng PnL:        {total_pnl:.2f} USD ({pnl_pct:+.2f}%)",
        f"Số lệnh:         {n}",
        f"Thắng:           {wins}",
        f"Thua:            {losses}",
        f"Tỉ lệ win:       {win_rate:.1f}%",
        "=======================================",
    ]
    summary_text = "\n".join(summary_lines)
    summary_text_utf8 = "\n".join(summary_lines_utf8)
    print(summary_text)

    # Ghi file summary (UTF-8, tiếng Việt)
    OUTPUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_SUMMARY, "w", encoding="utf-8") as f:
        f.write(summary_text_utf8)

    # Xuất CSV lệnh
    if trades:
        rows = []
        for t in trades:
            rows.append({
                "symbol": "BTCUSDT",
                "entry_time": t["entry_time"],
                "exit_time": t["exit_time"],
                "side": t["side"],
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "profit": t["profit"],
                "pct_pnl_margin": (t["profit"] / t["margin"] * 100) if t["margin"] else None,
                "pct_pnl_capital": (t["profit"] / t["capital_before"] * 100) if t["capital_before"] else None,
                "capital_after": t["capital_after"],
                "exit_reason": t["exit_reason"],
                "entry_rsi": t.get("entry_rsi"),
                "entry_ema_rsi": t.get("entry_ema_rsi"),
                "entry_wma_rsi": t.get("entry_wma_rsi"),
                "exit_rsi": t.get("exit_rsi"),
                "exit_ema_rsi": t.get("exit_ema_rsi"),
                "exit_wma_rsi": t.get("exit_wma_rsi"),
            })
        out_df = pd.DataFrame(rows)
        out_df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
        print(f"\nExported {len(rows)} trades to: {OUTPUT_CSV}")
    else:
        print("\nNo trades to export.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
