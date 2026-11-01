"""失败账号报告的可读性测试。

对应 SPEC.md 修订 2 的 S-14..S-17。

背景：用户反馈签到后只看到"账号1 error" —— 内部状态码直接抛给用户，
真实原因（"服务端错误 (500)"之类）被丢弃，账号标签还重复成"账号 账号1"。
"""

import json
import os

import pytest

import nodeseek_sign


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("NS_", "USER", "PASS", "GH_", "GITHUB_")):
            monkeypatch.delenv(key, raising=False)
    for key in (
        "IN_DOCKER",
        "CLIENT_KEY",
        "SOLVER_TYPE",
        "API_BASE_URL",
        "MAX_LOGIN_ATTEMPTS",
        "STATS_MAX_PAGES",
        "GH_COOKIE_WRITEBACK",
        "NOTIFY_CONFIG_JSON",
        "TIMEOUT",
        "DEBUG",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(nodeseek_sign, "hadsend", False)
    monkeypatch.setattr(nodeseek_sign, "send", None)


def _result_json(capsys):
    """从 stdout 里取出 RESULT JSON。"""
    out = capsys.readouterr().out
    for line in out.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT ") :])
    raise AssertionError(f"未找到 RESULT 输出:\n{out}")


class TestFailureReasonIsVisible:
    """S-14：失败原因必须写出来。"""

    def test_s14_notification_shows_the_reason(self, monkeypatch, capsys):
        """通知正文必须写明"服务端错误 (500)"，而不是只写 error。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(
            nodeseek_sign,
            "sign",
            lambda *a, **k: ("error", "服务端错误 (500)"),
        )
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        assert "服务端错误 (500)" in sent["content"]
        assert "❌ error" not in sent["content"]

    def test_s14_stdout_line_shows_the_reason(self, monkeypatch, capsys):
        """标准输出里也要能看到原因。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(
            nodeseek_sign,
            "sign",
            lambda *a, **k: ("error", "服务端错误 (500)"),
        )
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )

        nodeseek_sign.run()
        out = capsys.readouterr().out

        assert "服务端错误 (500)" in out

    @pytest.mark.parametrize(
        "status,msg,expected",
        [
            ("error", "服务端错误 (500)", "服务端错误 (500)"),
            ("error", "请求过于频繁 (429)", "请求过于频繁 (429)"),
            ("error", "请求失败：无响应", "请求失败：无响应"),
            ("error", "签到请求异常", "签到请求异常"),
        ],
    )
    def test_s14_own_generated_reasons_are_shown(
        self, monkeypatch, capsys, status, msg, expected
    ):
        """本仓库自己生成的原因必须原样透出。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: (status, msg))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        assert expected in sent["content"]


class TestAccountLabel:
    """S-15：账号标签不重复。"""

    def test_s15_label_has_no_duplicated_prefix(self, monkeypatch, capsys):
        """未配置用户名时显示"账号1"，不显示"账号 账号1"。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(
            nodeseek_sign, "sign", lambda *a, **k: ("error", "服务端错误 (500)")
        )
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        assert "账号 账号1" not in sent["content"]
        assert "账号1" in sent["content"]

    def test_s15_named_account_keeps_its_name(self, monkeypatch, capsys):
        """配置了用户名时账号名照常显示。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "alice")
        monkeypatch.setenv("PASS", "pw")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("success", "ok"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        # _mask_string(show_start=2, show_end=1) => "al**e"
        assert "al**e" in sent["content"]


class TestStatusTranslation:
    """S-16：内部状态码翻译成可读中文。"""

    @pytest.mark.parametrize(
        "status,expected",
        [
            ("success", "签到成功"),
            ("already", "今日已签到"),
            ("invalid", "Cookie 已失效"),
            ("forbidden", "被拦截"),
            ("fail", "签到失败"),
            ("error", "请求异常"),
        ],
    )
    def test_s16_status_is_translated(self, monkeypatch, capsys, status, expected):
        """每个内部状态都对应一句可读中文。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: (status, "x"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        assert expected in sent["content"]

    def test_s16_result_json_keeps_machine_status(self, monkeypatch, capsys):
        """RESULT JSON 的 status 字段保持内部状态码不变（向后兼容）。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(
            nodeseek_sign, "sign", lambda *a, **k: ("error", "服务端错误 (500)")
        )
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )

        nodeseek_sign.run()
        summary = _result_json(capsys)

        assert summary["results"][0]["status"] == "error"
        assert summary["failed"] == 1


class TestServerTextIsNotLeaked:
    """S-17：服务端返回的原文不得进入通知。"""

    def test_s17_server_message_is_not_in_notification(self, monkeypatch, capsys):
        """服务端 message 字段的内容不得出现在通知正文里。"""
        secret = "SENSITIVE-SERVER-TEXT"
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(
            nodeseek_sign,
            "sign",
            lambda *a, **k: ("fail", secret),
        )
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, body: sent.update(title=title, content=body),
        )

        nodeseek_sign.run()

        assert secret not in sent["content"]
        assert "签到失败" in sent["content"]
