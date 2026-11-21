"""验证码求解器的失败分支测试。

覆盖 SPEC.md 的 S-5 与失败模型"付费求解被误触发"：
这些分支决定"什么时候放弃"而不是"什么时候再花钱"。
每一次重试都是一次潜在的验证码费用，因此放弃条件必须被钉死。
"""

import pytest

import turnstile_solver
import yescaptcha


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestTurnstileFailureBranches:
    """turnstile_solver 的失败分支。"""

    def test_create_task_api_error_raises(self, monkeypatch):
        """创建任务时 API 返回 errorId 必须抛异常并透出原因。"""
        monkeypatch.setattr(
            turnstile_solver.requests,
            "post",
            lambda *a, **k: FakeResponse({"errorId": 5, "errorDescription": "bad key"}),
        )
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        with pytest.raises(turnstile_solver.TurnstileSolverError) as excinfo:
            solver.solve("https://example.com", "sitekey")
        assert "bad key" in str(excinfo.value)

    def test_create_task_without_task_id_raises(self, monkeypatch):
        """没有 taskId 必须抛异常，不能拿 None 去轮询。"""
        monkeypatch.setattr(
            turnstile_solver.requests,
            "post",
            lambda *a, **k: FakeResponse({"errorId": 0}),
        )
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        with pytest.raises(turnstile_solver.TurnstileSolverError):
            solver.solve("https://example.com", "sitekey")

    def test_result_api_error_raises(self, monkeypatch):
        """轮询时 API 返回 errorId 必须抛异常。"""
        responses = [
            FakeResponse({"errorId": 0, "taskId": "t1"}),
            FakeResponse({"errorId": 9, "errorDescription": "expired"}),
        ]
        monkeypatch.setattr(
            turnstile_solver.requests, "post", lambda *a, **k: responses.pop(0)
        )
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        with pytest.raises(turnstile_solver.TurnstileSolverError) as excinfo:
            solver.solve("https://example.com", "sitekey")
        assert "expired" in str(excinfo.value)

    def test_missing_token_raises(self, monkeypatch):
        """状态是 completed 但没有令牌时必须抛异常。"""
        responses = [
            FakeResponse({"errorId": 0, "taskId": "t1"}),
            FakeResponse({"errorId": 0, "status": "completed", "result": {}}),
        ]
        monkeypatch.setattr(
            turnstile_solver.requests, "post", lambda *a, **k: responses.pop(0)
        )
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        with pytest.raises(turnstile_solver.TurnstileSolverError) as excinfo:
            solver.solve("https://example.com", "sitekey")
        assert "令牌" in str(excinfo.value)

    def test_max_retries_raises_timeout(self, monkeypatch):
        """一直拿不到结果时按总时限放弃，抛 Timeout 而不是无限重试。"""
        responses = [FakeResponse({"errorId": 0, "taskId": "t1"})] + [
            FakeResponse({"errorId": 0, "status": "processing"}) for _ in range(5)
        ]
        monkeypatch.setattr(
            turnstile_solver.requests, "post", lambda *a, **k: responses.pop(0)
        )
        monkeypatch.setattr(turnstile_solver.time, "sleep", lambda _s: None)
        solver = turnstile_solver.TurnstileSolver(
            "https://api.example.com", "key", max_retries=2, retry_interval=1
        )
        with pytest.raises(turnstile_solver.TurnstileSolverTimeout):
            solver.solve("https://example.com", "sitekey")

    def test_network_failure_raises_network_error(self, monkeypatch):
        """网络层失败必须归类为 NetworkError，便于上层区分"服务不可达"。"""
        import requests

        def boom(*a, **k):
            raise requests.exceptions.ConnectionError("no route")

        monkeypatch.setattr(turnstile_solver.requests, "post", boom)
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        with pytest.raises(turnstile_solver.TurnstileSolverNetworkError):
            solver.solve("https://example.com", "sitekey")

    def test_timeout_subclasses_base_error(self):
        """超时异常必须仍是 TurnstileSolverError 的子类（上层一��捕获）。"""
        assert issubclass(
            turnstile_solver.TurnstileSolverTimeout,
            turnstile_solver.TurnstileSolverError,
        )
        assert issubclass(
            turnstile_solver.TurnstileSolverNetworkError,
            turnstile_solver.TurnstileSolverError,
        )

    def test_action_and_user_agent_are_passed(self, monkeypatch):
        """action / userAgent / proxy 必须原样传给 API。"""
        captured = {}

        def fake_post(url, data=None, headers=None, timeout=None):
            if "createTask" in url:
                captured["data"] = data
                return FakeResponse({"errorId": 0, "taskId": "t1"})
            return FakeResponse(
                {"errorId": 0, "status": "ready", "solution": {"token": "tok"}}
            )

        monkeypatch.setattr(turnstile_solver.requests, "post", fake_post)
        solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
        token = solver.solve(
            "https://example.com",
            "sitekey",
            action="managed",
            user_agent="UA/1.0",
            proxy={"type": "http"},
        )

        assert token == "tok"
        payload = captured["data"]
        assert '"action": "managed"' in payload
        assert '"userAgent": "UA/1.0"' in payload
        assert '"proxy"' in payload


