# -*- coding: utf-8 -*-
"""
Backtest chiến lược Method 3 (Exit B) trên dữ liệu lịch sử.
Replay klines 4H từ start_date→end_date, mô phỏng paper_loop logic.
"""

import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

FAPI_BASE = "https://fapi.binance.com"


def _fetch_klines_range(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Lấy toàn bộ klines từ start_ms đến end_ms (milliseconds timestamp)."""
    all_klines = []
    limit = 1500
    cur_start = start_ms
    while cur_start < end_ms:
        try:
            r = requests.get(
                f"{FAPI_BASE}/fapi/v1/klines",
                params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cur_start,
                    "endTime": end_ms,
                    "limit": limit,
                },
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"Fetch klines lỗi: {e}")
        if not data:
            break
        all_klines.extend(data)
        last_open_ms = int(data[-1][0])
        if last_open_ms <= cur_start or len(data) < limit:
            break
        cur_start = last_open_ms + 1
    return all_klines


def _klines_to_df(raw: list) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    tz = timezone(timedelta(hours=7))
    rows = []
    for k in raw:
        ts_utc = pd.Timestamp(int(k[0]), unit="ms", tz="UTC")
        ts_local = ts_utc.tz_convert(tz)
        rows.append({
            "timestamp": ts_local,
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]) if len(k) > 5 else 0,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index.name = "timestamp"
    return df


def run_backtest(
    symbol: str,
    start_dt: datetime,
    end_dt: datetime,
    initial_capital: float,
    leverage: float = 20.0,
    wallet_pct: float = 0.30,
    taker_fee: float = 0.0004,
) -> dict:
    """
    Chạy backtest Method 3 từ start_dt đến end_dt.
    Trả về dict: trades, final_balance, summary.
    """
    from strategy import add_indicators, long_entry, short_entry, size_and_margin, atr_1h_at_entry, compute_exit_candidates, pick_best_exit
    from strategy.indicators import add_indicators_m3
    from strategy.risk import m3_adx_zone, m3_streak_multiplier, m3_atr_multiplier
    from bot.paper_fees import linear_taker_fee_usdt
    from config import settings

    # Cần thêm warmup 80 nến 4H trước start_dt
    warmup_delta = timedelta(hours=4 * 80)
    fetch_start = start_dt - warmup_delta
    fetch_start_ms = int(fetch_start.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    # Fetch 4H klines
    raw_4h = _fetch_klines_range(symbol, "4h", fetch_start_ms, end_ms)
    if len(raw_4h) < 10:
        return {"error": "Không đủ dữ liệu 4H"}
    df_4h_full = _klines_to_df(raw_4h)

    # Fetch 1H klines for ATR
    raw_1h = _fetch_klines_range(symbol, "1h", fetch_start_ms, end_ms)
    df_1h_full = _klines_to_df(raw_1h) if raw_1h else pd.DataFrame()

    # Add indicators to full dataframes
    df_4h_ind = add_indicators(df_4h_full)
    df_4h_m3_ind = add_indicators_m3(
        df_4h_full,
        ema_trend_len=getattr(settings, "M3_EMA_TREND_LEN", 50),
        swing_lookback=getattr(settings, "M3_SWING_LOOKBACK", 6),
    )
    df_1h_ind = add_indicators(df_1h_full) if not df_1h_full.empty else pd.DataFrame()

    # Determine which 4H candle indices are within the actual backtest range
    start_ts = pd.Timestamp(start_dt).tz_convert(df_4h_ind.index.tz) if df_4h_ind.index.tz else pd.Timestamp(start_dt)
    valid_mask = df_4h_ind.index >= start_ts
    valid_indices = [i for i, v in enumerate(valid_mask) if v]

    if len(valid_indices) < 2:
        return {"error": "Không đủ nến 4H trong khoảng thời gian đã chọn"}

    # Simulation state
    balance = float(initial_capital)
    open_trade = None
    trades = []
    consecutive_losses = 0
    cb_heavy_until = None
    cb_light_until = None

    FOUR_H_BOUNDARY_HOURS = {3, 7, 11, 15, 19, 23}

    def _is_4h_boundary(ts):
        local_hour = ts.hour
        return local_hour in FOUR_H_BOUNDARY_HOURS

    def _f(v):
        try:
            x = float(v)
            return x if pd.notna(x) else None
        except (TypeError, ValueError):
            return None

    for i in valid_indices:
        if i < 3 or i >= len(df_4h_ind):
            continue

        row = df_4h_ind.iloc[i]
        row_closed = df_4h_ind.iloc[i - 1]
        prev_row_closed = df_4h_ind.iloc[i - 2]
        ts_4h = df_4h_ind.index[i]
        in_4h_window = _is_4h_boundary(ts_4h)

        # Slice 4H data up to current candle for exit/entry computation
        df_4h_slice = df_4h_full.iloc[max(0, i - 200):i + 1]
        df_4h_raw_slice = df_4h_slice

        # Slice 1H data up to current time
        if not df_1h_ind.empty:
            df_1h_slice = df_1h_ind[df_1h_ind.index <= ts_4h].iloc[-200:]
        else:
            df_1h_slice = pd.DataFrame()

        # --- Check exit if open trade ---
        if open_trade:
            entry = float(open_trade["entry_price"])
            size = float(open_trade["size"])
            side = open_trade["side"]

            exit_px_ref = float(row_closed["close"])
            exit_time_ts = df_4h_ind.index[i - 1]

            entry_4h_ts_val = open_trade.get("entry_4h_ts")
            allow_early_exit = entry_4h_ts_val is None or (df_4h_ind.index[i - 1] != entry_4h_ts_val)

            try:
                candidates = compute_exit_candidates(
                    open_trade,
                    pd.DataFrame(),  # no 1m in backtest
                    df_1h_slice,
                    df_4h_raw_slice,
                    prev_row_closed,
                    row_closed,
                    exit_px_ref,
                    exit_time_ts,
                    paper_use_4h_window=True,
                    in_4h_window=in_4h_window,
                    method="METHOD_3",
                    lookback_trades=15,
                    allow_early_exit=allow_early_exit,
                )
                best = pick_best_exit(candidates)
            except Exception:
                best = None

            if best is not None:
                best_time, best_pnl, best_px, reason = best
                capital_after = balance + best_pnl

                closed = {
                    "entry_time": open_trade.get("entry_time"),
                    "exit_time": best_time,
                    "entry_price": entry,
                    "exit_price": best_px,
                    "side": side,
                    "size": size,
                    "margin": open_trade.get("margin"),
                    "profit": best_pnl,
                    "capital_before": balance,
                    "capital_after": capital_after,
                    "exit_reason": reason,
                    "paper_slot": 3,
                }
                trades.append(closed)
                balance = capital_after
                open_trade = None

                # Update circuit breaker
                if best_pnl < 0:
                    consecutive_losses += 1
                    loss_pct = abs(best_pnl) / capital_after if capital_after > 0 else 0
                    now_utc = datetime.now(timezone.utc)
                    if loss_pct >= 0.10 or consecutive_losses >= 3:
                        cb_heavy_until = now_utc + timedelta(hours=24)
                        cb_light_until = None
                    elif loss_pct >= 0.05:
                        cb_light_until = now_utc + timedelta(hours=8)
                else:
                    consecutive_losses = 0
                    cb_heavy_until = None
                    cb_light_until = None

                continue

        # --- Check entry ---
        if open_trade is None and in_4h_window:
            # Circuit breaker check (use simulation time)
            sim_time_utc = ts_4h.astimezone(timezone.utc) if hasattr(ts_4h, 'astimezone') else datetime.now(timezone.utc)
            if cb_heavy_until and sim_time_utc < cb_heavy_until:
                continue
            if cb_light_until and sim_time_utc < cb_light_until:
                continue

            # Method 3 indicators
            try:
                row_m3 = df_4h_m3_ind.iloc[i - 1] if i - 1 < len(df_4h_m3_ind) else None
            except Exception:
                row_m3 = None

            sig_long = long_entry(prev_row_closed, row_closed)
            sig_short = short_entry(prev_row_closed, row_closed)

            if sig_long or sig_short:
                side = "LONG" if sig_long else "SHORT"
                m3_size_mult = 1.0

                if row_m3 is not None:
                    try:
                        adx_val = float(row_m3.get("ADX", 25.0) or 25.0)
                        allow, adx_size_mult = m3_adx_zone(adx_val)
                        if not allow:
                            continue
                        m3_size_mult = adx_size_mult

                        ema_trend_adx_thresh = getattr(settings, "M3_EMA_TREND_ADX_ABOVE", 30.0)
                        if adx_val > ema_trend_adx_thresh:
                            ema_trend_val = float(row_m3.get("EMA_TREND", 0.0) or 0.0)
                            close_val = float(row_m3.get("close", 0.0) or 0.0)
                            if ema_trend_val > 0 and close_val > 0:
                                if side == "LONG" and close_val < ema_trend_val:
                                    continue
                                if side == "SHORT" and close_val > ema_trend_val:
                                    continue

                        disagree_size = getattr(settings, "M3_SWING_DISAGREE_SIZE", 0.6)
                        higher_low = bool(row_m3.get("higher_low", False))
                        lower_high = bool(row_m3.get("lower_high", False))
                        if side == "LONG" and lower_high and not higher_low:
                            m3_size_mult = min(m3_size_mult, disagree_size)
                        elif side == "SHORT" and higher_low and not lower_high:
                            m3_size_mult = min(m3_size_mult, disagree_size)

                        streak_mult = m3_streak_multiplier(consecutive_losses)
                        m3_size_mult = m3_size_mult * streak_mult
                    except Exception:
                        pass

                entry_px = float(row_closed["close"])
                lev = float(leverage)
                wct = float(wallet_pct)
                size, margin, notional = size_and_margin(balance, entry_px, leverage=lev, wallet_pct=wct)
                if m3_size_mult < 1.0:
                    size = size * m3_size_mult
                    margin = margin * m3_size_mult
                    notional = notional * m3_size_mult
                if size <= 0 or margin > balance:
                    continue

                fee_in = linear_taker_fee_usdt(size, entry_px, taker_fee)
                balance_after_fee = balance - fee_in

                atr_now = atr_1h_at_entry(df_1h_slice, float(row_closed.get("ATR", 0)))
                entry_time_now = ts_4h.to_pydatetime() if hasattr(ts_4h, 'to_pydatetime') else datetime.now(timezone.utc)
                atr_mult_now = m3_atr_multiplier(entry_time_now)
                trail_dist = atr_now * atr_mult_now
                init_stop = entry_px - trail_dist if side == "LONG" else entry_px + trail_dist

                open_trade = {
                    "side": side,
                    "entry_time": entry_time_now,
                    "entry_price": entry_px,
                    "size": size,
                    "margin": margin,
                    "capital_before": balance,
                    "atr": atr_now,
                    "notional": notional,
                    "trail_stop": init_stop,
                    "last_sl_check": ts_4h,
                    "entry_rsi": _f(row_closed.get("RSI")),
                    "entry_ema_rsi": _f(row_closed.get("EMA_RSI")),
                    "entry_wma_rsi": _f(row_closed.get("WMA_RSI")),
                    "entry_4h_ts": df_4h_ind.index[i - 1],
                    "trading_method": "METHOD_3",
                    "paper_slot": 3,
                    "atr_multiplier_override": atr_mult_now,
                }
                balance = balance_after_fee

    # Force-close open trade at end
    if open_trade:
        open_trade["exit_time"] = end_dt
        open_trade["exit_price"] = open_trade["entry_price"]
        open_trade["profit"] = 0.0
        open_trade["exit_reason"] = "backtest_end"
        open_trade["capital_before"] = balance
        open_trade["capital_after"] = balance
        open_trade["paper_slot"] = 3
        trades.append(open_trade)
        open_trade = None

    # Summary
    n = len(trades)
    wins = sum(1 for t in trades if float(t.get("profit", 0)) > 0)
    total_pnl = sum(float(t.get("profit", 0)) for t in trades)

    return {
        "trades": trades,
        "final_balance": round(balance, 4),
        "total_trades": n,
        "wins": wins,
        "losses": n - wins,
        "winrate": round(wins / n * 100, 2) if n else 0.0,
        "total_pnl": round(total_pnl, 4),
    }
