# -*- coding: utf-8 -*-
"""
Binance Futures: lấy giá (klines) từ API công khai – không cần API key.
Paper trade chạy trên code (VPS/máy), không dùng paper trade của Binance.
Khi bật trade thật: dùng API key để get_balance, get_position, place_market_order, close_position.
"""

import pandas as pd
import requests

from config import settings

# API công khai Binance Futures – chỉ cần cho klines (không cần key)
FAPI_BASE = "https://fapi.binance.com"


class BinanceClient:
    def __init__(self):
        self._client = None
        self._has_key = bool(settings.BINANCE_API_KEY and settings.BINANCE_API_SECRET)

    def _get_client(self):
        """Chỉ có khi đã cấu hình API key (dùng cho trade thật sau này)."""
        if self._client is None and self._has_key:
            from binance.client import Client
            self._client = Client(
                settings.BINANCE_API_KEY,
                settings.BINANCE_API_SECRET,
                testnet=settings.BINANCE_TESTNET,
            )
        return self._client

    def is_connected(self) -> bool:
        """True nếu có thể lấy giá: dùng API công khai (không cần key) hoặc đã có key."""
        return True  # Giá luôn lấy được qua public API

    def _klines_to_df(self, klines) -> pd.DataFrame:
        """Chuyển list klines Binance -> DataFrame (timestamp, open, high, low, close)."""
        if not klines:
            return pd.DataFrame(columns=["open", "high", "low", "close"]).rename_axis("timestamp")
        rows = []
        for k in klines:
            rows.append({
                "timestamp": pd.Timestamp(k[0], unit="ms", tz="UTC"),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
            })
        df = pd.DataFrame(rows).set_index("timestamp")
        df.index.name = "timestamp"
        return df

    def _fetch_klines_public(self, symbol: str, interval: str, limit: int):
        """Lấy klines qua API công khai – không cần API key."""
        url = f"{FAPI_BASE}/fapi/v1/klines"
        try:
            r = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception:
            return []

    def get_klines_4h(self, symbol: str = None, limit: int = 500) -> pd.DataFrame:
        symbol = symbol or settings.SYMBOL
        if self._has_key:
            client = self._get_client()
            if client:
                from binance.client import Client
                klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_4HOUR, limit=limit)
                return self._klines_to_df(klines)
        klines = self._fetch_klines_public(symbol, "4h", limit)
        return self._klines_to_df(klines)

    def get_klines_1m(self, symbol: str = None, limit: int = 1000) -> pd.DataFrame:
        symbol = symbol or settings.SYMBOL
        if self._has_key:
            client = self._get_client()
            if client:
                from binance.client import Client
                klines = client.futures_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
                return self._klines_to_df(klines)
        klines = self._fetch_klines_public(symbol, "1m", limit)
        return self._klines_to_df(klines)

    def get_balance(self) -> float:
        """Số dư USDT – chỉ có khi đã cấu hình API key (trade thật)."""
        client = self._get_client()
        if not client:
            return 0.0
        acc = client.futures_account_balance()
        for b in acc:
            if b["asset"] == "USDT":
                return float(b.get("availableBalance", 0) or b.get("balance", 0))
        return 0.0

    def get_position(self, symbol: str = None):
        """Position trên sàn – chỉ có khi trade thật (có API key)."""
        symbol = symbol or settings.SYMBOL
        client = self._get_client()
        if not client:
            return None
        positions = client.futures_position_information(symbol=symbol)
        for p in positions:
            amt = float(p.get("positionAmt", 0))
            if amt == 0:
                continue
            return {
                "side": "LONG" if amt > 0 else "SHORT",
                "size": abs(amt),
                "entry_price": float(p.get("entryPrice", 0)),
            }
        return None

    def set_leverage(self, symbol: str = None, leverage: int = None):
        """Chỉ dùng khi trade thật."""
        if not self._has_key:
            return
        leverage = leverage or int(settings.LEVERAGE)
        symbol = symbol or settings.SYMBOL
        client = self._get_client()
        if client:
            client.futures_change_leverage(symbol=symbol, leverage=leverage)

    def place_market_order(self, symbol: str, side: str, quantity: float, reduce_only: bool = False):
        """Chỉ dùng khi trade thật (có API key)."""
        client = self._get_client()
        if not client:
            return None
        side_binance = "BUY" if side == "LONG" else "SELL"
        params = {"symbol": symbol, "side": side_binance, "type": "MARKET", "quantity": quantity}
        if reduce_only:
            params["reduceOnly"] = "true"
        return client.futures_create_order(**params)

    def close_position(self, symbol: str = None):
        """Chỉ dùng khi trade thật."""
        pos = self.get_position(symbol)
        if not pos:
            return None
        side_close = "SELL" if pos["side"] == "LONG" else "BUY"
        client = self._get_client()
        if not client:
            return None
        qty = round(pos["size"], 3)
        return client.futures_create_order(
            symbol=symbol or settings.SYMBOL,
            side=side_close,
            type="MARKET",
            quantity=qty,
            reduceOnly="true",
        )