class TestYesCaptchaFailureBranches:
    """yescaptcha 的失败分支。"""

    def test_network_failure_raises_network_error(self, monkeypatch):
        """网络层失败必须归类为 NetworkError。"""

        def boom(*a, **k):
            raise RuntimeError("no route")

        monkeypatch.setattr(yescaptcha.requests, "post", boom)
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        with pytest.raises(yescaptcha.YesCaptchaSolverNetworkError):
            solver._create_task("https://example.com", "sitekey")

    def test_non_json_response_raises(self, monkeypatch):
        """响应不是合法 JSON 必须抛异常，不能被裸 except 吞掉。"""

        class BadResponse:
            status_code = 200

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(yescaptcha.requests, "post", lambda *a, **k: BadResponse())
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
            solver._create_task("https://example.com", "sitekey")
        assert "JSON" in str(excinfo.value)

    def test_terminal_status_raises(self, monkeypatch):
        """任务进入失败终态必须抛异常并透出原因。"""
        monkeypatch.setattr(
            yescaptcha.requests,
            "post",
            lambda *a, **k: FakeResponse(
                {"errorId": 0, "status": "failed", "errorDescription": "blocked"}
            ),
        )
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
            solver._get_task_result("t1")
        assert "blocked" in str(excinfo.value)

    def test_result_api_error_raises(self, monkeypatch):
        """轮询时 API 返回 errorId 必须抛异常。"""
        monkeypatch.setattr(
            yescaptcha.requests,
            "post",
            lambda *a, **k: FakeResponse(
                {"errorId": 3, "errorDescription": "invalid key"}
            ),
        )
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
            solver._get_task_result("t1")
        assert "invalid key" in str(excinfo.value)

    def test_max_retries_raises_timeout(self, monkeypatch):
        """一直拿不到结果时按总时限放弃。"""
        monkeypatch.setattr(
            yescaptcha.requests,
            "post",
            lambda *a, **k: FakeResponse({"errorId": 0, "status": "processing"}),
        )
        monkeypatch.setattr(yescaptcha.time, "sleep", lambda _s: None)
        solver = yescaptcha.YesCaptchaSolver(
            "https://api.example.com", "key", max_retries=2, retry_interval=1
        )
        with pytest.raises(yescaptcha.YesCaptchaSolverTimeout):
            solver._get_task_result("t1")

    def test_timeout_subclasses_base_error(self):
        """超时与网络异常必须仍是 YesCaptchaSolverError 的子类。"""
        assert issubclass(
            yescaptcha.YesCaptchaSolverTimeout, yescaptcha.YesCaptchaSolverError
        )
        assert issubclass(
            yescaptcha.YesCaptchaSolverNetworkError, yescaptcha.YesCaptchaSolverError
        )

    def test_advanced_mode_uses_proxyless_m1(self, monkeypatch):
        """advanced=True 必须使用 TurnstileTaskProxylessM1 任务类型。"""
        captured = {}

        def fake_post(url, json=None, timeout=None, impersonate=None):
            captured["json"] = json
            return FakeResponse({"errorId": 0, "taskId": "t1"})

        monkeypatch.setattr(yescaptcha.requests, "post", fake_post)
        solver = yescaptcha.YesCaptchaSolver(
            "https://api.example.com", "key", advanced=True
        )
        solver._create_task("https://example.com", "sitekey")

        assert captured["json"]["task"]["type"] == "TurnstileTaskProxylessM1"

    def test_normal_mode_uses_proxyless(self, monkeypatch):
        """默认必须使用 TurnstileTaskProxyless 任务类型。"""
        captured = {}

        def fake_post(url, json=None, timeout=None, impersonate=None):
            captured["json"] = json
            return FakeResponse({"errorId": 0, "taskId": "t1"})

        monkeypatch.setattr(yescaptcha.requests, "post", fake_post)
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        solver._create_task("https://example.com", "sitekey")

        assert captured["json"]["task"]["type"] == "TurnstileTaskProxyless"

    def test_user_agent_is_included(self, monkeypatch):
        """传入 user_agent 时必须带上。"""
        captured = {}

        def fake_post(url, json=None, timeout=None, impersonate=None):
            captured["json"] = json
            return FakeResponse({"errorId": 0, "taskId": "t1"})

        monkeypatch.setattr(yescaptcha.requests, "post", fake_post)
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
        solver._create_task("https://example.com", "sitekey", user_agent="UA/1.0")

        assert captured["json"]["task"]["userAgent"] == "UA/1.0"

    def test_invalid_api_url_rejected(self):
        """非法 API 地址必须在构造时就被拒绝。"""
        with pytest.raises(yescaptcha.YesCaptchaSolverError):
            yescaptcha.YesCaptchaSolver("not-a-url", "key")

    def test_total_deadline_exceeded_raises_timeout(self, monkeypatch):
        """总时限已到时必须抛 Timeout，不得继续轮询。"""
        monkeypatch.setattr(
            yescaptcha.requests,
            "post",
            lambda *a, **k: FakeResponse({"errorId": 0, "status": "processing"}),
        )
        monkeypatch.setattr(yescaptcha.time, "sleep", lambda _s: None)
        # 让 monotonic 始终越过 deadline。
        monkeypatch.setattr(yescaptcha.time, "monotonic", lambda: 1e12)
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        with pytest.raises(yescaptcha.YesCaptchaSolverTimeout):
            solver._get_task_result("t1")

    def test_non_json_result_response_raises(self, monkeypatch):
        """轮询响应不是合法 JSON 时必须抛异常，不能被吞掉。"""

        class BadResponse:
            status_code = 200

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(yescaptcha.requests, "post", lambda *a, **k: BadResponse())
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
            solver._get_task_result("t1")
        assert "JSON" in str(excinfo.value)

    def test_result_network_failure_raises_network_error(self, monkeypatch):
        """轮询时网络失败必须归类为 NetworkError。"""

        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(yescaptcha.requests, "post", boom)
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        with pytest.raises(yescaptcha.YesCaptchaSolverNetworkError):
            solver._get_task_result("t1")

    def test_solve_returns_token_on_success(self, monkeypatch):
        """完整流程：创建任务 -> 轮询 -> 返回令牌。"""
        responses = [
            FakeResponse({"errorId": 0, "taskId": "t1"}),
            FakeResponse(
                {"errorId": 0, "status": "ready", "solution": {"token": "tok"}}
            ),
        ]
        monkeypatch.setattr(
            yescaptcha.requests, "post", lambda *a, **k: responses.pop(0)
        )
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        assert solver.solve("https://example.com", "sitekey") == "tok"

    def test_solve_raises_when_create_task_fails(self, monkeypatch):
        """创建任务失败时 solve 必须抛异常。"""
        monkeypatch.setattr(
            yescaptcha.requests,
            "post",
            lambda *a, **k: FakeResponse({"errorId": 7, "errorDescription": "bad key"}),
        )
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
            solver.solve("https://example.com", "sitekey")
        assert "bad key" in str(excinfo.value)

    def test_verbose_mode_prints_progress(self, monkeypatch, capsys):
        """verbose=True 时必须打印进度（便于排障）。"""
        responses = [
            FakeResponse({"errorId": 0, "taskId": "t1"}),
            FakeResponse(
                {"errorId": 0, "status": "ready", "solution": {"token": "tok"}}
            ),
        ]
        monkeypatch.setattr(
            yescaptcha.requests, "post", lambda *a, **k: responses.pop(0)
        )
        solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")

        solver.solve("https://example.com", "sitekey", verbose=True)

        out = capsys.readouterr().out
        assert "创建" in out
