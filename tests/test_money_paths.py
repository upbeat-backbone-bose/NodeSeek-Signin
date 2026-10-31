"""付费验证码与凭据路径的回归测试。

本文件覆盖 SPEC.md 的 S-1..S-7：涉及"花钱"（付费验证码求解）与
"凭据"（Cookie、GitHub Secret）的关键路径。

这些路径在审查前几乎没有测试覆盖，而它们恰恰是最贵的失败点：
一次误触发就是一次真金白银的验证码账单。
"""

import io
import os
from contextlib import redirect_stdout

import pytest

import nodeseek_sign


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """清除所有会影响 run() 的环境变量，保证测试可重复。"""
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
        "RUN_AT",
        "TASK_TIMEOUT",
        "HEARTBEAT_FILE",
        "SCHEDULER_LOCK_FILE",
        "SCHEDULER_SLEEP_CHUNK",
        "DEBUG",
        "TIMEOUT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(nodeseek_sign, "hadsend", False)
    monkeypatch.setattr(nodeseek_sign, "send", None)


def _install_fakes(monkeypatch, sign_result="success", stats=None):
    """替换网络调用，返回调用记录。"""
    calls = []

    def fake_sign(cookie, ns_random):
        calls.append(cookie)
        return sign_result, "ok"

    def fake_stats(cookie, days=30):
        return stats, "ok"

    monkeypatch.setattr(nodeseek_sign, "sign", fake_sign)
    monkeypatch.setattr(nodeseek_sign, "get_signin_stats", fake_stats)
    return calls


