"""调度器生命周期路径的回归测试。

覆盖 SPEC.md 的 S-8b/S-9b：心跳写入、停止信号处理与主循环退出。
这些路径决定容器健康检查是否正常、停止信号能否让容器优雅退出。
"""

import os
import signal

import pytest

import scheduler


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("NS_", "RUN_AT", "TASK_", "HEARTBEAT", "SCHEDULER_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(scheduler, "_stop_requested", False)


class TestHeartbeat:
    """心跳文件是 Docker healthcheck 的依据。"""

    def test_heartbeat_is_written_atomically(self, monkeypatch, tmp_path):
        """心跳写入临时文件后原子替换，不留下 .tmp 残留。"""
        target = tmp_path / "heartbeat"
        monkeypatch.setattr(scheduler, "HEARTBEAT_FILE", str(target))

        scheduler._write_heartbeat()

        assert target.exists()
        leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []

    def test_heartbeat_failure_does_not_raise(self, monkeypatch, tmp_path):
        """心跳写不进去时只打印提示，不得让调度器崩溃。"""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory", encoding="utf-8")
        monkeypatch.setattr(
            scheduler, "HEARTBEAT_FILE", str(blocker / "nested" / "heartbeat")
        )

        # 不得抛异常。
        scheduler._write_heartbeat()


class TestStopSignal:
    """停止信号必须让主循环退出。"""

    def test_handle_stop_sets_flag(self, monkeypatch):
        """收到停止信号后置位退出标志。"""
        monkeypatch.setattr(scheduler, "_stop_requested", False)

        scheduler._handle_stop(signal.SIGTERM, None)

        assert scheduler._stop_requested is True

    def test_main_returns_nonzero_when_lock_unavailable(self, monkeypatch):
        """拿不到锁时调度器直接退出，返回非 0。"""
        monkeypatch.setattr(scheduler, "_acquire_lock", lambda: False)

        assert scheduler.main() == 1

    def test_main_exits_cleanly_on_stop(self, monkeypatch):
        """停止信号已置位时主循环立即退出，返回 0。"""
        monkeypatch.setattr(scheduler, "_acquire_lock", lambda: True)
        monkeypatch.setattr(scheduler, "_stop_requested", True)
        monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **k: None)

        assert scheduler.main() == 0

    def test_main_runs_the_checkin_task_once(self, monkeypatch):
        """主循环必须真的执行一次签到任务。"""
        runs = []
        monkeypatch.setattr(scheduler, "_acquire_lock", lambda: True)
        monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **k: None)
        monkeypatch.setattr(scheduler, "get_run_config", lambda: ("fixed", "09:00"))
        monkeypatch.setattr(
            scheduler,
            "calculate_next_run_time",
            lambda *a, **k: scheduler.datetime.datetime.now(scheduler.GMT8),
        )
        monkeypatch.setattr(scheduler, "_sleep_until", lambda *a, **k: True)
        monkeypatch.setattr(
            scheduler, "run_checkin_task", lambda: runs.append(1) or True
        )
        monkeypatch.setattr(scheduler.time, "sleep", lambda _s: None)

        # 第一次循环后置位停止标志，让主循环只跑一轮。
        state = {"calls": 0}

        def sleep_until(_target):
            state["calls"] += 1
            if state["calls"] >= 1:
                scheduler._stop_requested = True
            return True

        monkeypatch.setattr(scheduler, "_sleep_until", sleep_until)

        assert scheduler.main() == 0
        assert len(runs) == 1


class TestSleepUntil:
    """休眠到目标时刻。"""

    def test_returns_true_when_target_reached(self, monkeypatch):
        """目标时刻已过时立即返回 True。"""
        monkeypatch.setattr(scheduler, "_stop_requested", False)
        monkeypatch.setattr(scheduler, "_write_heartbeat", lambda *a, **k: None)

        target = scheduler.datetime.datetime.now(
            scheduler.GMT8
        ) - scheduler.datetime.timedelta(seconds=1)

        assert scheduler._sleep_until(target) is True

    def test_writes_heartbeat_while_sleeping(self, monkeypatch):
        """休眠期间必须刷新心跳，否则容器会被判定为不健康。"""
        beats = []
        monkeypatch.setattr(scheduler, "_stop_requested", False)
        monkeypatch.setattr(
            scheduler, "_write_heartbeat", lambda *a, **k: beats.append(1)
        )
        monkeypatch.setattr(scheduler, "SLEEP_CHUNK", 0.01)

        target = scheduler.datetime.datetime.now(
            scheduler.GMT8
        ) + scheduler.datetime.timedelta(seconds=0.05)

        assert scheduler._sleep_until(target) is True
        assert beats


class TestRunConfig:
    """RUN_AT 解析。"""

    def test_unset_uses_code_default(self, monkeypatch):
        """未设置时使用代码默认值 09:00-21:00。"""
        monkeypatch.delenv("RUN_AT", raising=False)

        assert scheduler.get_run_config() == ("range", scheduler.DEFAULT_RUN_AT)

    def test_invalid_falls_back(self, monkeypatch):
        """格式非法时回退到 FALLBACK_RUN_AT。"""
        monkeypatch.setenv("RUN_AT", "not-a-time")

        assert scheduler.get_run_config() == ("range", scheduler.FALLBACK_RUN_AT)

    def test_fixed_time(self, monkeypatch):
        """合法固定时间被正确解析。"""
        monkeypatch.setenv("RUN_AT", "09:30")

        assert scheduler.get_run_config() == ("fixed", "09:30")


class TestParseHhmm:
    """时间解析的边界。"""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("00:00", (0, 0)),
            ("23:59", (23, 59)),
            ("09:05", (9, 5)),
        ],
    )
    def test_valid_values(self, value, expected):
        assert scheduler._parse_hhmm(value) == expected

    @pytest.mark.parametrize(
        "value", ["24:00", "9:00", "09:60", "ab:cd", "", "09:00:00", "-1:00"]
    )
    def test_invalid_values_rejected(self, value):
        assert scheduler._parse_hhmm(value) is None
