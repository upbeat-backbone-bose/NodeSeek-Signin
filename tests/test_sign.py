import pytest

import nodeseek_sign


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self.payload = payload or {}

    def json(self):
        return self.payload


def test_sign_without_cookie_is_invalid():
    assert nodeseek_sign.sign("", "false") == ("invalid", "无有效Cookie")


def test_sign_success(monkeypatch):
    def fake_request(*args, **kwargs):
        return FakeResponse(payload={"success": True, "message": "获得 5 个鸡腿"}), "chrome146", None

    monkeypatch.setattr(nodeseek_sign, "_request_with_impersonate_fallback", fake_request)
    status, message = nodeseek_sign.sign("session=abc", "false")
    assert status == "success"
    assert "鸡腿" in message


def test_sign_already_checked_in(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (FakeResponse(payload={"message": "今日已完成签到"}), "chrome146", None),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "already"


def test_sign_already_wins_over_success_flag(monkeypatch):
    """接口在"今日已签到"时也可能返回 success=true，此时必须记为 already。"""
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (
            FakeResponse(payload={"success": True, "message": "今日已完成签到"}),
            "chrome146",
            None,
        ),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "already"


def test_sign_reward_wins_over_already(monkeypatch):
    """消息同时提到鸡腿与"已完成签到"时，以拿到奖励（新签到）为准。"""
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (
            FakeResponse(payload={"success": True, "message": "今日已完成签到，获得 5 个鸡腿"}),
            "chrome146",
            None,
        ),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "success"


def test_sign_expired_session_wins_over_success_flag(monkeypatch):
    """会话失效必须优先于 success 标志，否则失效的 Cookie 永远不会被刷新。"""
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (
            FakeResponse(payload={"success": True, "message": "请先登录"}),
            "chrome146",
            None,
        ),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "invalid"


def test_sign_404_status_is_invalid(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (FakeResponse(payload={"status": 404, "message": "ok"}), "chrome146", None),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "invalid"


def test_sign_unauthorized_message_is_invalid(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (FakeResponse(payload={"status": 200, "message": "未登录"}), "chrome146", None),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "invalid"


def test_sign_cloudflare_forbidden(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (
            FakeResponse(status_code=403, text="Just a moment...", payload={}),
            "chrome146",
            None,
        ),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "forbidden"


def test_sign_rate_limited_is_error(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (FakeResponse(status_code=429, text="", payload={}), "chrome146", None),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "error"


def test_sign_5xx_is_error(monkeypatch):
    monkeypatch.setattr(
        nodeseek_sign,
        "_request_with_impersonate_fallback",
        lambda *a, **k: (
            FakeResponse(status_code=500, text="", payload={}),
            "chrome146",
            None,
        ),
    )
    assert nodeseek_sign.sign("session=abc", "false")[0] == "error"


def test_transport_error_does_not_retry(monkeypatch):
    calls = []

    def failing_request(*args, **kwargs):
        calls.append(kwargs.get("impersonate"))
        raise TimeoutError("boom")

    monkeypatch.setattr(nodeseek_sign.requests, "request", failing_request)
    response, used, error = nodeseek_sign._request_with_impersonate_fallback(
        "POST", "https://example.com", headers={}
    )
    assert response is None
    assert error is not None
    assert used
    assert len(calls) == 1


def test_cloudflare_challenge_rotates_fingerprint(monkeypatch):
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs.get("impersonate"))
        if len(calls) == 1:
            return FakeResponse(status_code=403, text="Just a moment", payload={})
        return FakeResponse(status_code=200, payload={"success": True})

    monkeypatch.setattr(nodeseek_sign.requests, "request", fake_request)
    response, used, error = nodeseek_sign._request_with_impersonate_fallback(
        "POST", "https://example.com", headers={}
    )
    assert response is not None
    assert response.status_code == 200
    assert error is None
    assert len(calls) == 2


def test_non_challenge_403_does_not_rotate(monkeypatch):
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs.get("impersonate"))
        return FakeResponse(status_code=403, text="Forbidden", payload={})

    monkeypatch.setattr(nodeseek_sign.requests, "request", fake_request)
    response, _used, error = nodeseek_sign._request_with_impersonate_fallback(
        "POST", "https://example.com", headers={}
    )
    assert response is not None
    assert response.status_code == 403
    assert error is None
    assert len(calls) == 1


def test_reported_fingerprint_matches_last_request(monkeypatch):
    """返回的指纹必须是最后实际发出请求用的那个，而不是候选列表的最后一项。"""
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs.get("impersonate"))
        return FakeResponse(status_code=403, text="Just a moment", payload={})

    monkeypatch.setattr(nodeseek_sign.requests, "request", fake_request)
    monkeypatch.setattr(nodeseek_sign, "IMPERSONATE_ATTEMPTS", 2)
    _response, used, _error = nodeseek_sign._request_with_impersonate_fallback(
        "POST", "https://example.com", headers={}
    )

    assert len(calls) == 2
    assert used == calls[-1]


def test_reported_fingerprint_matches_failed_request(monkeypatch):
    """请求在第一个候选上就失败时，报告的指纹必须是那个候选本身。"""
    calls = []

    def fake_request(*args, **kwargs):
        calls.append(kwargs.get("impersonate"))
        raise TimeoutError("boom")

    monkeypatch.setattr(nodeseek_sign.requests, "request", fake_request)
    monkeypatch.setattr(nodeseek_sign, "IMPERSONATE_ATTEMPTS", 3)
    _response, used, error = nodeseek_sign._request_with_impersonate_fallback(
        "POST", "https://example.com", headers={}
    )

    assert len(calls) == 1
    assert error is not None
    assert used == calls[0]


def test_candidate_list_is_bounded():
    assert 1 <= len(nodeseek_sign.IMPERSONATE_CANDIDATES) <= 5
    assert len(nodeseek_sign.IMPERSONATE_CANDIDATES) <= nodeseek_sign.IMPERSONATE_ATTEMPTS


def test_candidates_are_supported_by_installed_curl_cffi():
    assert nodeseek_sign.SUPPORTED_IMPERSONATE
    for candidate in nodeseek_sign.IMPERSONATE_CANDIDATES:
        assert candidate in nodeseek_sign.SUPPORTED_IMPERSONATE


def test_unsupported_impersonate_is_skipped(monkeypatch):
    monkeypatch.setattr(nodeseek_sign, "IMPERSONATE_VERSION", "not-a-real-browser")
    monkeypatch.setattr(nodeseek_sign, "IMPERSONATE_ATTEMPTS", 3)
    candidates = nodeseek_sign._get_impersonate_candidates()
    assert candidates
    assert "not-a-real-browser" not in candidates
    assert all(item in nodeseek_sign.SUPPORTED_IMPERSONATE for item in candidates)


def test_mask_string_hides_middle():
    assert nodeseek_sign._mask_string("abcdef", 2, 1) == "ab***f"
    assert nodeseek_sign._mask_string("ab", 2, 1) == "**"
