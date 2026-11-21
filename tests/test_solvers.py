import pytest

import turnstile_solver
import yescaptcha


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_turnstile_rejects_invalid_api_url():
    with pytest.raises(turnstile_solver.TurnstileSolverError):
        turnstile_solver.TurnstileSolver("file:///tmp/api", "key")


def test_yescaptcha_rejects_invalid_api_url():
    with pytest.raises(yescaptcha.YesCaptchaSolverError):
        yescaptcha.YesCaptchaSolver("not-a-url", "key")


def test_turnstile_stops_on_terminal_status(monkeypatch):
    calls = []
    responses = [
        FakeResponse({"errorId": 0, "taskId": "task-1"}),
        FakeResponse({"errorId": 0, "status": "failed", "errorDescription": "nope"}),
    ]

    def fake_post(*args, **kwargs):
        calls.append(args[0])
        return responses.pop(0)

    monkeypatch.setattr(turnstile_solver.requests, "post", fake_post)
    solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
    with pytest.raises(turnstile_solver.TurnstileSolverError):
        solver.solve("https://example.com", "sitekey", verbose=False)
    assert len(calls) == 2


def test_turnstile_returns_token(monkeypatch):
    responses = [
        FakeResponse({"errorId": 0, "taskId": "task-1"}),
        FakeResponse(
            {
                "errorId": 0,
                "status": "completed",
                "result": {"response": {"token": "tok"}},
            }
        ),
    ]
    monkeypatch.setattr(
        turnstile_solver.requests, "post", lambda *a, **k: responses.pop(0)
    )
    solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
    assert solver.solve("https://example.com", "sitekey") == "tok"


def test_turnstile_returns_token_from_ready_solution(monkeypatch):
    """2captcha 风格服务返回 status=ready + solution.token，必须能取到令牌。"""
    responses = [
        FakeResponse({"errorId": 0, "taskId": "task-1"}),
        FakeResponse({"errorId": 0, "status": "ready", "solution": {"token": "tok"}}),
    ]
    monkeypatch.setattr(
        turnstile_solver.requests, "post", lambda *a, **k: responses.pop(0)
    )
    solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
    assert solver.solve("https://example.com", "sitekey") == "tok"


def test_turnstile_stops_on_error_id(monkeypatch):
    calls = []
    responses = [
        FakeResponse({"errorId": 0, "taskId": "task-1"}),
        FakeResponse({"errorId": 12, "errorDescription": "bad key"}),
    ]

    def fake_post(*args, **kwargs):
        calls.append(args[0])
        return responses.pop(0)

    monkeypatch.setattr(turnstile_solver.requests, "post", fake_post)
    solver = turnstile_solver.TurnstileSolver("https://api.example.com", "key")
    with pytest.raises(turnstile_solver.TurnstileSolverError):
        solver.solve("https://example.com", "sitekey", verbose=False)
    assert len(calls) == 2


def test_yescaptcha_stops_on_terminal_error(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(args[0])
        return FakeResponse({"errorId": 7, "errorDescription": "bad key"})

    monkeypatch.setattr(yescaptcha.requests, "post", fake_post)
    solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
    with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
        solver._get_task_result("task-1")
    # 真实原因必须透出，不能被吞成 None。
    assert "bad key" in str(excinfo.value)
    assert len(calls) == 1


def test_yescaptcha_create_task_surfaces_api_error(monkeypatch):
    """创建任务时 API 返回 errorId 必须抛异常并透出原因，不能静默返回 None。"""
    monkeypatch.setattr(
        yescaptcha.requests,
        "post",
        lambda *a, **k: FakeResponse({"errorId": 7, "errorDescription": "余额不足"}),
    )
    solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
    with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
        solver._create_task("https://example.com", "sitekey")
    assert "余额不足" in str(excinfo.value)


def test_yescaptcha_create_task_requires_task_id(monkeypatch):
    """API 返回成功但没有 taskId 时必须抛异常，不能返回 None 当作失败。"""
    monkeypatch.setattr(
        yescaptcha.requests,
        "post",
        lambda *a, **k: FakeResponse({"errorId": 0}),
    )
    solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
    with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
        solver._create_task("https://example.com", "sitekey")
    assert "taskId" in str(excinfo.value)


def test_yescaptcha_reports_http_status_on_create(monkeypatch):
    monkeypatch.setattr(
        yescaptcha.requests,
        "post",
        lambda *a, **k: FakeResponse({}, status_code=500),
    )
    solver = yescaptcha.YesCaptchaSolver("https://api.example.com", "key")
    with pytest.raises(yescaptcha.YesCaptchaSolverError) as excinfo:
        solver._create_task("https://example.com", "sitekey")
    assert "500" in str(excinfo.value)


def test_yescaptcha_returns_ready_token(monkeypatch):
    responses = [
        FakeResponse({"errorId": 0, "status": "processing"}),
        FakeResponse({"errorId": 0, "status": "ready", "solution": {"token": "tok"}}),
    ]
    monkeypatch.setattr(yescaptcha.requests, "post", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(yescaptcha.time, "sleep", lambda _seconds: None)
    solver = yescaptcha.YesCaptchaSolver(
        "https://api.example.com", "key", max_retries=2, retry_interval=1
    )
    assert solver._get_task_result("task-1") == "tok"
