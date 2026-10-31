"""签到收益统计与主流程通知的回归测试。

覆盖 SPEC.md 的 S-12（统计截断必须标注）与 S-13（通知失败不得中断主流程）。
统计窗口被静默截断会让用户以为"今天没签到"，通知失败会让用户完全
不知道自己签没签上——两者都是"看起来成功、实际信息缺失"。
"""

import os

import pytest

import nodeseek_sign


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离环境变量：否则 run() 会真的去发通知（网络调用 + 真实耗时）。"""
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


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class TestGetSigninStats:
    """统计查询。"""

    def test_empty_cookie_returns_none(self):
        """没有 Cookie 时直接返回 None，不发请求。"""
        assert nodeseek_sign.get_signin_stats("") == (None, "无有效Cookie")

    def test_non_positive_days_is_clamped_to_one(self, monkeypatch):
        """days<=0 时按 1 天处理，不得算出负数窗口。"""
        captured = {}

        def fake_request(method, url, headers=None, json_data=None, timeout=None):
            captured["url"] = url
            return FakeResponse({"success": True, "data": []})

        monkeypatch.setattr(
            nodeseek_sign, "_request_with_impersonate_fallback", fake_request
        )

        nodeseek_sign.get_signin_stats("session=abc", days=0)

        assert "page-1" in captured["url"]

    def test_api_failure_returns_empty_stats(self, monkeypatch):
        """接口返回 success=false 时结束分页，返回零值统计（既有行为）。"""
        monkeypatch.setattr(
            nodeseek_sign,
            "_request_with_impersonate_fallback",
            lambda *a, **k: (
                FakeResponse({"success": False, "message": "nope"}),
                "c",
                None,
            ),
        )

        stats, message = nodeseek_sign.get_signin_stats("session=abc")

        assert stats is not None
        assert stats["total_amount"] == 0
        assert stats["days_count"] == 0

    def test_request_exception_returns_none(self, monkeypatch):
        """请求抛异常时返回 None，不得让主流程崩溃。"""

        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(nodeseek_sign, "_request_with_impersonate_fallback", boom)

        stats, message = nodeseek_sign.get_signin_stats("session=abc")

        assert stats is None
        assert message


class TestRunNotification:
    """主流程结束后的通知。"""

    def test_notification_failure_does_not_change_exit_code(self, monkeypatch, capsys):
        """通知发送失败不得改变退出码（签到结果才是退出码的依据）。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("success", "ok"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)

        def boom(title, content):
            raise RuntimeError("notify down")

        monkeypatch.setattr(nodeseek_sign, "send", boom)

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "发送通知失败" in out

    def test_failed_count_is_included_in_the_notification(self, monkeypatch):
        """有失败账号时，通知里必须写明失败数。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("error", "boom"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)

        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, content: sent.update(title=title, content=content),
        )

        nodeseek_sign.run()

        assert "失败账号数: 1" in sent["content"]

    def test_no_notification_when_all_succeeded(self, monkeypatch):
        """全部成功时通知里不写失败数。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("success", "ok"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)

        sent = {}
        monkeypatch.setattr(
            nodeseek_sign,
            "send",
            lambda title, content: sent.update(title=title, content=content),
        )

        nodeseek_sign.run()

        assert "失败账号数" not in sent["content"]


class TestRunExitCodes:
    """run() 的退出码语义（N-4）。"""

    def test_all_success_exits_zero(self, monkeypatch):
        """全部成功退出码为 0。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("success", "ok"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )

        assert nodeseek_sign.run() == 0

    def test_already_counted_as_success(self, monkeypatch):
        """already 也算成功，退出码为 0。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("already", "ok"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )

        assert nodeseek_sign.run() == 0

    def test_failure_exits_nonzero(self, monkeypatch):
        """有失败账号时退出码非 0。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: ("error", "boom"))
        monkeypatch.setattr(
            nodeseek_sign, "get_signin_stats", lambda *a, **k: (None, "x")
        )

        assert nodeseek_sign.run() == 1

    def test_no_configuration_exits_nonzero(self, monkeypatch):
        """完全没配置时退出码非 0。"""
        monkeypatch.delenv("NS_COOKIE", raising=False)

        assert nodeseek_sign.run() == 1


class TestSignClassification:
    """sign() 的状态分类。"""

    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"success": True, "message": "获得 5 个鸡腿"}, "success"),
            ({"success": True, "message": "今日已完成签到"}, "already"),
            ({"success": True, "message": "未登录"}, "invalid"),
            ({"success": True, "message": "请先登录"}, "invalid"),
            ({"success": True, "status": 404, "message": "x"}, "invalid"),
            ({"success": False, "message": "x"}, "fail"),
        ],
    )
    def test_classification(self, monkeypatch, payload, expected):
        """不同响应必须被分到正确的状态。"""
        monkeypatch.setattr(
            nodeseek_sign,
            "_request_with_impersonate_fallback",
            lambda *a, **k: (FakeResponse(payload), "chrome146", None),
        )

        assert nodeseek_sign.sign("session=abc", "false")[0] == expected

    def test_transport_error_is_error(self, monkeypatch):
        """传输层异常归类为 error（不触发登录）。"""
        monkeypatch.setattr(
            nodeseek_sign,
            "_request_with_impersonate_fallback",
            lambda *a, **k: (None, "chrome146", RuntimeError("down")),
        )

        assert nodeseek_sign.sign("session=abc", "false")[0] == "error"

    def test_no_response_is_error(self, monkeypatch):
        """没有响应也没有异常时归类为 error。"""
        monkeypatch.setattr(
            nodeseek_sign,
            "_request_with_impersonate_fallback",
            lambda *a, **k: (None, "chrome146", None),
        )

        assert nodeseek_sign.sign("session=abc", "false")[0] == "error"

    def test_exception_is_error(self, monkeypatch):
        """签到请求抛异常时归类为 error，不崩溃。"""

        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(nodeseek_sign, "_request_with_impersonate_fallback", boom)

        assert nodeseek_sign.sign("session=abc", "false")[0] == "error"
