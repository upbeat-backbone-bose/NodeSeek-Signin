import datetime
import os
import random
import re
import signal
import subprocess
import sys
import time
from datetime import timezone, timedelta

from config import get_env_int, get_env_str

GMT8 = timezone(timedelta(hours=8))

DEFAULT_RUN_AT = "09:00-21:00"
FALLBACK_RUN_AT = "08:00-10:59"
HEARTBEAT_FILE = get_env_str("HEARTBEAT_FILE", "./cookie/heartbeat")
TASK_TIMEOUT = max(60, get_env_int("TASK_TIMEOUT", 1800))
SLEEP_CHUNK = max(5, min(get_env_int("SCHEDULER_SLEEP_CHUNK", 60), 300))

_stop_requested = False
_lock_handle = None


def _now() -> datetime.datetime:
    return datetime.datetime.now(GMT8)


def _log(message: str) -> None:
    print(f"[{_now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def _handle_stop(signum, frame):
    global _stop_requested
    _stop_requested = True
    _log(f"收到停止信号 ({signum})，准备退出...")


def _write_heartbeat() -> None:
    """Write an atomic heartbeat used by the Docker healthcheck."""
    try:
        directory = os.path.dirname(HEARTBEAT_FILE)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temp_path = f"{HEARTBEAT_FILE}.tmp"
        with open(temp_path, "w", encoding="utf-8") as handle:
            handle.write(_now().isoformat())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, HEARTBEAT_FILE)
    except Exception as exc:
        print(f"写入 heartbeat 失败: {type(exc).__name__}", flush=True)


