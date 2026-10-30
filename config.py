# -*- coding: utf-8 -*-
"""Shared environment helpers.

Keep parsing rules consistent across the sign-in script, scheduler,
captcha solvers and notification module.
"""

import os


def get_env_str(name: str, default: str = "") -> str:
    """Read a trimmed environment variable, falling back when empty."""
    value = os.getenv(name)
    if value is None:
        return default
    value = str(value).strip()
    return value if value else default


def get_env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back when invalid."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def get_env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable (true/false/1/0/yes/on).

    Unrecognised or empty values fall back to *default* instead of silently
    resolving to ``False``.
    """
    value = os.getenv(name)
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on"):
        return True
    if text in ("false", "0", "no", "off"):
        return False
    return default


DEBUG_MODE = get_env_bool("DEBUG", False)
REQUEST_TIMEOUT = max(1, get_env_int("TIMEOUT", 15))
