# -*- coding: utf-8 -*-
"""
[2026-11-22] Vẽ ảnh PNG biểu đồ vốn (PnL) + drawdown của một kết quả backtest, chỉ dùng thư viện chuẩn
(VPS không có matplotlib / Pillow). Ảnh được nhúng vào file Excel (sheet "Biểu đồ PnL").

Chữ trong ảnh dùng font bitmap 5x7 nên chỉ có chữ HOA không dấu, số và vài ký hiệu; phần chữ tiếng Việt
nằm ở các ô Excel phía trên ảnh.
"""

from __future__ import annotations

import struct
import zlib
from datetime import datetime, timedelta, timezone

# Font 5x7: mỗi ký tự 7 dòng, mỗi dòng 5 bit (bit trái = cột 0)
_F = {
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 10001 01010 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "-": "00000 00000 00000 11111 00000 00000 00000", "+": "00000 00100 00100 11111 00100 00100 00000",
    ".": "00000 00000 00000 00000 00000 01100 01100", ",": "00000 00000 00000 00000 01100 00100 01000",
    ":": "00000 01100 01100 00000 01100 01100 00000", "/": "00001 00010 00010 00100 01000 01000 10000",
    "%": "11000 11001 00010 00100 01000 10011 00011", "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000", ">": "01000 00100 00010 00001 00010 00100 01000",
    "=": "00000 00000 11111 00000 11111 00000 00000", "|": "00100 00100 00100 00100 00100 00100 00100",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}
_GLYPH = {k: [int(r, 2) for r in v.split()] for k, v in _F.items()}

BG = (255, 255, 255)
PANEL = (248, 249, 251)
GRID = (226, 229, 235)
AXIS = (100, 106, 120)
TEXT = (30, 34, 45)
UP = (0, 137, 123)
DOWN = (211, 47, 47)
BASE = (150, 155, 168)
DD_FILL = (248, 205, 205)
VN = timezone(timedelta(hours=7))


