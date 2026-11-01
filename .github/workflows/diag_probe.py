# -*- coding: utf-8 -*-
"""临时诊断脚本：打印签到接口的真实状态码与响应体。

只用于排查 500，不进入正式流程。响应体只打印前 300 字符，
且不打印 Cookie。
"""

import json
import os
import sys

from curl_cffi import requests

COOKIE = os.getenv("NS_COOKIE", "")
RANDOM = os.getenv("NS_RANDOM", "false")
URL = f"https://www.nodeseek.com/api/attendance?random={RANDOM}"

HEADERS = {
    "origin": "https://www.nodeseek.com",
    "referer": "https://www.nodeseek.com/board",
    "Content-Type": "application/json",
    "Cookie": COOKIE,
}

FINGERPRINTS = [
    "chrome146",  # 分支默认指纹
    "chrome110",  # 上游 main 默认指纹
    "safari184",
    "firefox133",
]


def probe(impersonate: str, label: str) -> None:
    try:
        resp = requests.post(
            URL,
            headers=HEADERS,
            json={},
            timeout=25,
            impersonate=impersonate,
        )
    except Exception as exc:  # noqa: BLE001 - 诊断脚本需要看到原始异常
        print(f"[{label}] impersonate={impersonate} EXC {type(exc).__name__}: {exc}")
        return
    body = (resp.text or "")[:300].replace("\n", " ")
    print(f"[{label}] impersonate={impersonate} status={resp.status_code} body={body!r}")


def main() -> int:
    import curl_cffi

    print(f"curl_cffi version = {curl_cffi.__version__}")
    print(f"cookie_len = {len(COOKIE)} random = {RANDOM!r}")
    print("--- 单次请求，各指纹对比 ---")
    for fp in FINGERPRINTS:
        probe(fp, "once")

    print("--- 同一指纹连续两次（测同日重复签到） ---")
    for i in (1, 2):
        probe("chrome146", f"dup{i}")

    print("--- 统计接口（对照：是否也 500） ---")
    try:
        resp = requests.post(
            "https://www.nodeseek.com/api/attendance/records?days=30",
            headers=HEADERS,
            timeout=25,
            impersonate="chrome146",
        )
        print(f"[stats] status={resp.status_code} body={(resp.text or '')[:200]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"[stats] EXC {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