class TestRunDoesNotBuyCaptcha:
    """S-1..S-3：不得为错误账号或瞬时故障购买验证码。"""

    def test_s1_more_accounts_than_cookies_does_not_buy_captcha(
        self, monkeypatch, capsys
    ):
        """S-1 账号数多于 Cookie 数时不购买验证码。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("USER1", "u2")
        monkeypatch.setenv("PASS1", "p2")
        monkeypatch.setenv("CLIENT_KEY", "key")
        login_calls = []
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: login_calls.append(a) or "fresh",
        )
        _install_fakes(monkeypatch)

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert login_calls == []
        assert "尝试重新登录获取新 Cookie" not in out
        assert exit_code == 1

    def test_s2_network_error_does_not_buy_captcha(self, monkeypatch, capsys):
        """S-2 网络异常不触发付费求解。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("CLIENT_KEY", "key")
        login_calls = []
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: login_calls.append(a) or "fresh",
        )
        monkeypatch.setattr(
            nodeseek_sign, "sign", lambda *a, **k: ("error", "请求异常")
        )

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert login_calls == []
        assert "跳过重新登录" in out
        assert exit_code == 1

    @pytest.mark.parametrize(
        "sign_result",
        [("forbidden", "403 Forbidden"), ("error", "服务端错误 (500)")],
    )
    def test_s3_403_and_5xx_do_not_buy_captcha(self, monkeypatch, capsys, sign_result):
        """S-3 403 与 5xx 不触发付费求解。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("CLIENT_KEY", "key")
        login_calls = []
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: login_calls.append(a) or "fresh",
        )
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: sign_result)

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert login_calls == []
        assert "跳过重新登录" in out
        assert exit_code == 1


class FakeSolver:
    """记录求解参数并返回预置结果或抛出预置异常。"""

    def __init__(self, token="tok", error=None):
        self.token = token
        self.error = error
        self.calls = []

    def __call__(self, **kwargs):
        outer = self

        class _Instance:
            def solve(self, **inner):
                outer.calls.append(inner)
                if outer.error is not None:
                    raise outer.error
                return outer.token

        return _Instance()


class _CookieJar:
    """模拟 curl_cffi 的 CookieJar。"""

    def __init__(self, data):
        self._data = data

    def get_dict(self):
        return dict(self._data)


class FakeSession:
    """模拟 curl_cffi Session：返回预置 JSON，并收集 Cookie。"""

    def __init__(self, payload, cookies=None):
        self.payload = payload
        self._cookies = _CookieJar(cookies or {})
        self.posted = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def get(self, *args, **kwargs):
        return None

    def post(self, url, json=None, **kwargs):
        self.posted.append({"url": url, "json": json})
        payload = self.payload

        class _Response:
            def json(self_inner):
                return payload

        return _Response()

    @property
    def cookies(self):
        return self._cookies


def _install_session(monkeypatch, session):
    """把 nodeseek_sign.requests.Session 换成桩。"""

    class _Requests:
        Session = staticmethod(lambda *a, **k: session)

    monkeypatch.setattr(nodeseek_sign, "requests", _Requests)
    return session


class TestSessionLoginDoesNotLeakSecrets:
    """S-4：密码与验证码令牌不得进入输出。"""

    def test_s4_password_and_token_do_not_appear_in_output(self, monkeypatch):
        monkeypatch.setattr(
            nodeseek_sign, "TurnstileSolver", FakeSolver(token="SECRET_TOKEN_VALUE")
        )
        _install_session(
            monkeypatch,
            FakeSession({"success": True}, {"sess": "abc"}),
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = nodeseek_sign.session_login(
                "myuser", "hunter2", "turnstile", "https://api.example.com", "key"
            )
        output = buffer.getvalue()

        assert result == "sess=abc"
        assert "hunter2" not in output
        assert "SECRET_TOKEN_VALUE" not in output

    def test_s4_token_is_sent_to_the_api_but_not_printed(self, monkeypatch):
        """令牌必须真的送到接口（否则登录永远失败），只是不打印。"""
        solver = FakeSolver(token="SECRET_TOKEN_VALUE")
        monkeypatch.setattr(nodeseek_sign, "TurnstileSolver", solver)
        session = _install_session(
            monkeypatch, FakeSession({"success": True}, {"sess": "abc"})
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            nodeseek_sign.session_login(
                "myuser", "hunter2", "turnstile", "https://api.example.com", "key"
            )

        assert len(session.posted) == 1
        assert session.posted[0]["json"]["token"] == "SECRET_TOKEN_VALUE"
        assert "SECRET_TOKEN_VALUE" not in buffer.getvalue()


class TestSessionLoginFailureModes:
    """S-5、S-6：失败原因要透出，且不返回空凭据。"""

    def test_s5_solver_error_reason_is_surfaced(self, monkeypatch):
        """S-5 求解器失败时真实原因被透出。"""
        from yescaptcha import YesCaptchaSolverError

        monkeypatch.setattr(
            nodeseek_sign,
            "TurnstileSolver",
            FakeSolver(error=YesCaptchaSolverError("余额不足")),
        )

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = nodeseek_sign.session_login(
                "u", "p", "turnstile", "https://api.example.com", "key"
            )
        output = buffer.getvalue()

        assert result is None
        assert "余额不足" in output

    def test_s6_login_success_without_cookies_returns_none(self, monkeypatch):
        """S-6 登录成功但未获得 Cookie 时不返回空凭据。"""
        monkeypatch.setattr(nodeseek_sign, "TurnstileSolver", FakeSolver(token="tok"))
        session = FakeSession({"success": True}, {})
        _install_session(monkeypatch, session)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            result = nodeseek_sign.session_login(
                "u", "p", "turnstile", "https://api.example.com", "key"
            )
        output = buffer.getvalue()

        assert result is None
        assert "未获得 Cookie" in output

    def test_login_failure_returns_none(self, monkeypatch):
        """认证失败时返回 None，且不产生任何 Cookie。"""
        monkeypatch.setattr(nodeseek_sign, "TurnstileSolver", FakeSolver(token="tok"))
        _install_session(
            monkeypatch, FakeSession({"success": False, "message": "nope"}, {})
        )

        result = nodeseek_sign.session_login(
            "u", "p", "turnstile", "https://api.example.com", "key"
        )

        assert result is None

    def test_missing_client_key_skips_solver_entirely(self, monkeypatch):
        """没有 CLIENT_KEY 时连求解器都不该被构造。"""
        constructed = []

        def factory(**kwargs):
            constructed.append(kwargs)
            raise AssertionError("不应构造求解器")

        monkeypatch.setattr(nodeseek_sign, "TurnstileSolver", factory)

        result = nodeseek_sign.session_login(
            "u", "p", "turnstile", "https://api.example.com", ""
        )

        assert result is None
        assert constructed == []


class TestGithubSecretWriteback:
    """S-7：回写失败不得报告成功，未启用不得发出请求。"""

    def test_s7_disabled_returns_none_and_makes_no_request(self, monkeypatch):
        monkeypatch.delenv("GH_COOKIE_WRITEBACK", raising=False)
        requests = []

        class _PyRequests:
            @staticmethod
            def get(*a, **k):
                requests.append(a)
                raise AssertionError("未启用时不应发起请求")

            @staticmethod
            def put(*a, **k):
                requests.append(a)
                raise AssertionError("未启用时不应发起请求")

        monkeypatch.setattr(nodeseek_sign, "py_requests", _PyRequests)

        assert nodeseek_sign.save_cookie_to_github_secret("NS_COOKIE", "c") is None
        assert requests == []

    def test_s7_public_key_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("GH_COOKIE_WRITEBACK", "true")
        monkeypatch.setenv("GH_PAT", "token")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        put_calls = []

        class _Response:
            status_code = 403

            def json(self):
                return {}

        class _PyRequests:
            @staticmethod
            def get(*a, **k):
                return _Response()

            @staticmethod
            def put(*a, **k):
                put_calls.append(a)
                raise AssertionError("公钥获取失败时不应尝试写入")

        monkeypatch.setattr(nodeseek_sign, "py_requests", _PyRequests)

        assert nodeseek_sign.save_cookie_to_github_secret("NS_COOKIE", "c") is False
        assert put_calls == []

    def test_s7_missing_credentials_returns_false(self, monkeypatch):
        monkeypatch.setenv("GH_COOKIE_WRITEBACK", "true")
        monkeypatch.delenv("GH_PAT", raising=False)
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)

        assert nodeseek_sign.save_cookie_to_github_secret("NS_COOKIE", "c") is False

    def test_s7_successful_writeback_returns_true(self, monkeypatch):
        """成功时返回 True，且写入的是密文而非明文 Cookie。"""
        pytest.importorskip("nacl")
        monkeypatch.setenv("GH_COOKIE_WRITEBACK", "true")
        monkeypatch.setenv("GH_PAT", "token")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        put_calls = []

        class _KeyResponse:
            status_code = 200

            def json(self):
                from nacl import encoding
                from nacl.public import PrivateKey

                private_key = PrivateKey.generate()
                public_key = private_key.public_key
                return {
                    "key": public_key.encode(encoding.Base64Encoder()).decode("utf-8"),
                    "key_id": "kid-1",
                }

        class _PutResponse:
            status_code = 204

        class _PyRequests:
            @staticmethod
            def get(*a, **k):
                return _KeyResponse()

            @staticmethod
            def put(*a, **k):
                put_calls.append(k.get("json"))
                return _PutResponse()

        monkeypatch.setattr(nodeseek_sign, "py_requests", _PyRequests)

        assert (
            nodeseek_sign.save_cookie_to_github_secret("NS_COOKIE", "plain-cookie")
            is True
        )
        assert len(put_calls) == 1
        assert "plain-cookie" not in str(put_calls[0])
        assert put_calls[0]["encrypted_value"]
        assert put_calls[0]["key_id"] == "kid-1"
