# -*- coding: utf-8 -*-
"""
[2026-11-21] "Hộp và đĩa": mỗi chiến lược là một ĐĨA (file .md), web + bot là cái HỘP dùng chung
(dữ liệu, paper trade, backtest, Telegram, giao diện).

Một đĩa KHÔNG chứa code chạy được. Nó chỉ là phần khai báo (front matter giữa hai dòng `---` ở đầu file):

    ---
    disk: 1                 # phiên bản định dạng
    id: pp7-risk1           # mã đĩa: chữ thường, số, - _ (đĩa có sẵn của repo dùng "1".."7", "6.1")
    name: PP7 rủi ro 1%     # tên hiển thị
    description: ...        # một câu mô tả
    base: pp4               # khung lõi có sẵn: pp1 | pp2 | pp3 | pp4
    blocks:                 # khối bật thêm (chỉ ghép được trên khung pp4)
      trend_filter_always: true
      risk_sizing: true
      stop_atr_4h: true
    params:                 # tham số riêng cho đĩa này (tên giống .env); không ghi = lấy theo .env
      M7_RISK_PCT: 0.01
    ---
    # Phần còn lại là Markdown giải thích (chỉ để đọc, không chạy)

Hộp đọc đĩa bằng một bộ phân tích YAML rút gọn (chỉ map / số / chữ / true-false / danh sách ngắn),
kiểm tra từng khoá theo SCHEMA bên dưới; sai một chỗ là từ chối cả đĩa. Mọi logic chạy vẫn là code trong repo
(strategy/*, bot/slot_engine.py, backtest/live_replay.py) — đĩa chỉ chọn khối nào bật và tham số nào.
Muốn khối thật sự MỚI thì vẫn cần một lần merge code qua GitHub, kèm đĩa .md mới.

Đĩa có sẵn: strategies/*.md trong repo (PP1–PP7, PP6.1) — chính là các phương pháp cũ, chạy y hệt.
Đĩa nạp từ web: data/strategies/<id>.md (gitignored) — chỉ chạy paper/backtest, không tự lên live.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import threading
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

from config import settings

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_DIR = ROOT / "strategies"
UPLOAD_DIR = ROOT / "data" / "strategies"
FORMAT_VERSION = 1
MAX_DISK_BYTES = 64 * 1024

BASES = {
    "pp1": "Khung PP1: vào theo RSI/EMA/WMA 4H; thoát 4H + early + ATR trailing 1H + trần lỗ",
    "pp2": "Khung PP2: như PP1 nhưng thoát 4H/early chỉ khi đang lãi và RSI 1H đảo chiều; chốt lời dải %change",
    "pp3": "Khung PP3: Exit B, lọc EMA50 khi ADX>30, vùng ADX, swing, size theo chuỗi thua, circuit breaker",
    "pp4": "Khung PP4: PP3 + Exit B thay early, hard stop % vốn, xác nhận RSI 1H, chặn RSI cực trị, ADX exhaustion",
}

# khối → (mô tả, các khối bắt buộc phải bật kèm)
BLOCKS = {
    "regime_cut": ("Nhận diện giai đoạn ER+EMA50 và cắt lỗ sớm của PP4 (bật bằng tham số M4_REGIME_ENABLED, "
                   "M4_INVALIDATION_EXIT, M4_TIME_STOP, M4_SMOOTH_GRACE; mặc định tắt)", ()),
    "daily_cycle": ("Lọc chu kỳ nến ngày của PP5: tăng chỉ LONG, giảm chỉ SHORT, đi ngang thì thoát nới", ()),
    "cvd": ("CVD của PP6: CVD 4H phải cùng chiều lệnh; CVD 1H đi ngược thì siết trailing "
            "(ghép với daily_cycle = PP6.1: đi ngang chọn phía theo CVD)", ()),
    "trend_filter_always": ("Lọc trend của PP7: LONG chỉ khi giá đóng 4H trên EMA50, SHORT khi dưới (bất kể ADX)", ()),
    "stop_atr_4h": ("Stop + trailing = M7_ATR4H_MULT × ATR nến 4H lúc vào lệnh, không siết sau 12h (PP7)", ()),
    "risk_sizing": ("Size theo rủi ro của PP7: chạm stop ban đầu chỉ mất M7_RISK_PCT vốn", ("stop_atr_4h",)),
}

# Tham số được phép ghi đè trong đĩa: tên .env (đã có trong config/settings.py) với các tiền tố sau.
_PARAM_PREFIXES = ("M3_", "M4_", "M5_", "M6_", "M61_", "M7_")
_PARAM_EXTRA = ("ATR_MULTIPLIER", "MAX_STOP_CAPITAL_PCT", "RSI_EARLY_EXIT", "RSI_LONG_CUT", "RSI_SHORT_CUT")
# Tham số chỉ báo dùng chung cho mọi phương pháp trên cùng một cặp (tính một lần, có lưu đệm) → không đổi theo đĩa
FIXED_PARAMS = {"M3_EMA_TREND_LEN", "M3_SWING_LOOKBACK", "M5_DAILY_KLINES"}
PARAM_ENUMS = {
    "M5_SIDEWAYS_MODE": ("atr", "pct"),
    "M5_SIDEWAYS_MIXED": ("latest", "both", "skip"),
    "M5_EXIT_B": ("wide", "all", "off"),
    "M6_EXIT_MODE": ("tighten", "close", "off"),
    "M61_SIDEWAYS_BIAS": ("cvd", "close", "both"),
    "M7_EXIT_B": ("off", "fixed"),
}
# Thành phần của đĩa có sẵn được chốt cứng trong code: file strategies/*.md hỏng / mất / bị sửa khối
# cũng không làm PP1–PP5 đang chạy paper/live đổi cách vào ra lệnh (dùng bản trong code và ghi lỗi).
BUILTIN_SPEC = {
    "1": ("pp1", ()),
    "2": ("pp2", ()),
    "3": ("pp3", ()),
    "4": ("pp4", ("regime_cut",)),
    "5": ("pp4", ("daily_cycle",)),
    "6": ("pp4", ("cvd",)),
    "6.1": ("pp4", ("daily_cycle", "cvd")),
    "7": ("pp4", ("trend_filter_always", "stop_atr_4h", "risk_sizing")),
}
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_BUILTIN_ID_RE = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_TOP_KEYS = {"disk", "id", "name", "short", "description", "base", "blocks", "params", "author", "created"}


class DiskError(ValueError):
    """Đĩa không hợp lệ (thông báo tiếng Việt, hiện thẳng cho người dùng)."""


# ---------------------------------------------------------------------------
# YAML rút gọn (an toàn: không có tag, không có anchor, không gọi hàm nào)
# ---------------------------------------------------------------------------
def _strip_comment(line: str) -> str:
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(s: str, lineno: int):
    s = s.strip()
    if s == "":
        return None
    if (s[0] == s[-1]) and s[0] in "\"'" and len(s) >= 2:
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [] if not inner else [_scalar(x, lineno) for x in inner.split(",")]
    if s[0] in "{&*!|>@`%":
        raise DiskError(f"Dòng {lineno}: giá trị '{s[:30]}' không được hỗ trợ (chỉ số, chữ, true/false)")
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~", "none"):
        return None
    try:
        if re.fullmatch(r"[+-]?\d+", s):
            return int(s)
        if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", s):
            return float(s)
    except ValueError:
        pass
    return s


def parse_mini_yaml(text: str) -> dict:
    root: dict = {}
    stack = [(-1, root)]
    for lineno, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise DiskError(f"Dòng {lineno}: dùng dấu cách để thụt lề, không dùng tab")
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if body.startswith("- "):
            raise DiskError(f"Dòng {lineno}: danh sách dạng '- ...' chưa hỗ trợ, dùng [a, b]")
        if ":" not in body:
            raise DiskError(f"Dòng {lineno}: thiếu dấu ':' (dạng khoá: giá trị)")
        key, _, val = body.partition(":")
        key = key.strip().strip("\"'")
        if not key:
            raise DiskError(f"Dòng {lineno}: khoá rỗng")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise DiskError(f"Dòng {lineno}: thụt lề không hợp lệ")
        parent = stack[-1][1]
        if key in parent:
            raise DiskError(f"Dòng {lineno}: khoá '{key}' bị lặp")
        if val.strip() == "":
            if len(stack) > 3:
                raise DiskError(f"Dòng {lineno}: lồng quá sâu")
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(val, lineno)
    return root


def split_front_matter(text: str):
    """(front_matter_text, markdown_body). Front matter = giữa dòng '---' đầu tiên và dòng '---' kế tiếp."""
    t = text.lstrip("﻿")
    lines = t.splitlines()
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        raise DiskError("Đĩa phải bắt đầu bằng dòng '---', rồi phần khai báo, rồi một dòng '---' nữa")
    for j in range(i + 1, len(lines)):
        if lines[j].strip() == "---":
            return "\n".join(lines[i + 1: j]), "\n".join(lines[j + 1:]).strip("\n")
    raise DiskError("Thiếu dòng '---' đóng phần khai báo")


# ---------------------------------------------------------------------------
# Tham số
# ---------------------------------------------------------------------------
def param_schema() -> dict:
    """{tên: {"type": bool|int|float|str, "default": giá trị .env hiện tại, "enum": (...)?}}"""
    out = {}
    for name in dir(settings):
        if not (name.startswith(_PARAM_PREFIXES) or name in _PARAM_EXTRA) or name in FIXED_PARAMS:
            continue
        v = getattr(settings, name)
        if isinstance(v, bool):
            t = bool
        elif isinstance(v, int):
            t = int
        elif isinstance(v, float):
            t = float
        elif isinstance(v, str):
            t = str
        else:
            continue
        d = {"type": t, "default": v}
        if name in PARAM_ENUMS:
            d["enum"] = PARAM_ENUMS[name]
        out[name] = d
    return out


def _check_param(name, value, schema):
    if name in FIXED_PARAMS:
        raise DiskError(f"Tham số {name} là tham số chỉ báo dùng chung, không đổi riêng cho đĩa được")
    sc = schema.get(name)
    if sc is None:
        raise DiskError(f"Tham số '{name}' không có trong danh sách cho phép")
    t = sc["type"]
    if t is bool:
        if not isinstance(value, bool):
            raise DiskError(f"{name} phải là true/false")
        return value
    if t is str:
        if not isinstance(value, str):
            raise DiskError(f"{name} phải là chữ" + (f" ({', '.join(sc['enum'])})" if "enum" in sc else ""))
        value = value.strip().lower()
        if "enum" in sc and value not in sc["enum"]:
            raise DiskError(f"{name} chỉ nhận: {', '.join(sc['enum'])}")
        if len(value) > 32:
            raise DiskError(f"{name} quá dài")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DiskError(f"{name} phải là số")
    if t is int:
        if isinstance(value, float) and not value.is_integer():
            raise DiskError(f"{name} phải là số nguyên")
        value = int(value)
        if not (0 <= value <= 100000):
            raise DiskError(f"{name} ngoài khoảng cho phép (0..100000)")
        return value
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1e6:
        raise DiskError(f"{name} không hợp lệ")
    if (name.endswith("_PCT") and "CAPITAL" in name or name == "M7_RISK_PCT") and not (0 < value <= 1):
        raise DiskError(f"{name} là tỉ lệ (0..1], ví dụ 0.02 = 2%")
    if ("MULT" in name or "SIZE" in name) and value < 0:
        raise DiskError(f"{name} không được âm")
    return value


# ---------------------------------------------------------------------------
# Đĩa
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Disk:
    id: str
    name: str
    description: str
    base: str
    blocks: frozenset
    params: dict = field(default_factory=dict, hash=False, compare=False)
    short: str = ""
    source: str = "builtin"  # builtin | upload
    body: str = ""
    text: str = ""
    sha: str = ""
    author: str = ""
    created: str = ""

    # --- khung ---
    @property
    def pp2(self) -> bool:
        return self.base == "pp2"

    @property
    def m3(self) -> bool:  # circuit breaker, vùng ADX, EMA50/swing/streak, Exit B
        return self.base in ("pp3", "pp4")

    @property
    def pp3_only(self) -> bool:
        return self.base == "pp3"

    @property
    def m4(self) -> bool:
        return self.base == "pp4"

    # --- khối ---
    def has(self, block: str) -> bool:
        return block in self.blocks

    @property
    def regime(self) -> bool:
        return "regime_cut" in self.blocks

    @property
    def daily(self) -> bool:
        return "daily_cycle" in self.blocks

    @property
    def cvd(self) -> bool:
        return "cvd" in self.blocks

    @property
    def trend_always(self) -> bool:
        return "trend_filter_always" in self.blocks

    @property
    def stop4h(self) -> bool:
        return "stop_atr_4h" in self.blocks

    @property
    def risk_sizing(self) -> bool:
        return "risk_sizing" in self.blocks

    @property
    def pp7_any(self) -> bool:
        return bool(self.blocks & {"trend_filter_always", "stop_atr_4h", "risk_sizing"})

    @property
    def label(self) -> str:
        """Nhãn ngắn trong bảng kết quả: PP4, PP6.1, hoặc mã đĩa nạp từ web."""
        return self.short or (f"PP{self.id}" if _BUILTIN_ID_RE.match(self.id) else self.id)

    def applied(self):
        """Context manager: trong khối with, settings đọc tham số riêng của đĩa (đĩa không ghi đè → không làm gì)."""
        return settings.overrides(self.params) if self.params else nullcontext()

    def needs(self) -> dict:
        """Dữ liệu thêm mà hộp phải tải cho đĩa này."""
        return {"daily": self.daily, "taker": self.cvd}

    def to_public(self) -> dict:
        return {
            "id": self.id, "name": self.name, "short": self.label, "description": self.description,
            "base": self.base, "base_text": BASES.get(self.base, ""),
            "blocks": sorted(self.blocks), "blocks_text": {b: BLOCKS[b][0] for b in sorted(self.blocks)},
            "params": dict(self.params), "source": self.source, "sha": self.sha[:12],
            "author": self.author, "created": self.created, "needs": self.needs(),
        }


def parse_disk(text: str, source: str = "upload") -> Disk:
    if not isinstance(text, str):
        raise DiskError("Nội dung đĩa phải là văn bản")
    if len(text.encode("utf-8")) > MAX_DISK_BYTES:
        raise DiskError(f"Đĩa quá lớn (tối đa {MAX_DISK_BYTES // 1024} KB)")
    fm, body = split_front_matter(text)
    if re.search(r"<\s*script|javascript:|<[a-z][^>]*\son\w+\s*=", text, re.I):
        raise DiskError("Đĩa không được chứa HTML/JavaScript")
    if re.search(r"^\s*```\s*(py|python|js|javascript|sh|bash)\b", body, re.I | re.M):
        raise DiskError("Đĩa không được chứa code chạy được (khối ```python/js/sh```). Chỉ khai báo khối + tham số")
    meta = parse_mini_yaml(fm)
    unknown = set(meta) - _TOP_KEYS
    if unknown:
        raise DiskError(f"Khoá không hợp lệ: {', '.join(sorted(unknown))}")
    if meta.get("disk") != FORMAT_VERSION:
        raise DiskError(f"Thiếu hoặc sai 'disk: {FORMAT_VERSION}' (phiên bản định dạng)")
    did = meta.get("id")
    did = str(did) if isinstance(did, (int, float)) and not isinstance(did, bool) else did
    if not isinstance(did, str) or not did.strip():
        raise DiskError("Thiếu 'id'")
    did = did.strip().lower()
    if source == "builtin":
        if not (_BUILTIN_ID_RE.match(did) or _ID_RE.match(did)):
            raise DiskError(f"id '{did}' không hợp lệ")
    elif not _ID_RE.match(did):
        raise DiskError("id phải bắt đầu bằng chữ cái, chỉ gồm a-z 0-9 - _ (2–32 ký tự), ví dụ: pp7-risk1")
    name = meta.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise DiskError("Thiếu 'name' (tối đa 80 ký tự)")
    desc = meta.get("description") or ""
    if not isinstance(desc, str) or len(desc) > 500:
        raise DiskError("'description' phải là một câu (tối đa 500 ký tự)")
    short = meta.get("short") or ""
    if not isinstance(short, str) or len(short) > 16:
        raise DiskError("'short' tối đa 16 ký tự")
    base = str(meta.get("base") or "").strip().lower()
    if base not in BASES:
        raise DiskError(f"'base' phải là một trong: {', '.join(BASES)}")
    blocks_raw = meta.get("blocks") or {}
    if not isinstance(blocks_raw, dict):
        raise DiskError("'blocks' phải là danh sách khoá: true/false")
    blocks = set()
    for b, on in blocks_raw.items():
        if b not in BLOCKS:
            raise DiskError(f"Khối '{b}' chưa có trong hộp (có: {', '.join(BLOCKS)}). Khối mới cần merge code qua GitHub")
        if not isinstance(on, bool):
            raise DiskError(f"Khối {b}: chỉ nhận true/false")
        if on:
            blocks.add(b)
    if blocks and base != "pp4":
        raise DiskError("Các khối thêm chỉ ghép được trên base: pp4")
    for b in blocks:
        for req in BLOCKS[b][1]:
            if req not in blocks:
                raise DiskError(f"Khối {b} cần bật kèm {req}")
    params_raw = meta.get("params") or {}
    if not isinstance(params_raw, dict):
        raise DiskError("'params' phải là danh sách TÊN: giá trị")
    schema = param_schema()
    params = {str(k).strip().upper(): _check_param(str(k).strip().upper(), v, schema) for k, v in params_raw.items()}
    if len(params) > 60:
        raise DiskError("Quá nhiều tham số (tối đa 60)")
    return Disk(
        id=did, name=name.strip(), description=desc.strip(), base=base, blocks=frozenset(blocks),
        params=params, short=short.strip(), source=source, body=body, text=text,
        sha=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        author=str(meta.get("author") or "")[:60], created=str(meta.get("created") or "")[:30],
    )


# ---------------------------------------------------------------------------
# Kho đĩa
# ---------------------------------------------------------------------------
_lock = threading.RLock()
_cache = {"disks": None, "stamp": None}


def _dir_stamp():
    parts = []
    for d in (BUILTIN_DIR, UPLOAD_DIR):
        try:
            for p in sorted(d.glob("*.md")):
                st = p.stat()
                parts.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(parts)


def _load_all() -> dict:
    disks, errors = {}, {}
    for src, d in (("builtin", BUILTIN_DIR), ("upload", UPLOAD_DIR)):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if p.name.lower() == "readme.md":
                continue
            try:
                disk = parse_disk(p.read_text(encoding="utf-8"), source=src)
            except Exception as e:  # noqa: BLE001 — đĩa hỏng không được làm sập bot
                errors[p.name] = str(e)
                continue
            if src == "upload" and (disk.id in BUILTIN_SPEC or _BUILTIN_ID_RE.match(disk.id)):
                errors[p.name] = f"id '{disk.id}' dành cho đĩa có sẵn"
                continue
            if disk.id in disks:
                errors[p.name] = f"id '{disk.id}' trùng với đĩa đã có"
                continue
            disks[disk.id] = disk
    for bid, (base, blocks) in BUILTIN_SPEC.items():
        d = disks.get(bid)
        ok = d is not None and d.source == "builtin" and d.base == base and d.blocks == frozenset(blocks) and not d.params
        if not ok:
            if d is not None:
                errors[f"{bid}"] = "đĩa có sẵn khác thành phần chốt trong code → dùng bản trong code"
            disks[bid] = Disk(id=bid, name=(d.name if d else f"PP{bid}"), description=(d.description if d else ""),
                              base=base, blocks=frozenset(blocks), source="builtin", body=(d.body if d else ""),
                              text=(d.text if d else ""), sha=(d.sha if d else ""))
    _cache["errors"] = errors
    return disks


def all_disks() -> dict:
    """{id: Disk}. Đọc lại khi thư mục đĩa thay đổi (nạp/xoá trên web có hiệu lực ngay, không cần restart)."""
    with _lock:
        stamp = _dir_stamp()
        if _cache["disks"] is None or stamp != _cache["stamp"]:
            _cache["disks"] = _load_all()
            _cache["stamp"] = stamp
            _by_id_fast.clear()
        return _cache["disks"]


def load_errors() -> dict:
    all_disks()
    return dict(_cache.get("errors") or {})


_by_id_fast: dict = {}


def get_disk(method) -> Disk:
    """Đĩa theo mã phương pháp ("1".."7", "6.1", hoặc id đĩa nạp). Mã lạ → PP1 (như code cũ: nhánh else)."""
    key = str(method if method is not None else "1").strip().lower()
    d = _by_id_fast.get(key)
    if d is not None:
        return d
    disks = all_disks()
    d = disks.get(key) or disks.get("1") or _FALLBACK
    _by_id_fast[key] = d
    return d


def find_disk(method):
    """Như get_disk nhưng trả None nếu không có đĩa đó."""
    return all_disks().get(str(method).strip().lower()) if method is not None else None


_FALLBACK = Disk(id="1", name="PP1", description="", base="pp1", blocks=frozenset())


def sorted_disks() -> list:
    def k(d):
        if _BUILTIN_ID_RE.match(d.id):
            return (0, float(d.id), d.id)
        return (1, 0.0, d.id)
    return sorted(all_disks().values(), key=k)


def install_disk(text: str) -> Disk:
    """Kiểm tra rồi lưu đĩa nạp từ web vào data/strategies/<id>.md (ghi đè đĩa nạp cùng id)."""
    disk = parse_disk(text, source="upload")
    existing = all_disks().get(disk.id)
    if existing is not None and existing.source == "builtin":
        raise DiskError(f"id '{disk.id}' là đĩa có sẵn của hộp, hãy đặt id khác")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{disk.id}.md"
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    with _lock:
        _cache["disks"] = None
        _by_id_fast.clear()
    return all_disks()[disk.id]


def remove_disk(disk_id: str) -> None:
    d = all_disks().get(str(disk_id))
    if d is None:
        raise DiskError("Không có đĩa này")
    if d.source != "upload":
        raise DiskError("Đĩa có sẵn của hộp không xoá trên web được")
    (UPLOAD_DIR / f"{d.id}.md").unlink(missing_ok=True)
    with _lock:
        _cache["disks"] = None
        _by_id_fast.clear()


# ---------------------------------------------------------------------------
# Hiển thị Markdown an toàn (escape toàn bộ rồi mới đổi vài cú pháp đơn giản)
# ---------------------------------------------------------------------------
def render_markdown_safe(md: str) -> str:
    out, in_code, para, in_list = [], False, [], False

    def flush():
        nonlocal para
        if para:
            out.append("<p>" + _inline(" ".join(para)) + "</p>")
            para = []

    for raw in (md or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("```"):
            flush()
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line) + "\n")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            flush()
            lvl = min(len(m.group(1)) + 1, 5)
            out.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\s*[-*]\s+(.*)", line)
        if m:
            flush()
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>" + _inline(m.group(1)) + "</li>")
            continue
        if in_list and line.strip():
            out.append("</ul>")
            in_list = False
        if not line.strip():
            flush()
            if in_list:
                out.append("</ul>")
                in_list = False
            continue
        para.append(line.strip())
    flush()
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


def _inline(s: str) -> str:
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def check_params(values: dict) -> dict:
    """Kiểm tra bộ tham số thử (vd từ trang Backtest) theo cùng quy tắc của đĩa. Sai → DiskError."""
    schema = param_schema()
    return {str(k).strip().upper(): _check_param(str(k).strip().upper(), v, schema) for k, v in (values or {}).items()}


def use_variant(method, extra_params: dict) -> Disk:
    """Chỉ trong process hiện tại: đĩa `method` chạy với thêm tham số extra_params (backtest thử tham số)."""
    from dataclasses import replace
    base = get_disk(method)
    v = replace(base, params={**base.params, **extra_params})
    _by_id_fast[str(method).strip().lower()] = v
    return v


def disks_json() -> str:
    return json.dumps([d.to_public() for d in sorted_disks()], ensure_ascii=False)
