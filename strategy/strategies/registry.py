# -*- coding: utf-8 -*-
import os

METHOD_1 = "1"
METHOD_2 = "2"
METHOD_3 = "3"
METHOD_4 = "4"
METHOD_5 = "5"  # [2026-11-07] PP4 + lọc chu kỳ nến ngày (Paper 5, /live, backtest)
METHOD_6 = "6"  # [2026-11-14] PP4 + CVD 4H/1H (chỉ backtest)
METHOD_61 = "6.1"  # [2026-11-14] PP5 + CVD 4H/1H (chỉ backtest)

_LABELS = {
    METHOD_1: "Phương pháp 1 — thoát cổ điển (4H + early + ATR trail + SL)",
    METHOD_2: "Phương pháp 2 — TP %change + lọc đảo chiều RSI 1H (4H/early chỉ khi lãi + đảo chiều)",
    METHOD_3: "Phương pháp 3 — Exit B (tầng mạnh: RSI slope) + EMA filter ADX>30 + Circuit breaker",
    METHOD_4: "Phương pháp 4 — nâng cấp PP3: Exit B thay early, hard stop % vốn, xác nhận RSI 1H, filter RSI extreme + ADX exhaustion",
    METHOD_5: "Phương pháp 5 — PP4 + lọc chu kỳ nến ngày (EMA + %change): tăng chỉ LONG, giảm chỉ SHORT, đi ngang thì thoát nới",
    METHOD_6: "Phương pháp 6 — PP4 + CVD: CVD 4H xác nhận hướng vào lệnh, CVD 1H đi ngược thì siết trailing",
    METHOD_61: "Phương pháp 6.1 — PP5 + CVD: chu kỳ ngày chọn hướng, CVD 4H xác nhận, CVD 1H siết trailing, đi ngang chọn phía theo CVD",
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
    if v in ("4", "method4", "phuong_phap_4", "pp4"):
        return METHOD_4
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
    if m == METHOD_4:
        return (
            "Phương pháp 4 (nâng cấp PP3): Exit B THAY tầng early exit (thoát kiên nhẫn hơn); "
            "grace ATR 2.5 tự siết về 2.2 sau 12h; hard stop mỗi lệnh theo % vốn (mặc định 10%); "
            "entry cần xác nhận hướng RSI 1H; chặn SHORT khi RSI quá bán / LONG khi RSI quá mua; "
            "giảm size khi ADX quá cao (exhaustion); giữ nguyên EMA50 filter, swing, streak sizing, circuit breaker của PP3."
        )
    if m == METHOD_5:
        return (
            "Phương pháp 5 (PP4 + chu kỳ nến ngày): giữ toàn bộ PP4; thêm chu kỳ theo giá đóng nến 1D so với EMA. "
            "Tăng (2 nến đóng trên EMA hoặc đột biến %change) → chỉ LONG; giảm → chỉ SHORT; "
            "đi ngang (3 nến sát EMA trong X = k×ATR ngày) → vào theo phía nến đóng gần nhất, "
            "trailing nới + giảm size + chốt lời dải %change + Exit B đã sửa."
        )
    if m == METHOD_6:
        return (
            "Phương pháp 6 (PP4 + CVD): giữ toàn bộ PP4; chỉ vào khi độ dốc CVD 4H (6 nến) cùng chiều lệnh; "
            "khi CVD 1H (8 nến) đi ngược lệnh 2 giờ liền thì siết trailing về 1.5 ATR."
        )
    if m == METHOD_61:
        return (
            "Phương pháp 6.1 (PP5 + CVD): giữ toàn bộ PP5; thêm xác nhận CVD 4H và siết trailing theo CVD 1H như PP6; "
            "chu kỳ ngày đi ngang thì chọn phía theo độ dốc CVD 4H 2 ngày thay cho nến đóng gần nhất."
        )
    return "Phương pháp 1: thoát khi tín hiệu 4H / early / ATR trailing / thanh lý / trần lỗ như code gốc."
