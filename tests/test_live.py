# -*- coding: utf-8 -*-
"""Test trade thật với sàn giả (không gọi Binance / Telegram thật)."""
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import pytest


# ------------------------------------------------------------------ fixtures
@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setenv("LIVE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LIVE_SECRET_KEY", raising=False)
    import live.secrets_box as sb
    importlib.reload(sb)
    import live.store as store
    importlib.reload(store)
    import live.engine as engine
    importlib.reload(engine)
    return sb, store, engine


def make_klines(minutes=4 * 60 * 120, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-03-01", periods=minutes, freq="min", tz="Asia/Bangkok")
    close = 60000 * np.exp(np.cumsum(rng.normal(0, 0.001, minutes)))
    op = np.r_[close[0], close[:-1]]
    df = pd.DataFrame({"open": op, "high": np.maximum(op, close) * 1.0005, "low": np.minimum(op, close) * 0.9995,
                       "close": close, "volume": 1.0}, index=idx)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    return df, df.resample("1h").agg(agg), df.resample("4h", origin="epoch", offset="-7h").agg(agg)


class FakeMarket:
    def __init__(self):
        self.m1, self.h1, self.h4 = make_klines()

    def get_klines_4h(self, s=None, limit=200):
        return self.h4.tail(limit)

    def get_klines_1h(self, s=None, limit=200):
        return self.h1.tail(limit)

    def get_klines_1m(self, s=None, limit=500):
        return self.m1.tail(limit)


class FakeTrader:
    def __init__(self):
        self.orders = []
        self.stops = []
        self.cancelled = []
        self.positions = []
        self.available = 1000.0
        self.fill_px = None

    def symbol_rules(self, symbol):
        return {"step": 0.001, "min_qty": 0.001, "min_notional": 100, "tick": 0.1}

    def round_qty(self, symbol, q):
        return float(int(q * 1000) / 1000)

    def get_balance(self):
        return {"wallet": 1000.0, "available": self.available, "unrealized": 0.0}

    def get_positions(self):
        return list(self.positions)

    def set_leverage(self, symbol, lev):
        pass

    def market_order(self, symbol, side, qty, reduce_only=False):
        px = self.fill_px
        self.orders.append((symbol, side, qty, reduce_only, px))
        if reduce_only:
            self.positions = [p for p in self.positions if p["symbol"] != symbol]
            entry = self._entry
            realized = (px - entry) * qty if side == "LONG" else (entry - px) * qty
            return {"order_id": len(self.orders), "avg_price": px, "qty": qty, "fee": 0.05, "realized": realized}
        self._entry = px
        self.positions = [{"symbol": symbol, "side": side, "qty": qty, "entry_price": px, "mark_price": px,
                           "unrealized": 0.0, "position_side": "BOTH"}]
        return {"order_id": len(self.orders), "avg_price": px, "qty": qty, "fee": 0.06, "realized": 0.0}

    def place_stop(self, symbol, side, price):
        s = {"kind": "algo", "id": len(self.stops) + 1, "price": price}
        self.stops.append(s)
        return dict(s)

    def cancel_stop(self, symbol, stop):
        self.cancelled.append(stop.get("id") if stop else None)

    def user_trades_since(self, symbol, start_ms):
        return [{"side": "SELL", "orderId": 999, "qty": "0.005", "price": "59000", "realizedPnl": "-5.0",
                 "commission": "0.1", "commissionAsset": "USDT"}]


class FakeNotifier:
    def __init__(self):
        self.msgs = []

    def broadcast(self, kind, text, tg_ids=None):
        self.msgs.append((kind, text))


def setup_bot(store, method="1"):
    acc = store.upsert_account({"name": "Main", "env": "testnet", "api_key": "KEY1234567890abcd", "api_secret": "SECRET1234567890"})
    store.set_account_field(acc["id"], enabled=True)
    b = store.upsert_bot({"account_id": acc["id"], "symbol": "BTCUSDT", "method": method, "capital": 100,
                          "leverage": 20, "wallet_pct": 0.3})
    store.set_bot_status(b["id"], "running")
    return acc, b


@pytest.fixture()
def rig(live, monkeypatch):
    sb, store, engine = live
    import bot.slot_engine as se
    sig = {"long": False, "exit": None}
    monkeypatch.setattr(se, "long_entry", lambda p, r: sig["long"])
    monkeypatch.setattr(se, "short_entry", lambda p, r: False)
    real_cec = se.compute_exit_candidates

    def fake_cec(open_trade, df_1m, *a, **k):
        if sig["exit"]:
            return [(df_1m.index[-1], 0.0, sig["exit"], "4H_EXIT")]
        return []
    monkeypatch.setattr(se, "compute_exit_candidates", fake_cec)
    monkeypatch.setattr(engine, "is_4h_boundary_window", lambda: True)
    trader = FakeTrader()
    market = FakeMarket()
    trader.fill_px = float(market.m1["close"].iloc[-1]) + 5
    notifier = FakeNotifier()
    eng = engine.LiveEngine(market_client=market, trader_factory=lambda a, k, s: trader, notifier=notifier)
    acc, b = setup_bot(store)
    return store, eng, trader, notifier, sig, b, market


# ------------------------------------------------------------------- tests
def test_secrets_encrypted_on_disk(live):
    sb, store, engine = live
    setup_bot(store)
    raw = (Path(sb.DATA_DIR) / "config.json").read_text()
    assert "KEY1234567890abcd" not in raw and "SECRET1234567890" not in raw
    pub = store.list_accounts()[0]
    assert not any(k.endswith("_enc") for k in pub)
    assert pub["key_hint"] == "KEY1…abcd"
    assert store.account_credentials(pub["id"]) == ("KEY1234567890abcd", "SECRET1234567890")


def test_switch_off_only_signals(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    assert store.real_trading_enabled() is False
    sig["long"] = True
    eng.tick()
    eng.tick()
    assert trader.orders == []
    assert sum(1 for k, t in notifier.msgs if "Tín hiệu" in t) == 1  # chỉ báo 1 lần / nến 4H
    assert store.bot_state(b["id"])["open_trade"] is None


def test_open_and_close_real(rig):
    store, eng, trader, notifier, sig, b, market = rig
    store.set_real_trading_enabled(True)
    sig["long"] = True
    eng.tick()
    st = store.bot_state(b["id"])
    ot = st["open_trade"]
    assert ot is not None and ot["real"] is True
    # size = 100 * 0.3 * 20 / giá, làm tròn 0.001
    assert trader.orders[0][2] == trader.round_qty("BTCUSDT", 600 / float(market.m1["close"].iloc[-1]))
    assert ot["entry_price"] == trader.fill_px            # giá khớp thật, không phải giá nến
    assert st["balance"] == pytest.approx(100 - 0.06)    # trừ phí vào thật
    assert trader.stops, "phải đặt stop dự phòng trên sàn"
    assert trader.stops[0]["price"] < ot["entry_price"]

    sig["long"] = False
    trader.fill_px = ot["entry_price"] + 100
    sig["exit"] = trader.fill_px
    eng.tick()
    st = store.bot_state(b["id"])
    assert st["open_trade"] is None
    t = st["trades"][-1]
    assert t["exit_reason"] == "4H_EXIT"
    assert t["profit"] == pytest.approx(100 * ot["size"] - 0.05)
    assert st["balance"] == pytest.approx(100 - 0.06 + t["profit"])
    assert trader.orders[-1][3] is True                   # reduce-only
    assert trader.cancelled                               # huỷ stop sau khi đóng


def test_exchange_closed_is_reconciled(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    store.set_real_trading_enabled(True)
    sig["long"] = True
    eng.tick()
    sig["long"] = False
    assert store.bot_state(b["id"])["open_trade"]
    trader.positions = []          # stop trên sàn đã khớp
    eng.tick()                     # lần 1: chưa chắc
    assert store.bot_state(b["id"])["open_trade"] is not None
    eng.tick()                     # lần 2: ghi sổ
    st = store.bot_state(b["id"])
    assert st["open_trade"] is None
    t = st["trades"][-1]
    assert t["exit_reason"] == "EXCHANGE_STOP"
    assert t["exit_price"] == pytest.approx(59000)
    assert t["profit"] == pytest.approx(-5.1)


def test_manual_close_and_pause(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    store.set_real_trading_enabled(True)
    sig["long"] = True
    eng.tick()
    store.set_bot_status(b["id"], "stopped")   # dừng nhưng còn lệnh → vẫn quản lý
    eng.request_close(b["id"], by="web")
    eng.tick()
    st = store.bot_state(b["id"])
    assert st["open_trade"] is None
    assert st["trades"][-1]["exit_reason"] == "MANUAL_WEB"
    n = len(trader.orders)
    eng.tick()
    assert len(trader.orders) == n  # bot đã dừng: không mở lệnh mới


def test_existing_position_blocks_entry(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    store.set_real_trading_enabled(True)
    trader.positions = [{"symbol": "BTCUSDT", "side": "SHORT", "qty": 0.01, "entry_price": 1, "mark_price": 1,
                         "unrealized": 0, "position_side": "BOTH"}]
    sig["long"] = True
    eng.tick()
    assert trader.orders == []
    assert any("không do bot mở" in t for k, t in notifier.msgs)


def test_too_small_order_is_skipped(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    store.set_real_trading_enabled(True)
    store.upsert_bot({"id": b["id"], "capital": 5, "reset_capital": True})
    st = store.bot_state(b["id"])
    st["balance"] = 5
    sig["long"] = True
    eng.tick()
    assert trader.orders == []
    assert any("tối thiểu" in t for k, t in notifier.msgs)


def test_state_survives_restart(rig):
    store, eng, trader, notifier, sig, b, _ = rig
    store.set_real_trading_enabled(True)
    sig["long"] = True
    eng.tick()
    store.save_state()
    ot = store.bot_state(b["id"])["open_trade"]
    store.reload()
    ot2 = store.bot_state(b["id"])["open_trade"]
    assert ot2["entry_price"] == ot["entry_price"]
    assert isinstance(ot2["last_sl_check"], pd.Timestamp) and ot2["last_sl_check"].tzinfo is not None


def test_one_bot_per_account_symbol(live):
    sb, store, engine = live
    acc, b = setup_bot(store)
    with pytest.raises(ValueError):
        store.upsert_bot({"account_id": acc["id"], "symbol": "BTCUSDT", "method": "2"})


def test_web_requires_login_and_csrf(live, monkeypatch):
    monkeypatch.setenv("LIVE_ADMIN_PASSWORD", "pw-123456")
    from web.app import app
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.get("/live").status_code == 302
    assert c.get("/api/live/config").status_code == 401
    assert c.post("/live/login", data={"password": "sai"}).status_code == 200
    r = c.post("/live/login", data={"password": "pw-123456"})
    assert r.status_code == 302
    with c.session_transaction() as s:
        csrf = s["csrf"]
    assert c.post("/api/live/switch", json={"on": True}).status_code == 403
    r = c.post("/api/live/accounts", json={"name": "A", "env": "testnet", "api_key": "abcdefghijklmn", "api_secret": "zzzzzzzzzzzzzz"},
               headers={"X-CSRF-Token": csrf})
    body = r.get_json()
    assert body["ok"] and "api_secret" not in json.dumps(body) and "zzzz" not in json.dumps(body)
    page = c.get("/live")
    assert page.status_code == 200 and "Trade thật" in page.get_data(as_text=True)


def test_telegram_panel_controls(live, monkeypatch):
    sb, store, engine = live
    import live.telegram_ctl as tc
    importlib.reload(tc)
    sent = []
    monkeypatch.setattr(tc, "send", lambda token, chat, text, kb=None: sent.append((chat, text, kb)))
    t = store.upsert_telegram({"name": "Me", "token": "123:ABC", "chat_id": "42"})
    conn = store.list_telegrams()[0]
    upd = {"update_id": 1, "message": {"chat": {"id": 42}, "text": "/live_on"}}
    assert tc._process(conn, "123:ABC", upd, own_poller=True) is True
    assert store.real_trading_enabled() is True
    # chat lạ bị bỏ qua
    upd2 = {"update_id": 2, "message": {"chat": {"id": 7}, "text": "/live_off"}}
    assert tc._process(conn, "123:ABC", upd2, own_poller=True) is False
    assert store.real_trading_enabled() is True
    upd3 = {"update_id": 3, "callback_query": {"id": "x", "data": "lv:off", "message": {"chat": {"id": 42}}}}
    monkeypatch.setattr(tc, "_call", lambda *a, **k: None)
    tc._process(conn, "123:ABC", upd3, own_poller=True)
    assert store.real_trading_enabled() is False
