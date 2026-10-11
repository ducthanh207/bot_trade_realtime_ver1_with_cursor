# -*- coding: utf-8 -*-
"""
Binance USDⓈ-M Futures — client ký HMAC cho trade thật, mỗi tài khoản một instance.

Không phụ thuộc python-binance để tự chọn môi trường (mainnet / testnet / demo) và gọi
được Algo Order API (lệnh stop điều kiện). Mọi hàm ném BinanceAPIError khi sàn trả lỗi.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import threading
import time
from decimal import Decimal, ROUND_DOWN
from urllib.parse import urlencode

import requests

BASE_URLS = {
    "mainnet": "https://fapi.binance.com",
    "testnet": "https://testnet.binancefuture.com",
    "demo": "https://demo-fapi.binance.com",
}

ENV_LABELS = {
    "mainnet": "Tài khoản thật (mainnet)",
    "testnet": "Testnet (testnet.binancefuture.com)",
    "demo": "Demo trading (demo-fapi.binance.com)",
}

RECV_WINDOW = 10000


class BinanceAPIError(Exception):
    def __init__(self, status: int, code, msg: str):
        super().__init__(f"Binance {status} code={code}: {msg}")
        self.status = status
        self.code = code
        self.msg = msg


# exchangeInfo dùng chung giữa các tài khoản cùng môi trường
_exinfo_cache: dict = {}
_exinfo_lock = threading.Lock()


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    q = Decimal(str(step))
    return float((Decimal(str(value)) / q).to_integral_value(rounding=ROUND_DOWN) * q)


def _fmt(value: float) -> str:
    """Số → chuỗi thập phân ngắn nhất, không ký hiệu mũ (59000.1, 0.003)."""
    s = format(Decimal(str(value)), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


class BinanceFuturesTrader:
    exchange_id = "binance_usdm"

    def __init__(self, api_key: str, api_secret: str, env: str = "mainnet", timeout: float = 10.0):
        if env not in BASE_URLS:
            env = "mainnet"
        self.env = env
        self.base = BASE_URLS[env]
        self.api_key = (api_key or "").strip()
        self.api_secret = (api_secret or "").strip()
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"X-MBX-APIKEY": self.api_key})
        self._time_offset_ms = 0
        self._time_synced_at = 0.0
        self._dual_side = None
        self._leverage_set: dict = {}

    # ------------------------------------------------------------------ HTTP
    def _sync_time(self, force: bool = False):
        if not force and time.time() - self._time_synced_at < 1800:
            return
        try:
            r = self._request("GET", self.base + "/fapi/v1/time")
            server = int(r.json()["serverTime"])
            self._time_offset_ms = server - int(time.time() * 1000)
            self._time_synced_at = time.time()
        except Exception:
            pass

    def _request(self, method: str, url: str, **kw):
        try:
            return self._session.request(method, url, timeout=self.timeout, **kw)
        except requests.RequestException as e:
            # Không đưa URL (có chữ ký) vào thông báo lỗi
            raise ConnectionError(f"Không kết nối được {self.base} ({e.__class__.__name__})") from None

    def _public(self, path: str, params: dict = None):
        r = self._request("GET", self.base + path, params=params or {})
        return self._handle(r)

    def _signed(self, method: str, path: str, params: dict = None, _retry: bool = True):
        self._sync_time()
        p = {k: v for k, v in (params or {}).items() if v is not None}
        p["timestamp"] = int(time.time() * 1000) + self._time_offset_ms
        p["recvWindow"] = RECV_WINDOW
        query = urlencode(p)
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}?{query}&signature={sig}"
        r = self._request(method, url)
        try:
            return self._handle(r)
        except BinanceAPIError as e:
            # -1021: lệch giờ VPS ↔ sàn → đồng bộ lại và thử một lần
            if _retry and e.code == -1021:
                self._sync_time(force=True)
                return self._signed(method, path, params, _retry=False)
            raise

    @staticmethod
    def _handle(r):
        try:
            data = r.json()
        except ValueError:
            data = {"code": None, "msg": r.text[:300]}
        if r.status_code >= 400 or (isinstance(data, dict) and isinstance(data.get("code"), int) and data["code"] < 0):
            raise BinanceAPIError(r.status_code, data.get("code") if isinstance(data, dict) else None,
                                  data.get("msg", "") if isinstance(data, dict) else str(data))
        return data

    # ------------------------------------------------------------ thông tin
    def exchange_info(self) -> dict:
        with _exinfo_lock:
            c = _exinfo_cache.get(self.base)
            if c and time.time() - c[0] < 3600:
                return c[1]
        data = self._public("/fapi/v1/exchangeInfo")
        symbols = {}
        for s in data.get("symbols", []):
            f = {x["filterType"]: x for x in s.get("filters", [])}
            lot = f.get("MARKET_LOT_SIZE") or f.get("LOT_SIZE") or {}
            lot2 = f.get("LOT_SIZE") or {}
            step = float(lot.get("stepSize") or lot2.get("stepSize") or 0.001)
            if step <= 0:
                step = float(lot2.get("stepSize") or 0.001)
            symbols[s["symbol"]] = {
                "status": s.get("status"),
                "contract_type": s.get("contractType"),
                "step": step,
                "min_qty": float(lot.get("minQty") or lot2.get("minQty") or 0),
                "max_qty": float(lot.get("maxQty") or lot2.get("maxQty") or 0) or math.inf,
                "tick": float((f.get("PRICE_FILTER") or {}).get("tickSize") or 0.01),
                "min_notional": float((f.get("MIN_NOTIONAL") or {}).get("notional") or 5),
            }
        with _exinfo_lock:
            _exinfo_cache[self.base] = (time.time(), symbols)
        return symbols

    def symbol_rules(self, symbol: str) -> dict:
        rules = self.exchange_info().get(symbol.upper())
        if not rules:
            raise BinanceAPIError(400, None, f"Không tìm thấy cặp {symbol} trên Binance Futures")
        return rules

    def round_qty(self, symbol: str, qty: float) -> float:
        return _round_step(qty, self.symbol_rules(symbol)["step"])

    def round_price(self, symbol: str, price: float) -> float:
        tick = self.symbol_rules(symbol)["tick"]
        return float(Decimal(str(price)).quantize(Decimal(str(tick)), rounding=ROUND_DOWN)) if tick else price

    def mark_price(self, symbol: str) -> float:
        d = self._public("/fapi/v1/premiumIndex", {"symbol": symbol})
        return float(d.get("markPrice") or 0)

    # ------------------------------------------------------------- tài khoản
    def test_connection(self) -> dict:
        """Kiểm tra key: trả số dư USDT + chế độ vị thế. Ném lỗi nếu key sai / thiếu quyền Futures."""
        bal = self.get_balance()
        dual = self.is_dual_side(refresh=True)
        return {"ok": True, "env": self.env, "dual_side": dual, **bal}

    def get_balance(self) -> dict:
        """Số dư USDT: wallet, available, unrealized PnL."""
        data = self._signed("GET", "/fapi/v2/balance")
        for b in data:
            if b.get("asset") == "USDT":
                return {
                    "wallet": float(b.get("balance") or 0),
                    "available": float(b.get("availableBalance") or 0),
                    "unrealized": float(b.get("crossUnPnl") or 0),
                }
        return {"wallet": 0.0, "available": 0.0, "unrealized": 0.0}

    def is_dual_side(self, refresh: bool = False) -> bool:
        if self._dual_side is None or refresh:
            d = self._signed("GET", "/fapi/v1/positionSide/dual")
            self._dual_side = bool(d.get("dualSidePosition"))
        return self._dual_side

    def get_positions(self) -> list:
        """Mọi vị thế đang mở (positionAmt != 0)."""
        try:
            data = self._signed("GET", "/fapi/v3/positionRisk")
        except BinanceAPIError as e:
            if e.status == 404:
                data = self._signed("GET", "/fapi/v2/positionRisk")
            else:
                raise
        out = []
        for p in data:
            amt = float(p.get("positionAmt") or 0)
            if amt == 0:
                continue
            out.append({
                "symbol": p.get("symbol"),
                "position_side": p.get("positionSide") or "BOTH",
                "side": "LONG" if amt > 0 else "SHORT",
                "qty": abs(amt),
                "entry_price": float(p.get("entryPrice") or 0),
                "mark_price": float(p.get("markPrice") or 0),
                "unrealized": float(p.get("unRealizedProfit") or p.get("unrealizedProfit") or 0),
                "liq_price": float(p.get("liquidationPrice") or 0),
                "leverage": p.get("leverage"),
            })
        return out

    def set_leverage(self, symbol: str, leverage: int):
        key = (symbol, int(leverage))
        if self._leverage_set.get(symbol) == key:
            return
        self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": int(leverage)})
        self._leverage_set[symbol] = key

    # ---------------------------------------------------------------- lệnh
    def _pos_side(self, side: str):
        return side if self.is_dual_side() else None

    def market_order(self, symbol: str, side: str, qty: float, reduce_only: bool = False) -> dict:
        """
        side = hướng VỊ THẾ (LONG/SHORT). reduce_only=True → lệnh đóng vị thế đó.
        Trả {"order_id", "avg_price", "qty", "fee", "realized"} (fee/realized lấy từ userTrades).
        """
        if reduce_only:
            order_side = "SELL" if side == "LONG" else "BUY"
        else:
            order_side = "BUY" if side == "LONG" else "SELL"
        params = {
            "symbol": symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": _fmt(qty),
            "newOrderRespType": "RESULT",
        }
        ps = self._pos_side(side)
        if ps:
            params["positionSide"] = ps
        elif reduce_only:
            params["reduceOnly"] = "true"
        res = self._signed("POST", "/fapi/v1/order", params)
        order_id = res.get("orderId")
        avg = float(res.get("avgPrice") or 0)
        executed = float(res.get("executedQty") or 0)
        if (avg <= 0 or executed <= 0) and order_id:
            for _ in range(5):
                time.sleep(0.4)
                q = self._signed("GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id})
                avg = float(q.get("avgPrice") or 0)
                executed = float(q.get("executedQty") or 0)
                if q.get("status") == "FILLED":
                    break
        fee, realized, got = self.order_fills(symbol, order_id)
        if got and executed <= 0:
            executed = got["qty"]
            avg = got["avg_price"]
        return {"order_id": order_id, "avg_price": avg, "qty": executed, "fee": fee, "realized": realized}

    def order_fills(self, symbol: str, order_id):
        """Tổng phí (USDT) + realizedPnl của một lệnh từ userTrades. Phí trả bằng BNB thì quy theo giá khớp × taker ước lượng = None."""
        if not order_id:
            return None, None, None
        trades = []
        for _ in range(3):
            try:
                trades = self._signed("GET", "/fapi/v1/userTrades", {"symbol": symbol, "orderId": order_id})
            except BinanceAPIError:
                trades = []
            if trades:
                break
            time.sleep(0.4)
        if not trades:
            return None, None, None
        fee = 0.0
        fee_known = True
        realized = 0.0
        qty = 0.0
        quote = 0.0
        for t in trades:
            if t.get("commissionAsset") == "USDT":
                fee += float(t.get("commission") or 0)
            else:
                fee_known = False
            realized += float(t.get("realizedPnl") or 0)
            q = float(t.get("qty") or 0)
            qty += q
            quote += q * float(t.get("price") or 0)
        agg = {"qty": qty, "avg_price": quote / qty if qty else 0.0}
        return (fee if fee_known else None), realized, agg

    def user_trades_since(self, symbol: str, start_ms: int) -> list:
        return self._signed("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": int(start_ms), "limit": 1000})

    # ------------------------------------------------- stop dự phòng trên sàn
    def place_stop(self, symbol: str, side: str, stop_price: float) -> dict:
        """
        Đặt STOP_MARKET đóng toàn bộ vị thế `side` khi giá chạm stop_price (giá giao dịch, không phải mark).
        Ưu tiên Algo Order API (Binance chuyển lệnh điều kiện sang đây từ 12/2025), lỗi thì dùng /fapi/v1/order.
        Trả {"kind": "algo"|"order", "id": ..., "price": ...}.
        """
        order_side = "SELL" if side == "LONG" else "BUY"
        px = self.round_price(symbol, stop_price)
        common = {"symbol": symbol, "side": order_side, "type": "STOP_MARKET", "closePosition": "true",
                  "workingType": "CONTRACT_PRICE", "priceProtect": "true"}
        ps = self._pos_side(side)
        if ps:
            common["positionSide"] = ps
        try:
            res = self._signed("POST", "/fapi/v1/algoOrder", {**common, "algoType": "CONDITIONAL", "triggerPrice": _fmt(px)})
            return {"kind": "algo", "id": res.get("algoId"), "price": px}
        except BinanceAPIError as e_algo:
            try:
                res = self._signed("POST", "/fapi/v1/order", {**common, "stopPrice": _fmt(px)})
                return {"kind": "order", "id": res.get("orderId"), "price": px}
            except BinanceAPIError as e_old:
                raise BinanceAPIError(e_old.status, e_old.code, f"{e_old.msg} (algo: {e_algo.msg})")

    def cancel_stop(self, symbol: str, stop: dict):
        if not stop or not stop.get("id"):
            return
        try:
            if stop.get("kind") == "algo":
                self._signed("DELETE", "/fapi/v1/algoOrder", {"algoId": stop["id"]})
            else:
                self._signed("DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": stop["id"]})
        except BinanceAPIError as e:
            # Lệnh đã khớp / đã hủy / không tồn tại → coi như xong
            m = (e.msg or "").lower()
            if e.code in (-2011, -2013) or "not exist" in m or "unknown order" in m or "not found" in m:
                return
            raise
