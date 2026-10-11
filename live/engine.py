# -*- coding: utf-8 -*-
"""
Engine trade thật: mỗi "bot" = (tài khoản sàn × cặp coin × chiến lược PP1–PP4).

Mỗi vòng (LOOP_INTERVAL_SEC):
  1. Tải nến 4H/1H/1m cho từng cặp coin đang chạy (API công khai, dùng chung giữa các bot).
  2. Đối chiếu vị thế trên sàn: lệnh của bot đã bị đóng ngoài bot (stop trên sàn, thanh lý, đóng tay)
     → ghi sổ theo giá khớp thật.
  3. Chạy đúng logic paper (bot/slot_engine.step_slot) với hook đặt lệnh thật.
  4. Đồng bộ lệnh STOP_MARKET dự phòng trên sàn (theo trailing hoặc hard stop).
  5. Báo cáo Telegram mỗi giờ.

An toàn:
  - Công tắc tổng (mặc định TẮT) + công tắc từng tài khoản + trạng thái từng bot: khi tắt chỉ chặn
    MỞ lệnh mới; lệnh đang mở vẫn được quản lý thoát như bình thường.
  - Mỗi tài khoản chỉ 1 bot / cặp coin; bot không vào lệnh nếu cặp đó đã có vị thế không do bot mở.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from datetime import datetime, timezone

import pandas as pd

from config import settings
from bot.paper_fees import linear_taker_fee_usdt
from bot.slot_engine import MarketContext, step_slot, update_circuit_breaker, is_4h_boundary_window, _f
from exchange.binance_futures import BinanceFuturesTrader, BinanceAPIError, ENV_LABELS
from strategy import add_indicators
from strategy.risk import max_loss_from_capital
from strategy.strategies.registry import METHOD_3, METHOD_4
from live import store

_tz_app = getattr(settings, "GMT7", timezone.utc)

MAX_TRADES_KEPT = 3000
ENTRY_MAX_ATTEMPTS = 3
ENTRY_RETRY_SEC = 20
STOP_UPDATE_MIN_SEC = 20
STOP_UPDATE_MIN_MOVE = 0.0005  # 0.05% giá
MISSING_CONFIRM_TICKS = 2
ERROR_NOTIFY_EVERY_SEC = 600


def make_trader(account: dict, api_key: str, api_secret: str):
    if account.get("exchange", "binance_usdm") == "binance_usdm":
        return BinanceFuturesTrader(api_key, api_secret, env=account.get("env", "mainnet"))
    raise ValueError(f"Sàn {account.get('exchange')} chưa được hỗ trợ")


def _now():
    return datetime.now(_tz_app)


def _fmt_px(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v >= 1000:
        return f"{v:,.2f}"
    if v >= 1:
        return f"{v:.4f}"
    return f"{v:.6f}"


class LiveEngine:
    def __init__(self, market_client=None, trader_factory=make_trader, notifier=None):
        if market_client is None:
            from exchange.binance_client import BinanceClient
            market_client = BinanceClient()
        self.market = market_client
        self.trader_factory = trader_factory
        if notifier is None:
            from live import telegram_ctl
            notifier = telegram_ctl
        self.notifier = notifier
        self._traders = {}
        self._positions = {}        # acc_id -> list | None (lỗi) — làm mới mỗi vòng
        self._missing = {}          # bot_id -> số vòng liên tiếp sàn không còn vị thế
        self._err_last = {}         # key -> time
        self._commands = queue.Queue()
        self._last_report_hour = None
        self._last_save = 0.0
        self.last_tick_at = None
        self.last_error = None
        self.market_cache = {}      # symbol -> {"price", "t"}

    # ---------------------------------------------------------- tiện ích
    def trader_for(self, acc_id: str):
        acc = store.get_account(acc_id)
        if not acc or not acc.get("has_keys"):
            return None
        sig = (acc.get("api_key_enc"), acc.get("api_secret_enc"), acc.get("env"), acc.get("exchange"))
        cached = self._traders.get(acc_id)
        if cached and cached[0] == sig:
            return cached[1]
        key, secret = store.account_credentials(acc_id)
        if not key or not secret:
            return None
        tr = self.trader_factory(acc, key, secret)
        self._traders[acc_id] = (sig, tr)
        return tr

    def positions_for(self, acc_id: str):
        """Vị thế trên sàn của tài khoản (cache trong vòng). None = gọi API lỗi."""
        if acc_id in self._positions:
            return self._positions[acc_id]
        tr = self.trader_for(acc_id)
        pos = None
        if tr is not None:
            try:
                pos = tr.get_positions()
            except Exception as e:
                self._error(f"pos:{acc_id}", f"Không đọc được vị thế tài khoản {self._acc_name(acc_id)}: {e}")
        self._positions[acc_id] = pos
        return pos

    def _find_pos(self, acc_id, symbol, side=None):
        pos = self.positions_for(acc_id)
        if pos is None:
            return None, False
        for p in pos:
            if p["symbol"] == symbol and (side is None or p["side"] == side):
                return p, True
        return None, True

    @staticmethod
    def _acc_name(acc_id):
        a = store.get_account(acc_id) or {}
        return a.get("name") or acc_id

    def _tag(self, bot: dict) -> str:
        return f"[REAL {bot.get('name') or bot['symbol']}]"

    def _notify(self, bot: dict, kind: str, text: str):
        try:
            self.notifier.broadcast(kind, text, tg_ids=(bot or {}).get("telegram_ids") or None)
        except Exception:
            pass

    def _error(self, key: str, text: str, bot: dict = None):
        self.last_error = f"{_now():%H:%M:%S} {text}"
        print("[LIVE]", text)
        now = time.time()
        if now - self._err_last.get(key, 0) < ERROR_NOTIFY_EVERY_SEC:
            return
        self._err_last[key] = now
        store.add_event("error", text, bot_id=(bot or {}).get("id"))
        self._notify(bot, "errors", f"⚠️ {text}")

    # ------------------------------------------------------------ lệnh từ web / Telegram
    def request_close(self, bot_id: str, by: str = "web"):
        self._commands.put(("close", bot_id, by))

    def request_close_all(self, by: str = "web"):
        store.set_real_trading_enabled(False, by=by)
        for b in store.list_bots():
            if store.bot_state(b["id"]).get("open_trade"):
                self._commands.put(("close", b["id"], by))

    def _process_commands(self, markets: dict):
        while True:
            try:
                cmd, bot_id, by = self._commands.get_nowait()
            except queue.Empty:
                return
            bot = store.get_bot(bot_id)
            if not bot or cmd != "close":
                continue
            try:
                self._manual_close(bot, by, markets.get(bot["symbol"]))
            except Exception as e:
                self._error(f"close:{bot_id}", f"{self._tag(bot)} Đóng lệnh thủ công lỗi: {e}", bot)

    # ---------------------------------------------------------------- vòng lặp
    def run(self, stop_event: threading.Event = None):
        print("[LIVE] Engine trade thật đã khởi động (công tắc tổng: %s)" % ("BẬT" if store.real_trading_enabled() else "TẮT"))
        while stop_event is None or not stop_event.is_set():
            try:
                self.tick()
            except Exception as e:
                self.last_error = f"{_now():%H:%M:%S} {e}"
                traceback.print_exc()
            time.sleep(settings.LOOP_INTERVAL_SEC)

    def _load_market(self, symbol: str, in_window: bool):
        df_4h_raw = self.market.get_klines_4h(symbol, limit=200)
        df_1m = self.market.get_klines_1m(symbol, limit=480)
        df_1h = pd.DataFrame()
        try:
            df_1h_raw = self.market.get_klines_1h(symbol, limit=200)
            if not df_1h_raw.empty:
                df_1h = add_indicators(df_1h_raw)
        except Exception:
            pass
        if df_4h_raw is None or df_4h_raw.empty or len(df_4h_raw) < 20:
            return None
        mkt = MarketContext(df_4h_raw, df_1m, df_1h, in_window)
        if not mkt.ok:
            return None
        self.market_cache[symbol] = {"price": mkt.last_price(), "t": _now().isoformat()}
        return mkt

    def tick(self):
        self._positions = {}
        bots = store.list_bots()
        active = [b for b in bots if b.get("status") in ("running", "paused") or store.bot_state(b["id"]).get("open_trade")]
        in_window = is_4h_boundary_window()
        markets = {}
        for sym in sorted({b["symbol"] for b in active}):
            try:
                markets[sym] = self._load_market(sym, in_window)
            except Exception as e:
                self._error(f"mkt:{sym}", f"Không tải được nến {sym}: {e}")
                markets[sym] = None

        self._process_commands(markets)

        for bot in active:
            mkt = markets.get(bot["symbol"])
            if mkt is None:
                continue
            try:
                with store.lock():
                    self._step_bot(bot, mkt)
            except Exception as e:
                traceback.print_exc()
                self._error(f"step:{bot['id']}", f"{self._tag(bot)} Lỗi vòng lặp: {e}", bot)

        now = time.time()
        if now - self._last_save > 15:
            store.save_state()
            self._last_save = now
        self.last_tick_at = _now().isoformat()
        self._maybe_hourly_report(bots)

    # ------------------------------------------------------------ một bot
    def _step_bot(self, bot: dict, mkt: MarketContext):
        st = store.bot_state(bot["id"])
        if st.get("open_trade"):
            if self._reconcile(bot, st, mkt):
                return
        step_slot(bot["id"], bot["method"], self._slot_api(bot, st), mkt)
        if st.get("open_trade"):
            self._sync_stop(bot, st["open_trade"], mkt.last_price())

    def _slot_api(self, bot: dict, st: dict) -> dict:
        cbs = st["cb"]

        def get_status():
            s = bot.get("status", "stopped")
            if s == "stopped" and st.get("open_trade"):
                return "paused"  # bot dừng nhưng còn lệnh → vẫn quản lý thoát
            return s

        def set_open(v):
            st["open_trade"] = v

        def append_trade(t):
            st["trades"].append(t)
            del st["trades"][:-MAX_TRADES_KEPT]

        def set_last(t):
            st["last_trade"] = t

        def set_balance(v):
            st["balance"] = float(v)

        return {
            "get_status": get_status,
            "get_balance": lambda: float(st.get("balance") or 0),
            "set_balance": set_balance,
            "get_open": lambda: st.get("open_trade"),
            "set_open": set_open,
            "append_trade": append_trade,
            "set_last": set_last,
            "get_lev": lambda: float(bot["leverage"]),
            "get_wct": lambda: float(bot["wallet_pct"]),
            "lookback": lambda: min(max(int(getattr(settings, "LOOKBACK_TRADES", 15)), 1), 200),
            "cb": {
                "get_losses": lambda: int(cbs.get("losses") or 0),
                "set_losses": lambda v: cbs.__setitem__("losses", int(v)),
                "get_light": lambda: cbs.get("light_until"),
                "set_light": lambda dt: cbs.__setitem__("light_until", dt),
                "get_heavy": lambda: cbs.get("heavy_until"),
                "set_heavy": lambda dt: cbs.__setitem__("heavy_until", dt),
                "get_trades": lambda: st["trades"],
            },
            "execute_open": lambda payload: self._execute_open(bot, st, payload),
            "execute_close": lambda ot, best: self._execute_close(bot, st, ot, best),
            "on_opened": lambda ot: self._on_opened(bot, st, ot),
            "on_closed": lambda closed: self._on_closed(bot, st, closed),
        }

    # ------------------------------------------------------------- mở lệnh
    def _entry_gate(self, bot: dict, st: dict, payload: dict):
        """None = được phép; ngược lại là lý do chặn."""
        if not store.real_trading_enabled():
            return "công tắc trade thật đang TẮT"
        acc = store.get_account(bot["account_id"])
        if not acc:
            return "tài khoản sàn đã bị xoá"
        if not acc.get("enabled"):
            return f"tài khoản {acc.get('name')} đang TẮT"
        if not acc.get("has_keys"):
            return f"tài khoản {acc.get('name')} chưa nhập API key"
        return None

    def _execute_open(self, bot: dict, st: dict, payload: dict):
        side = payload["side"]
        symbol = bot["symbol"]
        candle = str(payload.get("entry_4h_ts"))
        eb = st.get("entry_block") or {}
        if eb.get("candle") != candle:
            eb = {"candle": candle, "attempts": 0, "last": 0, "notified": False}
            st["entry_block"] = eb
        if eb.get("done"):
            return None

        reason = self._entry_gate(bot, st, payload)
        if reason:
            if not eb.get("notified"):
                eb["notified"] = True
                msg = (f"📡 {self._tag(bot)} Tín hiệu {side} {symbol} @ {_fmt_px(payload['entry_price'])} "
                       f"— KHÔNG đặt lệnh vì {reason}.")
                store.add_event("signal", msg, bot["id"])
                self._notify(bot, "trades", msg)
            return None

        if eb["attempts"] >= ENTRY_MAX_ATTEMPTS or time.time() - eb.get("last", 0) < ENTRY_RETRY_SEC:
            return None
        eb["attempts"] += 1
        eb["last"] = time.time()

        tr = self.trader_for(bot["account_id"])
        if tr is None:
            self._error(f"open:{bot['id']}", f"{self._tag(bot)} Không tạo được kết nối sàn (thiếu API key?)", bot)
            return None

        existing, ok = self._find_pos(bot["account_id"], symbol)
        if not ok:
            return None
        if existing:
            eb["done"] = True
            self._error(f"exist:{bot['id']}", f"{self._tag(bot)} Bỏ qua tín hiệu {side}: tài khoản đang có vị thế "
                        f"{existing['side']} {symbol} không do bot mở.", bot)
            return None

        px = float(payload["entry_price"])
        lev = int(bot["leverage"])
        rules = {}
        qty = float(payload["size"])
        try:
            rules = tr.symbol_rules(symbol)
            qty = tr.round_qty(symbol, float(payload["size"]))
            if qty < rules["min_qty"] or qty * px < rules["min_notional"]:
                eb["done"] = True
                self._error(f"small:{bot['id']}", f"{self._tag(bot)} Bỏ qua tín hiệu {side}: khối lượng {qty} "
                            f"(~{qty * px:.2f} USDT) dưới mức tối thiểu của sàn ({rules['min_notional']} USDT). "
                            f"Tăng vốn / đòn bẩy / % vốn mỗi lệnh.", bot)
                return None
            bal = tr.get_balance()
            need = qty * px / lev
            if bal["available"] < need * 1.02:
                eb["done"] = True
                self._error(f"margin:{bot['id']}", f"{self._tag(bot)} Bỏ qua tín hiệu {side}: số dư khả dụng "
                            f"{bal['available']:.2f} USDT < margin cần {need:.2f} USDT.", bot)
                return None
            tr.set_leverage(symbol, lev)
            res = tr.market_order(symbol, side, qty)
        except BinanceAPIError as e:
            self._error(f"open:{bot['id']}", f"{self._tag(bot)} Đặt lệnh {side} {symbol} lỗi: {e}", bot)
            return None
        except Exception as e:
            # Lỗi mạng: lệnh có thể đã khớp → kiểm tra lại vị thế, nếu có thì nhận về
            self._positions.pop(bot["account_id"], None)
            p, ok = self._find_pos(bot["account_id"], symbol, side)
            if ok and p and abs(p["qty"] - qty) <= max(rules.get("step", 0), qty * 0.001):
                res = {"order_id": None, "avg_price": p["entry_price"], "qty": p["qty"], "fee": None, "realized": None}
            else:
                self._error(f"open:{bot['id']}", f"{self._tag(bot)} Đặt lệnh {side} {symbol} lỗi mạng: {e}", bot)
                return None

        filled = float(res.get("qty") or 0)
        if filled <= 0:
            self._error(f"open:{bot['id']}", f"{self._tag(bot)} Lệnh {side} {symbol} không khớp (qty=0).", bot)
            return None
        eb["done"] = True
        fill_px = float(res.get("avg_price") or px) or px
        fee_in = res.get("fee")
        if fee_in is None:
            fee_in = linear_taker_fee_usdt(filled, fill_px, float(settings.TAKER_FEE))

        shift = fill_px - px
        payload = dict(payload)
        payload.update({
            "signal_price": px,
            "entry_price": fill_px,
            "trail_stop": float(payload["trail_stop"]) + shift,
            "size": filled,
            "notional": filled * fill_px,
            "margin": filled * fill_px / lev,
            "entry_fee": float(fee_in),
            "entry_order_id": res.get("order_id"),
            "entry_order_ms": int(time.time() * 1000) - 60_000,
            "exchange_stop": None,
            "symbol": symbol,
            "account_id": bot["account_id"],
            "real": True,
        })
        return {"payload": payload, "fee_in": float(fee_in)}

    def _on_opened(self, bot: dict, st: dict, ot: dict):
        self._missing.pop(bot["id"], None)
        store.save_state()
        side = ot["side"]
        msg = (f"🟢 {self._tag(bot)} MỞ {side} {bot['symbol']} @ {_fmt_px(ot['entry_price'])}\n"
               f"Khối lượng: {ot['size']} | Margin ~{ot['margin']:.2f} USDT | x{bot['leverage']}\n"
               f"Trailing stop: {_fmt_px(ot.get('trail_stop'))} | Phí vào: {ot.get('entry_fee', 0):.4f} USDT\n"
               f"Chiến lược: PP{bot['method']} | Vốn bot: {st['balance']:.2f} USDT")
        store.add_event("open", msg, bot["id"])
        self._notify(bot, "trades", msg)
        self._sync_stop(bot, ot, float(ot["entry_price"]), force=True)
        store.save_state()

    # ------------------------------------------------------------- đóng lệnh
    def _close_on_exchange(self, bot: dict, ot: dict):
        """Đóng vị thế của bot bằng lệnh MARKET reduce-only. Trả kết quả khớp hoặc ném lỗi."""
        tr = self.trader_for(bot["account_id"])
        if tr is None:
            raise RuntimeError("không có kết nối sàn (API key?)")
        res = tr.market_order(bot["symbol"], ot["side"], float(ot["size"]), reduce_only=True)
        try:
            tr.cancel_stop(bot["symbol"], ot.get("exchange_stop"))
            ot["exchange_stop"] = None
        except Exception as e:
            self._error(f"cancel:{bot['id']}", f"{self._tag(bot)} Đã đóng lệnh nhưng KHÔNG huỷ được stop trên sàn — "
                        f"vào Binance huỷ tay lệnh stop {bot['symbol']}: {e}", bot)
        return res

    @staticmethod
    def _profit_from_fill(ot: dict, res: dict):
        entry = float(ot["entry_price"])
        qty = float(res.get("qty") or ot["size"])
        exit_px = float(res.get("avg_price") or 0)
        realized = res.get("realized")
        if realized is None:
            realized = (exit_px - entry) * qty if ot["side"] == "LONG" else (entry - exit_px) * qty
        fee_out = res.get("fee")
        if fee_out is None:
            fee_out = linear_taker_fee_usdt(qty, exit_px, float(settings.TAKER_FEE))
        return exit_px, float(realized) - float(fee_out), float(fee_out)

    def _execute_close(self, bot: dict, st: dict, ot: dict, best):
        best_time, best_pnl, best_px, reason = best
        try:
            res = self._close_on_exchange(bot, ot)
        except BinanceAPIError as e:
            if e.code == -2022:  # ReduceOnly bị từ chối: vị thế đã mất → để _reconcile ghi sổ
                self._missing[bot["id"]] = MISSING_CONFIRM_TICKS
                return None
            self._error(f"close:{bot['id']}", f"{self._tag(bot)} Đóng lệnh ({reason}) lỗi: {e} — sẽ thử lại.", bot)
            return None
        except Exception as e:
            self._error(f"close:{bot['id']}", f"{self._tag(bot)} Đóng lệnh ({reason}) lỗi: {e} — sẽ thử lại.", bot)
            return None
        exit_px, profit, fee_out = self._profit_from_fill(ot, res)
        if exit_px <= 0:
            exit_px = float(best_px)
        return {
            "exit_price": exit_px,
            "profit": profit,
            "exit_time": _now(),
            "exit_reason": reason,
            "extra": {"signal_exit_price": best_px, "signal_pnl": best_pnl, "exit_fee": fee_out,
                      "entry_fee": ot.get("entry_fee"), "exit_order_id": res.get("order_id"),
                      "symbol": bot["symbol"], "real": True},
        }

    def _on_closed(self, bot: dict, st: dict, closed: dict):
        self._missing.pop(bot["id"], None)
        st.pop("stop_fail", None)
        store.save_state()
        pnl = float(closed.get("profit") or 0)
        margin = float(closed.get("margin") or 0) or 1
        icon = "✅" if pnl >= 0 else "🔴"
        msg = (f"{icon} {self._tag(bot)} ĐÓNG {closed['side']} {bot['symbol']} @ {_fmt_px(closed['exit_price'])} "
               f"(vào {_fmt_px(closed['entry_price'])})\n"
               f"PnL: {pnl:+.4f} USDT ({pnl / margin * 100:+.2f}% margin) | Lý do: {closed.get('exit_reason')}\n"
               f"Vốn bot: {closed.get('capital_after', 0):.2f} USDT")
        store.add_event("close", msg, bot["id"])
        self._notify(bot, "trades", msg)

    def _book_external_close(self, bot: dict, st: dict, ot: dict, exit_px: float, profit: float, reason: str, extra: dict, row_closed=None):
        """Ghi sổ lệnh đã đóng ngoài step_slot (đóng trên sàn / đóng tay) — cùng định dạng closed của step_slot."""
        balance = float(st.get("balance") or 0)
        capital_after = balance + profit
        closed = {
            "entry_time": ot.get("entry_time"),
            "exit_time": _now(),
            "entry_price": float(ot["entry_price"]),
            "exit_price": exit_px,
            "side": ot["side"],
            "size": ot.get("size"),
            "margin": ot.get("margin"),
            "profit": profit,
            "capital_before": balance,
            "capital_after": capital_after,
            "exit_reason": reason,
            "entry_rsi": ot.get("entry_rsi"),
            "entry_ema_rsi": ot.get("entry_ema_rsi"),
            "entry_wma_rsi": ot.get("entry_wma_rsi"),
            "exit_rsi": _f(row_closed.get("RSI")) if row_closed is not None else None,
            "exit_ema_rsi": _f(row_closed.get("EMA_RSI")) if row_closed is not None else None,
            "exit_wma_rsi": _f(row_closed.get("WMA_RSI")) if row_closed is not None else None,
            "paper_slot": bot["id"],
        }
        closed.update(extra or {})
        st["open_trade"] = None
        st["last_trade"] = closed
        st["trades"].append(closed)
        del st["trades"][:-MAX_TRADES_KEPT]
        st["balance"] = capital_after
        if bot["method"] in (METHOD_3, METHOD_4):
            api = self._slot_api(bot, st)
            try:
                update_circuit_breaker(api["cb"], profit, capital_after)
            except Exception:
                pass
        self._on_closed(bot, st, closed)

    def _manual_close(self, bot: dict, by: str, mkt):
        with store.lock():
            st = store.bot_state(bot["id"])
            ot = st.get("open_trade")
            if not ot:
                return
            res = self._close_on_exchange(bot, ot)
            exit_px, profit, fee_out = self._profit_from_fill(ot, res)
            if exit_px <= 0 and mkt is not None:
                exit_px = mkt.last_price()
            self._book_external_close(
                bot, st, ot, exit_px, profit, f"MANUAL_{by.upper()}",
                {"exit_fee": fee_out, "entry_fee": ot.get("entry_fee"), "exit_order_id": res.get("order_id"),
                 "symbol": bot["symbol"], "real": True},
                mkt.row_closed if mkt is not None else None,
            )

    def _reconcile(self, bot: dict, st: dict, mkt: MarketContext) -> bool:
        """Sàn không còn vị thế của bot (stop trên sàn khớp / thanh lý / đóng tay) → ghi sổ. True nếu đã ghi."""
        ot = st["open_trade"]
        p, ok = self._find_pos(bot["account_id"], bot["symbol"], ot["side"])
        if not ok:
            return False
        if p is not None:
            self._missing.pop(bot["id"], None)
            return False
        n = self._missing.get(bot["id"], 0) + 1
        self._missing[bot["id"]] = n
        if n < MISSING_CONFIRM_TICKS:
            return False

        tr = self.trader_for(bot["account_id"])
        close_side = "SELL" if ot["side"] == "LONG" else "BUY"
        realized = fee = qty = quote = 0.0
        fee_known = True
        try:
            fills = tr.user_trades_since(bot["symbol"], int(ot.get("entry_order_ms") or 0)) if tr else []
        except Exception:
            fills = []
        for t in fills:
            if t.get("side") != close_side or (ot.get("entry_order_id") and t.get("orderId") == ot.get("entry_order_id")):
                continue
            q = float(t.get("qty") or 0)
            qty += q
            quote += q * float(t.get("price") or 0)
            realized += float(t.get("realizedPnl") or 0)
            if t.get("commissionAsset") == "USDT":
                fee += float(t.get("commission") or 0)
            else:
                fee_known = False
        if qty > 0:
            exit_px = quote / qty
            if not fee_known:
                fee = linear_taker_fee_usdt(qty, exit_px, float(settings.TAKER_FEE))
            profit = realized - fee
        else:
            exit_px = mkt.last_price()
            entry = float(ot["entry_price"])
            size = float(ot["size"])
            raw = (exit_px - entry) * size if ot["side"] == "LONG" else (entry - exit_px) * size
            fee = linear_taker_fee_usdt(size, exit_px, float(settings.TAKER_FEE))
            profit = raw - fee
        stop = ot.get("exchange_stop")
        reason = "EXCHANGE_STOP" if stop and stop.get("id") else "EXCHANGE_CLOSED"
        if tr is not None and stop:
            try:
                tr.cancel_stop(bot["symbol"], stop)
            except Exception:
                pass
        self._book_external_close(bot, st, ot, exit_px, profit, reason,
                                  {"exit_fee": fee, "entry_fee": ot.get("entry_fee"), "symbol": bot["symbol"],
                                   "real": True, "estimated": qty <= 0},
                                  mkt.row_closed)
        self._missing.pop(bot["id"], None)
        return True

    # -------------------------------------------------- stop dự phòng trên sàn
    @staticmethod
    def desired_stop(bot: dict, ot: dict):
        mode = bot.get("exchange_stop", "trail")
        if mode == "off":
            return None
        side = ot["side"]
        entry = float(ot["entry_price"])
        size = float(ot["size"]) or 1e-12
        hard = entry - max_loss_from_capital(ot) / size if side == "LONG" else entry + max_loss_from_capital(ot) / size
        if mode == "hard":
            return hard
        trail = float(ot.get("trail_stop") or hard)
        return max(trail, hard) if side == "LONG" else min(trail, hard)

    def _sync_stop(self, bot: dict, ot: dict, price: float, force: bool = False):
        want = self.desired_stop(bot, ot)
        if want is None or want <= 0 or not price:
            return
        side = ot["side"]
        # Stop phải nằm phía "chưa khớp" so với giá hiện tại, nếu không sàn từ chối → bot tự đóng bằng MARKET
        if (side == "LONG" and want >= price) or (side == "SHORT" and want <= price):
            return
        cur = ot.get("exchange_stop") or {}
        cur_px = float(cur.get("price") or 0)
        if cur_px and not force:
            better = want > cur_px if side == "LONG" else want < cur_px
            if not better or abs(want - cur_px) / price < STOP_UPDATE_MIN_MOVE:
                return
            if time.time() - float(cur.get("at") or 0) < STOP_UPDATE_MIN_SEC:
                return
        tr = self.trader_for(bot["account_id"])
        if tr is None:
            return
        try:
            try:
                new = tr.place_stop(bot["symbol"], side, want)
                if cur.get("id"):
                    tr.cancel_stop(bot["symbol"], cur)
            except BinanceAPIError:
                if not cur.get("id"):
                    raise
                tr.cancel_stop(bot["symbol"], cur)
                ot["exchange_stop"] = None
                new = tr.place_stop(bot["symbol"], side, want)
            new["at"] = time.time()
            ot["exchange_stop"] = new
        except Exception as e:
            self._error(f"stop:{bot['id']}", f"{self._tag(bot)} Không đặt được stop dự phòng trên sàn ({_fmt_px(want)}): {e}. "
                        f"Bot vẫn tự đóng lệnh khi chạm stop, nhưng nếu VPS tắt thì vị thế không có bảo vệ.", bot)

    # ---------------------------------------------------------- báo cáo
    def overview(self, max_age: float = 4.0) -> dict:
        """Dữ liệu cho dashboard + Telegram (gọi API sàn: số dư, vị thế). Cache vài giây."""
        cached = getattr(self, "_ov_cache", None)
        if cached and time.time() - cached[0] < max_age:
            return cached[1]
        ov = self._overview()
        self._ov_cache = (time.time(), ov)
        return ov

    def _overview(self) -> dict:
        accounts = []
        for a in store.list_accounts():
            info = {**a, "env_label": ENV_LABELS.get(a.get("env"), a.get("env"))}
            tr = self.trader_for(a["id"]) if a.get("has_keys") else None
            if tr is not None:
                try:
                    info["balance"] = tr.get_balance()
                    info["positions"] = tr.get_positions()
                except Exception as e:
                    info["error"] = str(e)
            accounts.append(info)
        pos_by_acc = {a["id"]: a.get("positions") or [] for a in accounts}
        bots = []
        today = _now().date()
        for b in store.list_bots():
            st = store.bot_state(b["id"])
            ot = st.get("open_trade")
            trades = st.get("trades") or []
            total = sum(float(t.get("profit") or 0) for t in trades)
            fees_in = sum(float(t.get("entry_fee") or 0) for t in trades)
            today_pnl = 0.0
            today_n = 0
            for t in trades:
                try:
                    if pd.Timestamp(t.get("exit_time")).tz_convert(_tz_app).date() == today:
                        today_pnl += float(t.get("profit") or 0)
                        today_n += 1
                except Exception:
                    pass
            item = {
                **b,
                "balance": float(st.get("balance") or 0),
                "started_at": st.get("started_at"),
                "total_pnl": total - fees_in,
                "n_trades": len(trades),
                "wins": sum(1 for t in trades if float(t.get("profit") or 0) > 0),
                "today_pnl": today_pnl,
                "today_n": today_n,
                "cb": st.get("cb"),
                "open_trade": None,
                "price": (self.market_cache.get(b["symbol"]) or {}).get("price"),
            }
            if ot:
                pos = next((p for p in pos_by_acc.get(b["account_id"], []) if p["symbol"] == b["symbol"] and p["side"] == ot["side"]), None)
                upnl = pos["unrealized"] if pos else None
                if upnl is None and item["price"]:
                    e = float(ot["entry_price"])
                    upnl = (item["price"] - e) * float(ot["size"]) if ot["side"] == "LONG" else (e - item["price"]) * float(ot["size"])
                item["open_trade"] = {
                    "side": ot["side"], "entry_price": ot["entry_price"], "size": ot["size"], "margin": ot.get("margin"),
                    "entry_time": ot.get("entry_time"), "trail_stop": ot.get("trail_stop"),
                    "exchange_stop": (ot.get("exchange_stop") or {}).get("price"),
                    "hard_stop": self.desired_stop({**b, "exchange_stop": "hard"}, ot),
                    "unrealized": upnl, "mark_price": pos["mark_price"] if pos else item["price"],
                    "on_exchange": pos is not None,
                }
            item["equity"] = item["balance"] + float((item["open_trade"] or {}).get("unrealized") or 0)
            bots.append(item)
        return {
            "real_trading_enabled": store.real_trading_enabled(),
            "accounts": accounts,
            "bots": bots,
            "last_tick_at": self.last_tick_at,
            "last_error": self.last_error,
            "server_time": _now().isoformat(),
            "in_4h_window": is_4h_boundary_window(),
        }

    def hourly_text(self, ov: dict = None, prev: dict = None) -> str:
        ov = ov or self.overview()
        prev = prev or {}
        lines = [f"⏰ Báo cáo trade thật {_now():%d/%m %H:%M} — công tắc: {'🟢 BẬT' if ov['real_trading_enabled'] else '⚪ TẮT'}"]
        for a in ov["accounts"]:
            if a.get("error"):
                lines.append(f"💼 {a['name']}: lỗi đọc số dư ({a['error'][:80]})")
                continue
            bal = a.get("balance")
            if not bal:
                continue
            w = bal["wallet"] + bal["unrealized"]
            p = (prev.get("accounts") or {}).get(a["id"])
            chg = f" ({(w - p) / p * 100:+.2f}% /1h)" if p else ""
            lines.append(f"💼 {a['name']} [{a.get('env')}]: {w:.2f} USDT{chg} | uPnL {bal['unrealized']:+.2f}")
        for b in ov["bots"]:
            if b["status"] == "stopped" and not b["open_trade"]:
                continue
            p = (prev.get("bots") or {}).get(b["id"])
            chg = f" ({(b['equity'] - p) / p * 100:+.2f}% /1h)" if p else ""
            cap = float(b.get("capital") or 0) or 1
            line = (f"🤖 {b['name']} [{b['status']}] vốn {b['equity']:.2f}{chg}, "
                    f"tổng {b['total_pnl']:+.2f} ({(b['equity'] - cap) / cap * 100:+.1f}% từ đầu), hôm nay {b['today_pnl']:+.2f}/{b['today_n']} lệnh")
            ot = b["open_trade"]
            if ot:
                u = ot.get("unrealized")
                line += f"\n    ↳ {ot['side']} @ {_fmt_px(ot['entry_price'])}, uPnL {u:+.2f}" if u is not None else f"\n    ↳ {ot['side']} @ {_fmt_px(ot['entry_price'])}"
            lines.append(line)
        if len(lines) == 1:
            lines.append("Chưa có tài khoản / bot nào.")
        return "\n".join(lines)

    def _maybe_hourly_report(self, bots):
        now = _now()
        key = now.strftime("%Y%m%d%H")
        if self._last_report_hour is None:
            self._last_report_hour = key  # không gửi ngay khi khởi động
            return
        if key == self._last_report_hour:
            return
        self._last_report_hour = key
        if not bots and not store.list_accounts():
            return
        try:
            ov = self.overview(max_age=0)
            snaps = store.snapshots(1)
            prev = snaps[-1] if snaps else {}
            text = self.hourly_text(ov, prev)
            snap = {
                "t": now.isoformat(),
                "accounts": {a["id"]: a["balance"]["wallet"] + a["balance"]["unrealized"] for a in ov["accounts"] if a.get("balance")},
                "bots": {b["id"]: b["equity"] for b in ov["bots"]},
            }
            store.add_snapshot(snap)
            self.notifier.broadcast("hourly", text)
        except Exception as e:
            self._error("hourly", f"Báo cáo giờ lỗi: {e}")


_engine = None


def get_engine() -> LiveEngine:
    global _engine
    if _engine is None:
        _engine = LiveEngine()
    return _engine


def start_engine_thread():
    eng = get_engine()
    t = threading.Thread(target=eng.run, name="live-engine", daemon=True)
    t.start()
    return eng
