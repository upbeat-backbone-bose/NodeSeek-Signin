"""通知模块运行时路径的回归测试。

覆盖 SPEC.md 的 S-10：单个通知渠道的异常不得影响其他渠道。
"""

import io
import threading
from contextlib import redirect_stdout

import notify


class TestChannelIsolation:
    """S-10：一个渠道炸了，其他渠道照常送达。"""

    def test_s10_failing_channel_does_not_stop_the_others(self, monkeypatch):
        """第一个渠道抛异常时，第二个渠道仍然被调用。"""
        calls = []

        def boom(title, content):
            calls.append("boom")
            raise RuntimeError("channel exploded")

        def fine(title, content):
            calls.append("fine")

        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [boom, fine])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            notify.send("标题", "内容")

        assert calls == ["boom", "fine"]

    def test_s10_channel_failure_is_reported_not_swallowed(self, monkeypatch, capsys):
        """失败渠道必须有可见提示，不能静默吞掉。"""

        def boom(title, content):
            raise RuntimeError("channel exploded")

        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [boom])

        notify.send("标题", "内容")

        out = capsys.readouterr().out
        assert "推送失败" in out

    def test_s10_skipped_title_is_not_pushed(self, monkeypatch):
        """标题命中 SKIP_PUSH_TITLE 时完全不推送。"""
        calls = []

        def channel(title, content):
            calls.append(title)

        monkeypatch.setenv("SKIP_PUSH_TITLE", "标题")
        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [channel])

        with redirect_stdout(io.StringIO()):
            notify.send("标题", "内容")

        assert calls == []

    def test_s10_empty_content_is_not_pushed(self, monkeypatch):
        """空内容不推送（避免发出无意义请求）。"""
        calls = []

        def channel(title, content):
            calls.append(title)

        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [channel])

        with redirect_stdout(io.StringIO()):
            notify.send("标题", "")

        assert calls == []

    def test_s10_channels_run_in_threads(self, monkeypatch):
        """渠道在独立线程中运行，主流程不阻塞在渠道内部。"""
        seen = []

        def channel(title, content):
            seen.append(threading.current_thread().name)

        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [channel])

        with redirect_stdout(io.StringIO()):
            notify.send("标题", "内容")

        assert seen
        assert seen[0] != threading.current_thread().name


class TestOptionalRequests:
    """requests 缺失时，只有 HTTP 渠道失效，标准库渠道仍可用。"""

    def test_smtp_still_works_without_requests(self, monkeypatch):
        """缺少 requests 时 smtp 仍可用（它只用标准库）。"""
        monkeypatch.setattr(notify, "requests", None)

        calls = []

        class FakeSmtp:
            def __init__(self, *a, **k):
                calls.append(a)

            def ehlo(self):
                pass

            def starttls(self, context=None):
                pass

            def login(self, *a):
                pass

            def sendmail(self, *a):
                pass

            def quit(self):
                pass

        monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSmtp)
        monkeypatch.setitem(notify.push_config, "SMTP_SERVER", "smtp.example.com:465")
        monkeypatch.setitem(notify.push_config, "SMTP_EMAIL", "a@example.com")
        monkeypatch.setitem(notify.push_config, "SMTP_PASSWORD", "pw")
        monkeypatch.setitem(notify.push_config, "SMTP_NAME", "n")
        monkeypatch.setitem(notify.push_config, "SMTP_SSL", "true")

        notify.smtp("标题", "内容")

        assert calls

    def test_http_channel_reports_missing_requests(self, monkeypatch, capsys):
        """缺少 requests 时 HTTP 渠道给出明确提示而不是崩溃。"""
        monkeypatch.setattr(notify, "requests", None)
        monkeypatch.setitem(notify.push_config, "BARK_PUSH", "https://example.com/x")

        notify.bark("标题", "内容")

        out = capsys.readouterr().out
        assert "requests" in out

    def test_one_returns_empty_without_requests(self, monkeypatch):
        """缺少 requests 时一言返回空字符串，不影响主通知。"""
        monkeypatch.setattr(notify, "requests", None)
        assert notify.one() == ""