class Canvas:
    def __init__(self, w: int, h: int, bg=BG):
        self.w, self.h = w, h
        self.px = bytearray(bytes(bg) * (w * h))

    def dot(self, x: int, y: int, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i:i + 3] = bytes(c)

    def rect(self, x0, y0, x1, y1, c):
        x0, x1 = max(0, int(min(x0, x1))), min(self.w, int(max(x0, x1)) + 1)
        y0, y1 = max(0, int(min(y0, y1))), min(self.h, int(max(y0, y1)) + 1)
        if x0 >= x1:
            return
        row = bytes(c) * (x1 - x0)
        for y in range(y0, y1):
            i = (y * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def line(self, x0, y0, x1, y1, c, t: int = 1, dash: int = 0):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err, n, r = dx + dy, 0, t // 2
        while True:
            if not dash or (n // dash) % 2 == 0:
                if t <= 1:
                    self.dot(x0, y0, c)
                else:
                    self.rect(x0 - r, y0 - r, x0 - r + t - 1, y0 - r + t - 1, c)
            n += 1
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def text(self, x, y, s: str, c=TEXT, scale: int = 2, align: str = "left"):
        s = str(s).upper()
        w = len(s) * 6 * scale - scale
        if align == "right":
            x -= w
        elif align == "center":
            x -= w // 2
        x, y = int(x), int(y)
        for ch in s:
            g = _GLYPH.get(ch, _GLYPH[" "])
            for ry, bits in enumerate(g):
                for rx in range(5):
                    if bits & (1 << (4 - rx)):
                        self.rect(x + rx * scale, y + ry * scale, x + rx * scale + scale - 1, y + ry * scale + scale - 1, c)
            x += 6 * scale

    def png(self) -> bytes:
        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _ts(v):
    """Chuỗi / Timestamp → giây epoch (UTC). Chuỗi không múi giờ coi là UTC."""
    if v is None or v == "":
        return None
    try:
        import pandas as pd

        t = pd.Timestamp(v)
        if t.tzinfo is None:
            t = t.tz_localize("UTC")
        return t.timestamp()
    except (TypeError, ValueError):
        return None


def _nice_step(span: float, n: int = 5) -> float:
    raw = span / max(1, n)
    mag = 10 ** len(str(int(raw))) / 10 if raw >= 1 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}".rstrip("0").rstrip(".")


def equity_points(result: dict) -> list:
    """[(epoch, vốn)] bắt đầu bằng vốn ban đầu, mỗi lệnh đóng thêm một điểm (vốn sau lệnh)."""
    cap0 = float(result.get("initial_capital") or 0)
    t0 = _ts(result.get("start"))
    pts = [(t0, cap0)]
    for t in result.get("trades") or []:
        te = _ts(t.get("exit_time"))
        if te is None:
            continue
        pts.append((te, float(t.get("capital_after") or 0)))
    if pts[0][0] is None:
        pts[0] = ((pts[1][0] if len(pts) > 1 else 0) or 0, cap0)
    return pts


def pnl_chart_png(result: dict, w: int = 1400, h: int = 820) -> bytes:
    """Ảnh PNG: trên là vốn theo thời gian (bậc thang theo lệnh đóng), dưới là drawdown % theo lệnh đóng."""
    pts = equity_points(result)
    cap0 = pts[0][1]
    t_end = _ts(result.get("end")) or pts[-1][0]
    t0, t1 = pts[0][0], max(t_end, pts[-1][0])
    if t1 <= t0:
        t1 = t0 + 86400
    peak, dd = cap0, []
    for t, v in pts:
        peak = max(peak, v)
        dd.append((t, (v / peak - 1) * 100 if peak > 0 else 0.0))

    cv = Canvas(w, h)
    final = pts[-1][1]
    ret = (final / cap0 - 1) * 100 if cap0 else 0.0
    col = UP if final >= cap0 else DOWN
    title = f"{result.get('label') or 'PP' + str(result.get('method'))} {result.get('symbol') or ''}"
    cv.text(24, 18, title, TEXT, 3)
    cv.text(w - 24, 18, f"{_fmt(cap0)} -> {_fmt(final)} USDT ({ret:+.2f}%)", col, 3, "right")

    padL, padR = 120, 30
    top0, top1 = 90, int(h * 0.64)      # khung vốn
    bot0, bot1 = top1 + 60, h - 50      # khung drawdown
    X = lambda t: padL + (t - t0) / (t1 - t0) * (w - padL - padR)

    # ---- khung vốn
    vs = [v for _, v in pts]
    vmin, vmax = min(vs), max(vs)
    if vmax - vmin < 1e-9:
        vmin, vmax = vmin - 1, vmax + 1
    pad = (vmax - vmin) * 0.08
    vmin, vmax = vmin - pad, vmax + pad
    Y = lambda v: top0 + (vmax - v) / (vmax - vmin) * (top1 - top0)
    cv.rect(padL, top0, w - padR, top1, PANEL)
    step = _nice_step(vmax - vmin)
    g = (int(vmin / step) - 1) * step
    while g <= vmax:
        if vmin <= g <= vmax:
            cv.line(padL, Y(g), w - padR, Y(g), GRID)
            cv.text(padL - 10, Y(g) - 7, _fmt(g), AXIS, 2, "right")
        g += step
    cv.text(padL, top0 - 22, "VON (USDT)", AXIS, 2)
    if vmin <= cap0 <= vmax:
        cv.line(padL, Y(cap0), w - padR, Y(cap0), BASE, 1, dash=6)
    prev = None
    for t, v in pts:
        if prev is not None:
            cv.line(X(t), Y(prev[1]), X(t), Y(v), col, 3)
        cv.line(X(prev[0]) if prev else X(t), Y(prev[1]) if prev else Y(v), X(t), Y(prev[1]) if prev else Y(v), col, 3)
        prev = (t, v)
    cv.line(X(prev[0]), Y(prev[1]), X(t1), Y(prev[1]), col, 3)

    # ---- khung drawdown
    dmin = min(d for _, d in dd)
    dlo = min(-1.0, dmin * 1.1)
    YD = lambda d: bot0 + (0 - d) / (0 - dlo) * (bot1 - bot0)
    cv.rect(padL, bot0, w - padR, bot1, PANEL)
    dstep = _nice_step(-dlo, 3)
    g = 0.0
    while g >= dlo - 1e-9:
        cv.line(padL, YD(g), w - padR, YD(g), GRID)
        cv.text(padL - 10, YD(g) - 7, f"{g:g}%" if abs(g) >= 1e-9 else "0%", AXIS, 2, "right")
        g = round(g - dstep, 6)
    for k, (t, d) in enumerate(dd):
        tn = dd[k + 1][0] if k + 1 < len(dd) else t1
        if d < 0:
            cv.rect(X(t), YD(d), X(tn), YD(0), DD_FILL)
            cv.line(X(t), YD(d), X(tn), YD(d), DOWN, 2)
    cv.text(padL, bot0 - 24, f"DRAWDOWN % (THEO LENH DONG)  THAP NHAT {dmin:.2f}%", AXIS, 2)

    # ---- trục thời gian (giờ VN)
    nx = 6
    for j in range(nx + 1):
        tt = t0 + (t1 - t0) * j / nx
        x = X(tt)
        cv.line(x, bot1, x, bot1 + 6, AXIS)
        lab = datetime.fromtimestamp(tt, VN).strftime("%Y-%m-%d")
        al = "left" if j == 0 else ("right" if j == nx else "center")
        cv.text(x, bot1 + 14, lab, AXIS, 2, al)
    return cv.png()
