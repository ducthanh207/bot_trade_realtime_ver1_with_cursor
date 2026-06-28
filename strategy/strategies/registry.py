# -*- coding: utf-8 -*-
import os

METHOD_1 = "1"
METHOD_2 = "2"
METHOD_3 = "3"

_LABELS = {
    METHOD_1: "Phương pháp 1 — thoát cổ điển (4H + early + ATR trail + SL)",
    METHOD_2: "Phương pháp 2 — TP %change + lọc đảo chiều RSI 1H (4H/early chỉ khi lãi + đảo chiều)",
    METHOD_3: "Phương pháp 3 — Exit B (tầng mạnh: RSI slope) + EMA filter ADX>30 + Circuit breaker",
}


def get_trading_method() -> str:
    v = METHOD_1
    try:
        from config import settings
        v = str(
            getattr(settings, "TRADING_METHOD", None) or os.environ.get("TRADING_METHOD") or METHOD_1
        ).strip().lower()
    except Exception:
        v = str(os.environ.get("TRADING_METHOD") or METHOD_1).strip().lower()
    if v in ("2", "method2", "phuong_phap_2", "pp2"):
        return METHOD_2
    if v in ("3", "method3", "phuong_phap_3", "pp3"):
        return METHOD_3
    return METHOD_1


def get_method_label(method: str = None) -> str:
    m = method if method is not None else get_trading_method()
    return _LABELS.get(m, _LABELS[METHOD_1])


def uses_pct_change_bands(method: str) -> bool:
    return str(method).strip() == METHOD_2


def describe_method(method: str = None) -> str:
    m = method if method is not None else get_trading_method()
    if m == METHOD_2:
        return (
            "Phương pháp 2: giữ SL/liquidation/ATR trailing như cũ; "
            "thoát theo tín hiệu 4H / early chỉ khi PnL>0 và RSI 1H có đảo chiều; "
            "thêm TP PCT_CHANGE khi cùng lúc đảo chiều RSI 1H và giá chạm dải %change."
        )
    if m == METHOD_3:
        return (
            "Phương pháp 3: thoát Exit B (tầng mạnh: RSI vượt ngưỡng + slope N nến); "
            "ATR trailing rộng hơn (2.2, grace 2.5 trong 12h đầu); "
            "entry filter EMA50 khi ADX>30; sizing động theo streak thua + ADX zone; "
            "circuit breaker 2 tầng (4 thua→8h cooldown; 7 thua hoặc DD>28%→48h dừng)."
        )
    return "Phương pháp 1: thoát khi tín hiệu 4H / early / ATR trailing / thanh lý / trần lỗ như code gốc."
