# -*- coding: utf-8 -*-
"""Cookie list parsing and atomic persistence.

Cookie position is the account identity. Empty slots must be preserved so a
refreshed cookie cannot shift to another account on the next run.
"""

import os
import tempfile
from typing import Iterable, List

COOKIE_FILE_PATH = "./cookie/NS_COOKIE.txt"


def split_cookies(raw: str) -> List[str]:
    """Split an account cookie list on ``&`` or line breaks.

    Empty entries in the middle are preserved deliberately. A value such as
    ``"cookie1&&cookie3"`` means account 2 has no cookie.

    Trailing empty slots are dropped: they carry no cookie information and
    would otherwise synthesize a phantom account that can never sign in.
    """
    if raw is None:
        return []
    if not str(raw).strip():
        return []
    # Normalize line separators to the same separator as &, then split without
    # filtering empty values.
    normalized = str(raw).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "&")
    slots = []
    for item in normalized.split("&"):
        value = item.strip()
        slots.append(value)

    while slots and not slots[-1]:
        slots.pop()
    return slots


def join_cookies(cookies: Iterable[str]) -> str:
    """Join cookie slots while keeping empty positions."""
    return "&".join((str(item).strip() if item else "") for item in cookies)


def align_cookies(cookies: List[str], account_count: int) -> List[str]:
    """Pad a cookie list to *account_count* without dropping positions."""
    result = list(cookies)
    if len(result) < account_count:
        result.extend([""] * (account_count - len(result)))
    return result


class CookieFileError(RuntimeError):
    """Cookie 文件存在但无法读取。"""


def load_cookie_file(path: str = COOKIE_FILE_PATH) -> str:
    """Read the persisted cookie list from disk.

    文件不存在视为"没有 Cookie"，返回空串；文件存在但读取失败（例如 Docker
    bind mount 权限不足）抛出 :class:`CookieFileError`，由调用方决定如何提示。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise CookieFileError(f"无法读取 Cookie 文件 {path}: {exc}") from exc


def save_cookie_file(cookies, path: str = COOKIE_FILE_PATH) -> bool:
    """Atomically write cookies to a private (0600) file.

    ``cookies`` may be an already-joined string or an iterable of slots.
    """
    data = cookies if isinstance(cookies, str) else join_cookies(cookies)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix=".NS_COOKIE.", dir=directory, text=True)
    try:
        os.chmod(temp_path, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return True
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
