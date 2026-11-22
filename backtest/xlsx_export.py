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


def _sheet_xml(rows, widths=None, opts=None) -> str:
    """opts (tuỳ chọn): bold_rows = tập chỉ số dòng in đậm (mặc định {0}), freeze = cố định dòng đầu (mặc định True),
    drawing = có ảnh (thêm <drawing r:id="rId1"/>)."""
    opts = opts or {}
    bold_rows = opts.get("bold_rows", {0})
    pane = ('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            if opts.get("freeze", True) else "")
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
           'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
           f'<sheetViews><sheetView workbookViewId="0">{pane}</sheetView></sheetViews>']
    if widths:
        out.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    for r, row in enumerate(rows):
        cells = "".join(_cell(f"{_col(c)}{r + 1}", v, r in bold_rows) for c, v in enumerate(row))
        out.append(f'<row r="{r + 1}">{cells}</row>')
    out.append("</sheetData>")
    if opts.get("image"):
        out.append('<drawing r:id="rId1"/>')
    out.append("</worksheet>")
    return "".join(out)


def _drawing_xml(img: dict) -> str:
    """Ảnh PNG neo tại ô (row, col) (đếm từ 0), kích thước theo pixel (1 px = 9525 EMU)."""
    cx, cy = int(img["w"]) * 9525, int(img["h"]) * 9525
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<xdr:oneCellAnchor><xdr:from><xdr:col>{img.get("col", 0)}</xdr:col><xdr:colOff>0</xdr:colOff>'
            f'<xdr:row>{img.get("row", 0)}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
            f'<xdr:ext cx="{cx}" cy="{cy}"/>'
            '<xdr:pic><xdr:nvPicPr><xdr:cNvPr id="2" name="Bieu do PnL"/><xdr:cNvPicPr><a:picLocks noChangeAspect="1"/>'
            '</xdr:cNvPicPr></xdr:nvPicPr><xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch>'
            f'</xdr:blipFill><xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr></xdr:pic><xdr:clientData/></xdr:oneCellAnchor>'
            '</xdr:wsDr>')


def build_xlsx(sheets: list) -> bytes:
    """sheets: [(tên sheet, rows, widths|None[, opts]), ...] → nội dung file .xlsx.
    opts xem _sheet_xml; opts["image"] = {"png": bytes, "w": px, "h": px, "row": 0, "col": 0} để chèn ảnh."""
    sheets = [tuple(sh) + (None,) * (4 - len(sh)) for sh in sheets]
    buf = io.BytesIO()
    names = [str(n)[:31] for n, _, _, _ in sheets]
    imgs = [(i, (sh[3] or {}).get("image")) for i, sh in enumerate(sheets)]
    imgs = [(i, im) for i, im in imgs if im]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Default Extension="png" ContentType="image/png"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                             for i in range(len(sheets)))
                   + "".join(f'<Override PartName="/xl/drawings/drawing{k + 1}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
                             for k in range(len(imgs)))
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
        for i, (_, rows, widths, opts) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet_xml(rows, widths, opts))
        for k, (i, im) in enumerate(imgs):
            z.writestr(f"xl/worksheets/_rels/sheet{i + 1}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" '
                       f'Target="../drawings/drawing{k + 1}.xml"/></Relationships>')
            z.writestr(f"xl/drawings/drawing{k + 1}.xml", _drawing_xml(im))
            z.writestr(f"xl/drawings/_rels/drawing{k + 1}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
                       f'Target="../media/image{k + 1}.png"/></Relationships>')
            z.writestr(f"xl/media/image{k + 1}.png", im["png"])
    return buf.getvalue()