def _parse_hhmm(value: str):
    match = re.fullmatch(r"(\d{2}):(\d{2})", value or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def get_run_config():
    """
    从环境变量 RUN_AT 读取并解析运行时间配置。
    - 'HH:MM': 固定时间
    - 'HH:MM-HH:MM': 随机时间范围
    - 未设置: 默认 '09:00-21:00'
    - 格式错误: 回退 '08:00-10:59'
    返回一个元组 (mode, value)
    """
    raw = get_env_str("RUN_AT", DEFAULT_RUN_AT)

    if _parse_hhmm(raw):
        print(f"检测到固定时间模式: {raw}", flush=True)
        return "fixed", raw

    if "-" in raw:
        start, _, end = raw.partition("-")
        if _parse_hhmm(start) and _parse_hhmm(end):
            print(f"检测到随机时间范围模式: {raw}", flush=True)
            return "range", raw

    if os.environ.get("RUN_AT"):
        print(f"警告: 环境变量 RUN_AT 的格式 '{raw}' 无效。", flush=True)

    print(f"将使用默认随机时间范围 '{FALLBACK_RUN_AT}'。", flush=True)
    return "range", FALLBACK_RUN_AT


def calculate_next_run_time(mode, value, now=None, rng=None, allow_immediate=True):
    """
    根据当前时间和配置计算下一次运行时间。
    启动时若已处于随机时间窗口内，可立即返回（加几秒抖动）；
    任务执行完毕后的下一次计算必须传入 allow_immediate=False，
    否则宽窗口会导致当天反复签到。
    """
    now = now or _now()
    rng = rng or random

    if mode == "fixed":
        hour, minute = _parse_hhmm(value)
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target

    start_text, _, end_text = value.partition("-")
    start_hour, start_minute = _parse_hhmm(start_text)
    end_hour, end_minute = _parse_hhmm(end_text)
    start_time = datetime.time(start_hour, start_minute)
    end_time = datetime.time(end_hour, end_minute)

    start_today = datetime.datetime.combine(now.date(), start_time, tzinfo=GMT8)
    end_clock_today = datetime.datetime.combine(now.date(), end_time, tzinfo=GMT8)
    overnight = end_time <= start_time

    # If we are inside today's window and immediate runs are allowed, run now.
    if overnight:
        in_window = now <= end_clock_today or now >= start_today
    else:
        in_window = start_today <= now <= end_clock_today

    if in_window and allow_immediate:
        return now + datetime.timedelta(seconds=rng.randint(0, 5))

    if in_window:
        # Skip the window we are currently in. For an overnight window the
        # early-morning part belongs to yesterday's start, so the next start is
        # still later today; the late-evening part rolls to tomorrow.
        if overnight and now <= end_clock_today:
            target_date = now.date()
        else:
            target_date = now.date() + datetime.timedelta(days=1)
    elif now < start_today:
        target_date = now.date()
    else:
        target_date = now.date() + datetime.timedelta(days=1)

    start_target = datetime.datetime.combine(target_date, start_time, tzinfo=GMT8)
    end_target = datetime.datetime.combine(target_date, end_time, tzinfo=GMT8)
    if overnight:
        end_target += datetime.timedelta(days=1)

    start_timestamp = int(start_target.timestamp())
    end_timestamp = int(end_target.timestamp())
    random_timestamp = rng.randint(start_timestamp, end_timestamp)
    return datetime.datetime.fromtimestamp(random_timestamp, tz=GMT8)


def _sleep_until(target: datetime.datetime) -> bool:
    """Sleep in short chunks; return False when a stop signal was received."""
    while not _stop_requested:
        remaining = (target - _now()).total_seconds()
        if remaining <= 0:
            return True
        time.sleep(min(remaining, SLEEP_CHUNK))
        _write_heartbeat()
    return False


def run_checkin_task() -> bool:
    """Run nodeseek_sign.py with a hard timeout and signal forwarding."""
    script_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "nodeseek_sign.py"
    )
    _log("开始执行签到任务...")
    _write_heartbeat()

    try:
        process = subprocess.Popen([sys.executable, script_path], cwd=os.path.dirname(script_path))
    except FileNotFoundError:
        _log("错误: 'nodeseek_sign.py' 未找到。")
        return False
    except Exception as exc:
        _log(f"启动签到任务失败: {type(exc).__name__}")
        return False

    deadline = time.monotonic() + TASK_TIMEOUT
    last_heartbeat = time.monotonic()
    timed_out = False
    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                break
            if _stop_requested:
                _log("调度器停止，正在终止签到子进程...")
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                return False
            if time.monotonic() >= deadline:
                timed_out = True
                process.kill()
                process.wait()
                break
            # Keep the Docker healthcheck alive during long check-in runs.
            if time.monotonic() - last_heartbeat >= SLEEP_CHUNK:
                _write_heartbeat()
                last_heartbeat = time.monotonic()
            time.sleep(0.5)
    finally:
        _write_heartbeat()

    if timed_out:
        _log(f"签到任务超过 {TASK_TIMEOUT} 秒，已强制终止。")
        return False

    if returncode == 0:
        _log("签到任务执行完毕。")
        return True

    _log(f"签到任务执行失败，返回码: {returncode}")
    return False


def _acquire_lock() -> bool:
    """Best-effort single-instance lock (POSIX flock, no-op elsewhere)."""
    global _lock_handle
    lock_path = get_env_str("SCHEDULER_LOCK_FILE", "./cookie/scheduler.lock")
    try:
        directory = os.path.dirname(lock_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        handle = open(lock_path, "a+", encoding="utf-8")
    except Exception as exc:
        print(f"无法创建调度器锁文件: {type(exc).__name__}", flush=True)
        return False

    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        pass
    except OSError:
        print("另一个调度器实例正在运行，退出。", flush=True)
        handle.close()
        return False

    _lock_handle = handle
    return True


def main() -> int:
    if not _acquire_lock():
        return 1

    print("调度器启动...", flush=True)
    mode, value = get_run_config()
    print(f"调度模式: '{mode}', 配置值: '{value}'", flush=True)
    _write_heartbeat()

    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)

    first_run = True
    while not _stop_requested:
        next_run_time = calculate_next_run_time(
            mode, value, allow_immediate=first_run
        )
        first_run = False
        _log(f"下一次签到任务计划在: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')}")
        if not _sleep_until(next_run_time):
            break

        run_checkin_task()
        _write_heartbeat()

        if _stop_requested:
            break
        # Avoid a tight loop if the clock moved backwards.
        time.sleep(1)

    _log("调度器已退出。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
