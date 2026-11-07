# -*- coding: utf-8 -*-
"""
[2026-11-07] Ghi file Excel (.xlsx) tối giản, không cần thư viện ngoài (openpyxl không có trên VPS).
Mỗi sheet là danh sách dòng; ô là số (int/float) hoặc chữ. Dòng đầu mỗi sheet in đậm.
"""

from __future__ import annotations

import io
import math
import zipfile
from xml.sax.saxutils import escape


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref: str, v, bold: bool) -> str:
    style = ' s="1"' if bold else ""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return ""
    if isinstance(v, bool):
        v = "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"{style}><v>{v}</v></c>'
    text = escape(str(v)).replace('"', "&quot;")
    return f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet_xml(rows, widths=None) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">',
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '</sheetView></sheetViews>']
    if widths:
        out.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(rows):
        cells = "".join(_cell(f"{_col(c)}{r + 1}", v, r == 0) for c, v in enumerate(row))
        out.append(f'<row r="{r + 1}">{cells}</row>')
    out.append("</sheetData></worksheet>")
    return "".join(out)


def build_xlsx(sheets: list) -> bytes:
    """sheets: [(tên sheet, rows, widths|None), ...] → nội dung file .xlsx."""
    buf = io.BytesIO()
    names = [str(n)[:31] for n, _, _ in sheets]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                   "</Relationships>")
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names))
                   + "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i + 1}" '
                             'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                             f'Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(sheets)))
                   + f'<Relationship Id="rId{len(sheets) + 1}" '
                     'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                   "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   "</styleSheet>")
        for i, (_, rows, widths) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows, widths))
    return buf.getvalue()


# ---------------------------------------------------------------- kết quả backtest web → Excel
TRADE_COLUMNS = [
    ("STT", None), ("Side", "side"), ("Vào lúc", "entry_time"), ("Giá vào", "entry_price"),
    ("Ra lúc", "exit_time"), ("Giá ra", "exit_price"), ("Size", "size"), ("Margin", "margin"),
    ("Phí vào", "fee_in"), ("Profit (đã trừ phí ra)", "profit"), ("Profit ròng", None),
    ("% vốn", None), ("Vốn trước", "capital_before"), ("Vốn sau", "capital_after"),
    ("Lý do thoát", "exit_reason"), ("RSI vào", "entry_rsi"), ("RSI ra", "exit_rsi"),
    ("Chu kỳ ngày (PP5)", "cycle"), ("Thoát nới (PP5)", "cycle_wide"),
]


def _time(v):
    """Thời gian → chuỗi giờ VN 'YYYY-MM-DD HH:MM'."""
    if not v:
        return ""
    try:
        import pandas as pd

        t = pd.Timestamp(v)
        if t.tzinfo is not None:
            t = t.tz_convert("Asia/Bangkok")
        return t.strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return str(v).replace("T", " ")[:16]


def backtest_stats(result: dict) -> list:
    """Danh sách (tên, giá trị) thống kê ngắn — dùng cho sheet Excel."""
    tr = result.get("trades") or []
    cap0 = float(result.get("initial_capital") or 0)
    net = [float(t.get("profit") or 0) - float(t.get("fee_in") or 0) for t in tr]
    wins = [x for x in net if x > 0]
    losses = [x for x in net if x <= 0]
    streak = cur = 0
    for x in net:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    final = float(result.get("final_balance") or 0)
    rows = [
        ("Cặp", result.get("symbol")), ("Phương pháp", f"PP{result.get('method')}"),
        ("Từ", _time(result.get("start"))), ("Đến", _time(result.get("end"))),
        ("Vốn ban đầu", round(cap0, 2)), ("Vốn cuối", round(final, 2)),
        ("Lời/lỗ (USDT)", round(final - cap0, 2)),
        ("Lời/lỗ (%)", round((final / cap0 - 1) * 100, 2) if cap0 else None),
        ("Số lệnh", len(tr)), ("Thắng / thua", f"{len(wins)} / {len(losses)}"),
        ("Winrate (%)", result.get("winrate")),
        ("Lệnh LONG / SHORT", f"{sum(1 for t in tr if t.get('side') == 'LONG')} / {sum(1 for t in tr if t.get('side') == 'SHORT')}"),
        ("Lãi TB lệnh thắng", round(sum(wins) / len(wins), 2) if wins else None),
        ("Lỗ TB lệnh thua", round(sum(losses) / len(losses), 2) if losses else None),
        ("Profit factor", round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None),
        ("Chuỗi thua dài nhất", streak),
        ("Drawdown lớn nhất (%)", result.get("max_drawdown_pct")),
    ]
    for k, v in sorted((result.get("exit_reasons") or {}).items()):
        rows.append((f"Thoát: {k}", v))
    return rows


def backtest_result_xlsx(result: dict) -> bytes:
    stats = [("Chỉ số", "Giá trị")] + backtest_stats(result)
    head = [c for c, _ in TRADE_COLUMNS]
    rows = [head]
    for i, t in enumerate(result.get("trades") or [], 1):
        cb = float(t.get("capital_before") or 0)
        netp = float(t.get("profit") or 0) - float(t.get("fee_in") or 0)
        row = []
        for name, key in TRADE_COLUMNS:
            if name == "STT":
                row.append(i)
            elif name == "Profit ròng":
                row.append(round(netp, 6))
            elif name == "% vốn":
                row.append(round(netp / cb * 100, 4) if cb else None)
            elif key in ("entry_time", "exit_time"):
                row.append(_time(t.get(key)))
            else:
                row.append(t.get(key))
        rows.append(row)
    widths = [6, 7, 20, 12, 20, 12, 12, 10, 9, 14, 12, 9, 12, 12, 18, 9, 9, 16, 12]
    return build_xlsx([("Thống kê", stats, [26, 26]), ("Lệnh", rows, widths)])