# ---------------------------------------------------------------- kết quả backtest web → Excel
TRADE_COLUMNS = [
    ("STT", None), ("Side", "side"), ("Vào lúc", "entry_time"), ("Giá vào", "entry_price"),
    ("Ra lúc", "exit_time"), ("Giá ra", "exit_price"), ("Size", "size"), ("Margin", "margin"),
    ("Phí vào", "fee_in"), ("Profit (đã trừ phí ra)", "profit"), ("Profit ròng", None),
    ("% vốn", None), ("Vốn trước", "capital_before"), ("Vốn sau", "capital_after"),
    ("Lý do thoát", "exit_reason"), ("RSI vào", "entry_rsi"), ("RSI ra", "exit_rsi"),
    ("Chu kỳ ngày (PP5)", "cycle"), ("Thoát nới (PP5)", "cycle_wide"), ("Ngược chu kỳ (PP5)", "cycle_counter"),
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
        ("Cặp", result.get("symbol")), ("Phương pháp", result.get("label") or f"PP{result.get('method')}"),
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
    for k, v in sorted((result.get("overrides") or {}).items()):
        rows.append((f"Tham số: {k}", v))
    for k, v in sorted((result.get("exit_reasons") or {}).items()):
        rows.append((f"Thoát: {k}", v))
    return rows


def _vn_time(epoch) -> str:
    """Giây epoch → 'YYYY-MM-DD HH:MM' giờ VN."""
    import datetime as _dt

    try:
        return _dt.datetime.fromtimestamp(float(epoch), _dt.timezone(_dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _safe(v) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9.-]+", "-", str(v or "")).strip("-") or "x"


def backtest_filename(result: dict, meta: dict | None = None, job_id: str | None = None) -> str:
    """[2026-11-22] Quy tắc đặt tên file Excel backtest (giống nhau cho tải lẻ và tải ZIP):
    <Chiến lược>_<Cặp>_<từ ngày>_den_<đến ngày>[_thamso]_chay-<YYYYMMDD-HHMM giờ VN>_<6 ký tự mã>.xlsx
    ví dụ PP4_BTCUSDT_2026-01-01_den_2026-10-01_chay-20261122-1459_ab12cd.xlsx
    "_thamso" có khi lần chạy dùng tham số thử (khác .env/đĩa)."""
    meta = meta or {}
    label = _safe(result.get("label") or meta.get("label") or f"PP{result.get('method') or meta.get('method')}")
    day = lambda v: (_time(v) or "")[:10] or "x"  # ngày theo giờ VN, khớp sheet Tổng quan
    run = _vn_time(meta.get("saved_at")) if meta.get("saved_at") else ""
    run = run.replace("-", "").replace(" ", "-").replace(":", "") if run else ""
    parts = [label, _safe(result.get("symbol")), day(result.get("start")), "den", day(result.get("end"))]
    if result.get("overrides"):
        parts.append("thamso")
    if run:
        parts.append("chay-" + run)
    if job_id:
        parts.append(_safe(job_id)[:6])
    return "_".join(parts) + ".xlsx"


def overview_rows(result: dict, meta: dict | None = None, job_id: str | None = None) -> tuple:
    """Sheet 'Tổng quan': thông tin lần chạy + kết quả chính + tham số thử + lý do thoát. Trả (rows, bold_rows)."""
    meta = meta or {}
    rows, bold = [], set()

    def section(title):
        if rows:
            rows.append(())
        bold.add(len(rows))
        rows.append((title, ""))

    bold.add(0)
    rows.append(("TỔNG QUAN BACKTEST", ""))
    rows.append(("Tên file", backtest_filename(result, meta, job_id)))
    section("Thông tin lần chạy")
    info = [
        ("Chiến lược", result.get("label") or f"PP{result.get('method')}"),
        ("Tên đĩa", result.get("disk_name") or meta.get("disk_name") or ""),
        ("Mã chiến lược", str(result.get("method") or meta.get("method") or "")),
        ("Cặp", result.get("symbol")),
        ("Từ (giờ VN)", _time(result.get("start"))), ("Đến (giờ VN)", _time(result.get("end"))),
        ("Lúc chạy (giờ VN)", _vn_time(meta["saved_at"]) if meta.get("saved_at") else ""),
        ("Mã kết quả", job_id or meta.get("id") or ""),
        ("Vốn ban đầu (USDT)", round(float(result.get("initial_capital") or 0), 2)),
        ("Đòn bẩy", meta.get("leverage") if meta.get("leverage") is not None else result.get("leverage")),
        ("% vốn mỗi lệnh", meta.get("wallet_pct") if meta.get("wallet_pct") is not None else result.get("wallet_pct")),
        ("Thời gian chạy (giây)", result.get("elapsed_sec") or meta.get("elapsed_sec")),
    ]
    rows += [r for r in info if r[1] not in (None, "")]  # bỏ dòng không có dữ liệu
    section("Kết quả")
    stats = backtest_stats(result)
    skip = {"Cặp", "Phương pháp", "Từ", "Đến", "Vốn ban đầu"}
    rows += [(k, v) for k, v in stats if k not in skip and not k.startswith(("Tham số:", "Thoát:"))]
    section("Tham số thử (chỉ cho lần chạy này)")
    ov = result.get("overrides") or {}
    rows += [(k, ov[k]) for k in sorted(ov)] or [("(không có)", "dùng tham số của đĩa / .env")]
    section("Lý do thoát lệnh (số lệnh)")
    er = result.get("exit_reasons") or {}
    rows += [(k, er[k]) for k in sorted(er)] or [("(không có lệnh)", "")]
    section("Ghi chú")
    rows += [
        ("Sheet 'Biểu đồ PnL'", "Vốn theo thời gian (bậc thang theo lệnh đóng) + drawdown theo lệnh đóng"),
        ("Sheet 'Lệnh'", "Chi tiết từng lệnh, giờ VN"),
        ("Drawdown lớn nhất", "Tính trong lúc phát lại (kể cả lệnh đang mở) nên có thể sâu hơn drawdown trên biểu đồ"),
        ("Lưu ý", "Chỉ là mô phỏng trên nến lịch sử, không đặt lệnh thật"),
    ]
    return rows, bold


def chart_sheet(result: dict) -> tuple:
    """Sheet 'Biểu đồ PnL': 2 dòng chữ + ảnh PNG từ dòng 4."""
    from backtest.chart_png import pnl_chart_png

    w, h = 1400, 820
    png = pnl_chart_png(result, w, h)
    rows = [("Biểu đồ PnL — " + str(result.get("label") or f"PP{result.get('method')}") + " · " + str(result.get("symbol") or "")
             + " · " + _time(result.get("start"))[:10] + " → " + _time(result.get("end"))[:10], ),
            ("Trên: vốn (USDT) sau mỗi lệnh đóng, đường đứt = vốn ban đầu. Dưới: drawdown % so với đỉnh vốn trước đó.", )]
    return ("Biểu đồ PnL", rows, [120], {"freeze": False, "image": {"png": png, "w": int(w * .72), "h": int(h * .72), "row": 3, "col": 0}})


def backtest_result_xlsx(result: dict, meta: dict | None = None, job_id: str | None = None) -> bytes:
    """[2026-11-22] File Excel kết quả backtest: Tổng quan, Biểu đồ PnL (ảnh), Lệnh."""
    ov, bold = overview_rows(result, meta, job_id)
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
    widths = [6, 7, 20, 12, 20, 12, 12, 10, 9, 14, 12, 9, 12, 12, 18, 9, 9, 16, 12, 12]
    return build_xlsx([("Tổng quan", ov, [30, 60], {"bold_rows": bold, "freeze": False}), chart_sheet(result),
                       ("Lệnh", rows, widths)])


def summary_xlsx(entries: list) -> bytes:
    """[2026-11-22] File tổng hợp trong ZIP: mỗi dòng một kết quả đã chọn + quy tắc đặt tên."""
    head = ["Tên file", "Chiến lược", "Cặp", "Từ", "Đến", "Lúc chạy (giờ VN)", "Vốn đầu", "Vốn cuối", "Lời/lỗ USDT",
            "Lời/lỗ %", "DD max %", "Số lệnh", "Winrate %", "Profit factor", "Chuỗi thua", "Tham số thử"]
    rows = [head]
    for fname, res, meta in entries:
        st = dict(backtest_stats(res))
        ov = res.get("overrides") or {}
        rows.append([fname, res.get("label") or f"PP{res.get('method')}", res.get("symbol"), _time(res.get("start"))[:10],
                     _time(res.get("end"))[:10], _vn_time(meta.get("saved_at")) if meta.get("saved_at") else "",
                     round(float(res.get("initial_capital") or 0), 2), round(float(res.get("final_balance") or 0), 2),
                     st.get("Lời/lỗ (USDT)"), st.get("Lời/lỗ (%)"), res.get("max_drawdown_pct"), st.get("Số lệnh"),
                     res.get("winrate"), st.get("Profit factor"), st.get("Chuỗi thua dài nhất"),
                     " ".join(f"{k}={ov[k]}" for k in sorted(ov))])
    rule = [("Quy tắc đặt tên file", ""),
            ("Mẫu", "<Chiến lược>_<Cặp>_<từ ngày>_den_<đến ngày>[_thamso]_chay-<YYYYMMDD-HHMM>_<mã>.xlsx"),
            ("Ví dụ", "PP4_BTCUSDT_2026-01-01_den_2026-10-01_chay-20261122-1459_ab12cd.xlsx"),
            ("_thamso", "Có khi lần chạy dùng tham số thử (khác .env / đĩa)"),
            ("chay-...", "Thời điểm chạy backtest, giờ Việt Nam"),
            ("<mã>", "6 ký tự đầu mã kết quả, để hai lần chạy giống nhau không trùng tên"),
            ("Mỗi file gồm", "Tổng quan · Biểu đồ PnL (ảnh) · Lệnh")]
    widths = [62, 12, 12, 11, 11, 17, 10, 10, 12, 10, 10, 9, 11, 12, 11, 40]
    return build_xlsx([("Tổng hợp", rows, widths), ("Quy tắc đặt tên", rule, [22, 90], {"freeze": False})])
