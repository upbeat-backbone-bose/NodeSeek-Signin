#!/usr/bin/env python
"""mypy 基线比较器：只拦截**新增**类型错误。

仓库在引入 mypy 之前就积累了 23 个历史类型错误（push_config 的 Any 联合类型、
隐式 Optional 等）。直接 `mypy` 会让 CI 永远是红的，等于把质量门禁变成噪音。

本脚本：
  1. 运行 mypy，收集错误（文件 + 错误码，不含行号 —— 行号会随代码变动漂移）。
  2. 与 scripts/mypy-baseline.txt 中登记的历史错误比较。
  3. 出现基线之外的错误 -> 退出码 1，并在输出里点名是哪些。
  4. 基线里的错误消失了 -> 提示可以收缩基线（不失败）。

用法：
    python scripts/mypy_baseline.py            # 检查（CI 用）
    python scripts/mypy_baseline.py --update   # 用当前结果重写基线
"""

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_FILE = Path(__file__).resolve().parent / "mypy-baseline.txt"

TARGETS = [
    "config.py",
    "cookie_store.py",
    "nodeseek_sign.py",
    "notify.py",
    "scheduler.py",
    "turnstile_solver.py",
    "yescaptcha.py",
]

ERROR_RE = re.compile(r"^(?P<file>[^:]+):(?P<line>\d+): error: (?P<msg>.*?)  \[(?P<code>[\w-]+)\]")


def collect_errors():
    """运行 mypy，返回 Counter[(文件, 错误码)] 与原始输出。"""
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "--ignore-missing-imports", "--no-error-summary"]
        + TARGETS,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    counts = Counter()
    for line in output.splitlines():
        match = ERROR_RE.match(line)
        if match:
            counts[(match.group("file"), match.group("code"))] += 1
    return counts, output


def load_baseline():
    """读取基线，返回 Counter[(文件, 错误码)]。"""
    if not BASELINE_FILE.exists():
        return Counter()
    counts = Counter()
    for line in BASELINE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 格式：<文件>:<错误码> = <条数>
        left, _, count_text = line.partition("=")
        left = left.strip()
        count_text = count_text.strip()
        if not left or not count_text.isdigit():
            continue
        # left 形如 "notify.py:arg-type"，用 rsplit 切最后一次冒号。
        file_name, _, code = left.rpartition(":")
        if file_name and code:
            counts[(file_name, code)] += int(count_text)
    return counts


def write_baseline(counts):
    """把当前错误写入基线文件。"""
    lines = [
        "# mypy 历史错误基线 —— 由 tools/mypy_baseline.py --update 生成。",
        "#",
        "# 这里登记的都是引入 mypy 之前就存在的类型问题。CI 只拦截基线之外的",
        "# 新增错误，因此历史问题不会让门禁一直是红的。",
        "#",
        "# 修掉某个历史问题后，把对应行删掉即可收缩基线。",
        "# 格式：<文件>:<错误码> = <条数>",
        "",
    ]
    for (file_name, code), count in sorted(counts.items()):
        lines.append(f"{file_name}:{code} = {count}")
    BASELINE_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    current, raw_output = collect_errors()
    baseline = load_baseline()

    if "--update" in sys.argv:
        write_baseline(current)
        print(f"基线已更新：{sum(current.values())} 个历史错误")
        return 0

    new_errors = current - baseline
    resolved = baseline - current

    print(f"mypy 当前错误：{sum(current.values())}（基线 {sum(baseline.values())}）")

    if resolved:
        print("\n以下基线错误已不存在，可以从基线中删除：")
        for key, count in sorted(resolved.items()):
            print(f"  {key[0]}:{key[1]} = {count}")

    if new_errors:
        print("\n新增类型错误（CI 将失败）：")
        for key, count in sorted(new_errors.items()):
            print(f"  {key[0]}:{key[1]} = {count}")
        print("\n详细输出：")
        print(raw_output)
        return 1

    print("没有新增类型错误。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
