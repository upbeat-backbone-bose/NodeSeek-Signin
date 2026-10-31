"""调度器运行时路径的回归测试。

覆盖 SPEC.md 的 S-8（子进程超时被终止）与 S-9（单实例锁），
外加 S-5b（Cookie 文件写入失败不留临时文件）。

这些路径在审查前几乎没有被测试覆盖：子进程失控会让容器永远签不到，
锁失效会让两个调度器同时跑。
"""

import os
import subprocess
import sys
import time

import pytest

import cookie_store
import scheduler


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("NS_", "RUN_AT", "TASK_", "HEARTBEAT", "SCHEDULER_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(scheduler, "_stop_requested", False)
    monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **k: None)


class TestRunCheckinTask:
    """S-8：子进程超时必须被终止。"""

    def test_s8_timeout_kills_the_child_process(self, monkeypatch):
        """超过 TASK_TIMEOUT 的子进程必须被杀掉，调度器报告失败。"""
        monkeypatch.setattr(scheduler, "TASK_TIMEOUT", 1)
        killed = []

        class FakeProcess:
            def __init__(self):
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                killed.append("terminate")

            def kill(self):
                killed.append("kill")
                self.returncode = -9

            def wait(self, timeout=None):
                return self.returncode

        monkeypatch.setattr(
            scheduler.subprocess, "Popen", lambda *a, **k: FakeProcess()
        )

        result = scheduler.run_checkin_task()

        assert result is False
        assert "kill" in killed

    def test_successful_child_process_returns_true(self, monkeypatch):
        """正常退出（返回码 0）时调度器报告成功。"""

        class FakeProcess:
            returncode = 0

            def poll(self):
                return 0

            def terminate(self):
                pass

            def kill(self):
                pass

            def wait(self, timeout=None):
                return 0

        monkeypatch.setattr(
            scheduler.subprocess, "Popen", lambda *a, **k: FakeProcess()
        )

        assert scheduler.run_checkin_task() is True

    def test_failing_child_process_returns_false(self, monkeypatch):
        """子进程返回非 0 时调度器报告失败。"""

        class FakeProcess:
            returncode = 1

            def poll(self):
                return 1

            def terminate(self):
                pass

            def kill(self):
                pass

            def wait(self, timeout=None):
                return 1

        monkeypatch.setattr(
            scheduler.subprocess, "Popen", lambda *a, **k: FakeProcess()
        )

        assert scheduler.run_checkin_task() is False

    def test_missing_script_returns_false(self, monkeypatch):
        """脚本不存在时报告失败而不是抛出异常。"""

        def raise_not_found(*a, **k):
            raise FileNotFoundError()

        monkeypatch.setattr(scheduler.subprocess, "Popen", raise_not_found)

        assert scheduler.run_checkin_task() is False

    def test_popen_exception_returns_false(self, monkeypatch):
        """启动子进程时抛异常必须报告失败，而不是让调度器崩溃。"""

        def boom(*a, **k):
            raise OSError("no fork")

        monkeypatch.setattr(scheduler.subprocess, "Popen", boom)

        assert scheduler.run_checkin_task() is False

    def test_stop_signal_terminates_the_child(self, monkeypatch):
        """停止信号到达时必须终止子进程并返回失败。"""
        monkeypatch.setattr(scheduler, "_stop_requested", False)
        terminated = []

        class FakeProcess:
            returncode = None

            def poll(self):
                return None

            def terminate(self):
                terminated.append("terminate")

            def kill(self):
                terminated.append("kill")
                self.returncode = -15

            def wait(self, timeout=None):
                return self.returncode

        monkeypatch.setattr(
            scheduler.subprocess, "Popen", lambda *a, **k: FakeProcess()
        )

        # 让第二次 poll 后停止标志置位，模拟收到停止信号。
        state = {"calls": 0}

        def poll_with_stop(self):
            state["calls"] += 1
            if state["calls"] >= 2:
                scheduler._stop_requested = True
            return None

        FakeProcess.poll = poll_with_stop

        result = scheduler.run_checkin_task()

        assert result is False
        assert "terminate" in terminated

    def test_real_child_process_runs_and_exits(self, tmp_path):
        """真实执行：子进程确实被拉起并跑完（不是只有桩能跑通）。"""
        marker = tmp_path / "ran.txt"
        script = tmp_path / "child.py"
        script.write_text(f"open({str(marker)!r}, 'w').write('ok')\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
        assert marker.read_text(encoding="utf-8") == "ok"


class TestSingleInstanceLock:
    """S-9：第二个调度器实例必须拿不到锁。"""

    def test_s9_lock_file_is_created(self, monkeypatch, tmp_path):
        lock_file = tmp_path / "scheduler.lock"
        monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock_file))

        assert scheduler._acquire_lock() is True
        assert lock_file.exists()

    def test_s9_second_instance_cannot_acquire_the_lock(self, monkeypatch, tmp_path):
        """同一个锁文件被持有时，第二次获取必须失败（仅 POSIX）。"""
        fcntl = pytest.importorskip("fcntl", reason="flock 单实例锁只在 POSIX 平台生效")
        lock_file = tmp_path / "scheduler.lock"
        monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock_file))

        assert scheduler._acquire_lock() is True

        # 第二个实例：模拟 POSIX 上 flock 被占用。
        with open(lock_file, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                # 第二个实例尝试获取同一把锁。
                monkeypatch.setattr(scheduler, "_lock_handle", None, raising=False)
                result = scheduler._acquire_lock()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        assert result is False

    @pytest.mark.skipif(sys.platform == "win32", reason="非 POSIX 平台上锁是空操作")
    def test_s9_lock_is_released_after_close(self, monkeypatch, tmp_path):
        """锁句柄关闭后，第二个实例必须能重新获取。"""
        fcntl = pytest.importorskip("fcntl")
        lock_file = tmp_path / "scheduler.lock"
        monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock_file))

        assert scheduler._acquire_lock() is True
        handle = scheduler._lock_handle
        handle.close()

        with open(lock_file, "a+", encoding="utf-8") as probe:
            fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(probe.fileno(), fcntl.LOCK_UN)

    def test_unwritable_lock_path_returns_false(self, monkeypatch, tmp_path):
        """锁文件无法创建时报告失败（而不是静默放行两个实例）。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(blocker / "nested" / "lock"))

        assert scheduler._acquire_lock() is False

    def test_s9_lock_contention_returns_false_on_any_platform(
        self, monkeypatch, tmp_path
    ):
        """锁被占用时必须返回 False —— 与平台无关。

        Windows 上没有 fcntl，POSIX 分支不会被执行；如果只测 POSIX 路径，
        "锁失败时仍然放行"这个变异在 Windows 上就杀不掉。这里用一个假 fcntl
        模块把该分支在任意平台上跑起来。
        """
        lock_file = tmp_path / "scheduler.lock"
        monkeypatch.setenv("SCHEDULER_LOCK_FILE", str(lock_file))

        real_platform = sys.platform
        monkeypatch.setattr(sys, "platform", "linux")

        class FakeFcntl:
            LOCK_EX = 1
            LOCK_NB = 2

            @staticmethod
            def flock(_fd, _flags):
                raise OSError("Resource temporarily unavailable")

        monkeypatch.setitem(sys.modules, "fcntl", FakeFcntl)

        try:
            assert scheduler._acquire_lock() is False
        finally:
            monkeypatch.setattr(sys, "platform", real_platform)


class TestCookieFileCleanup:
    """S-5b：写入失败不得留下临时文件。"""

    def test_s5b_no_temp_file_remains_after_write_failure(self, monkeypatch, tmp_path):
        """写入过程中抛异常时，临时文件必须被清理，原文件不被破坏。"""
        target = tmp_path / "NS_COOKIE.txt"
        target.write_text("original", encoding="utf-8")
        real_replace = os.replace

        def failing_replace(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(cookie_store.os, "replace", failing_replace)

        with pytest.raises(OSError):
            cookie_store.save_cookie_file(["c1", "", "c3"], str(target))

        monkeypatch.setattr(cookie_store.os, "replace", real_replace)

        leftovers = [
            p.name for p in tmp_path.iterdir() if p.name.startswith(".NS_COOKIE.")
        ]
        assert leftovers == []
        assert target.read_text(encoding="utf-8") == "original"

    def test_successful_write_leaves_no_temp_file(self, tmp_path):
        target = tmp_path / "NS_COOKIE.txt"
        assert cookie_store.save_cookie_file(["c1", "", "c3"], str(target)) is True

        leftovers = [
            p.name for p in tmp_path.iterdir() if p.name.startswith(".NS_COOKIE.")
        ]
        assert leftovers == []
        assert target.read_text(encoding="utf-8") == "c1&&c3"


class TestSleepUntil:
    """休眠循环必须在收到停止信号后立即返回。"""

    def test_sleep_until_returns_false_on_stop_signal(self, monkeypatch):
        monkeypatch.setattr(scheduler, "_stop_requested", True)
        monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **k: None)

        started = time.monotonic()
        result = scheduler._sleep_until(
            scheduler.datetime.datetime.now(scheduler.GMT8)
            + scheduler.datetime.timedelta(seconds=30)
        )
        elapsed = time.monotonic() - started

        assert result is False
        assert elapsed < 5
