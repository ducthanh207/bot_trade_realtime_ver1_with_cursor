# -*- coding: utf-8 -*-
"""
Mã hoá API key / token Telegram trước khi ghi xuống đĩa (Fernet, AES-128 + HMAC).

Khoá lấy từ biến môi trường LIVE_SECRET_KEY; nếu không có thì tự tạo file
data/live/secret.key (quyền 600) ở lần chạy đầu. Mất file khoá = phải nhập lại key trên web.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("LIVE_DATA_DIR") or (ROOT / "data" / "live"))


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass


def _read_or_create(path: Path, factory) -> bytes:
    _ensure_dir()
    if path.exists():
        return path.read_bytes().strip()
    val = factory()
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(val)
    return val


_fernet = None


def _box() -> Fernet:
    global _fernet
    if _fernet is None:
        env_key = (os.environ.get("LIVE_SECRET_KEY") or "").strip()
        key = env_key.encode() if env_key else _read_or_create(DATA_DIR / "secret.key", Fernet.generate_key)
        _fernet = Fernet(key)
    return _fernet


def encrypt(plain: str) -> str:
    if not plain:
        return ""
    return _box().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return _box().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def hint(plain: str) -> str:
    """Hiển thị an toàn: 4 ký tự đầu … 4 ký tự cuối."""
    plain = plain or ""
    if len(plain) <= 10:
        return "•" * len(plain)
    return f"{plain[:4]}…{plain[-4:]}"


def flask_secret() -> bytes:
    env_key = (os.environ.get("WEB_SECRET_KEY") or "").strip()
    if env_key:
        return env_key.encode()
    return _read_or_create(DATA_DIR / "flask_secret.key", lambda: os.urandom(32).hex().encode())
