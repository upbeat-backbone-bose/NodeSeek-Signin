"""端到端测试：签到主流程 run()。

不访问网络：通过 monkeypatch 替换 sign()/get_signin_stats()，
验证账号与 Cookie 的槽位对应关系、退出码以及通知内容。

覆盖审计发现的问题：
  - 末尾多余分隔符不应造出永远失败的"幽灵账号"（退出码必须为 0）。
  - "已完成签到" 必须能被正确识别为 already，而不是被 success 标志掩盖。
  - 账号数与 Cookie 数不一致时应给出告警。
"""

import io
import json
import os

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
    """替换网络调用，返回 (签到结果, 统计结果)。"""
    calls = []

    def fake_sign(cookie, ns_random):
        calls.append(cookie)
        return sign_result, "ok"

    def fake_stats(cookie, days=30):
        return stats, "ok"

    monkeypatch.setattr(nodeseek_sign, "sign", fake_sign)
    monkeypatch.setattr(nodeseek_sign, "get_signin_stats", fake_stats)
    return calls


def _parse_result(capsys):
    """从 stdout 中提取 RESULT JSON。"""
    out = capsys.readouterr().out
    for line in out.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[len("RESULT "):])
    raise AssertionError(f"未找到 RESULT 输出:\n{out}")


class TestRunExitCode:
    def test_trailing_separator_does_not_cause_failure(self, monkeypatch, capsys):
        """末尾多余的 "&" 不应产生幽灵账号，退出码应为 0。"""
        monkeypatch.setenv("NS_COOKIE", "c1&c2&")
        _install_fakes(monkeypatch)

        exit_code = nodeseek_sign.run()
        result = _parse_result(capsys)

        assert exit_code == 0
        assert result["failed"] == 0
        assert result["total"] == 2
        assert result["succeeded"] == 2
        assert result["success"] is True

    def test_middle_empty_slot_is_a_real_account(self, monkeypatch, capsys):
        """中间空槽位代表一个真实账号：没有 Cookie 也没有凭据时应计为失败。"""
        monkeypatch.setenv("NS_COOKIE", "c1&&c3")
        _install_fakes(monkeypatch)

        exit_code = nodeseek_sign.run()
        result = _parse_result(capsys)

        assert exit_code == 1
        assert result["total"] == 3
        assert result["failed"] == 1

    def test_no_config_exits_nonzero(self, monkeypatch, capsys):
        _install_fakes(monkeypatch)
        assert nodeseek_sign.run() == 1


class TestRunSlotAlignment:
    def test_cookie_slots_map_to_accounts_in_order(self, monkeypatch, capsys):
        """第 i 个 Cookie 必须对应第 i 个账号。"""
        monkeypatch.setenv("NS_COOKIE", "c1&c2&c3")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("USER1", "u2")
        monkeypatch.setenv("PASS1", "p2")
        monkeypatch.setenv("USER2", "u3")
        monkeypatch.setenv("PASS2", "p3")
        calls = _install_fakes(monkeypatch)

        assert nodeseek_sign.run() == 0
        assert calls == ["c1", "c2", "c3"]

    def test_user1_only_starts_at_first_account(self, monkeypatch, capsys):
        """只配置 USER1（没有 USER/PASS）时，USER1 就是第 1 个账号。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER1", "u1")
        monkeypatch.setenv("PASS1", "p1")
        calls = _install_fakes(monkeypatch)

        assert nodeseek_sign.run() == 0
        assert calls == ["c1"]

    def test_mismatch_between_accounts_and_cookies_warns(self, monkeypatch, capsys):
        """账号数与 Cookie 数不一致时必须显式告警，而不是静默错位。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("USER1", "u2")
        monkeypatch.setenv("PASS1", "p2")
        _install_fakes(monkeypatch)

        nodeseek_sign.run()
        out = capsys.readouterr().out
        assert "[警告]" in out
        assert "槽位错位" in out

    def test_misaligned_slot_does_not_buy_captcha(self, monkeypatch, capsys):
        """账号多于 Cookie 时，多出来的账号身份不可信，绝不能购买验证码。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("USER1", "u2")
        monkeypatch.setenv("PASS1", "p2")
        monkeypatch.setenv("CLIENT_KEY", "key")
        calls = []
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: calls.append(a[0]) or "fresh",
        )
        _install_fakes(monkeypatch)

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert calls == []
        assert "跳过重新登录" in out
        assert exit_code == 1

    def test_account_without_any_cookie_still_logs_in(self, monkeypatch, capsys):
        """完全没有 Cookie 时（只有账号密码），应正常重新登录。"""
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("CLIENT_KEY", "key")
        calls = []
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: calls.append(a[0]) or "fresh",
        )
        _install_fakes(monkeypatch)

        nodeseek_sign.run()

        assert calls == ["u1"]


class TestRunDoesNotBuyCaptchaOnTransientFailures:
    """403 / 5xx / 网络异常绝不能触发付费验证码求解。"""

    def _assert_no_login(self, monkeypatch, capsys, sign_result):
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("CLIENT_KEY", "key")
        calls = []
        monkeypatch.setattr(nodeseek_sign, "sign", lambda *a, **k: sign_result)
        monkeypatch.setattr(
            nodeseek_sign,
            "session_login",
            lambda *a, **k: calls.append(a) or "fresh",
        )
        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out
        assert calls == []
        assert "跳过重新登录" in out
        assert exit_code == 1

    def test_forbidden_does_not_trigger_paid_login(self, monkeypatch, capsys):
        self._assert_no_login(
            monkeypatch, capsys, ("forbidden", "403 Forbidden")
        )

    def test_server_error_does_not_trigger_paid_login(self, monkeypatch, capsys):
        self._assert_no_login(
            monkeypatch, capsys, ("error", "服务端错误 (500)")
        )


class TestRunAlreadyCounting:
    def test_already_is_counted_separately(self, monkeypatch, capsys):
        """接口返回 success=true + "已完成签到" 时应记为 already。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        _install_fakes(monkeypatch, sign_result="already")

        exit_code = nodeseek_sign.run()
        result = _parse_result(capsys)

        assert exit_code == 0
        assert result["already"] == 1
        assert result["succeeded"] == 0
        assert result["failed"] == 0
        assert result["success"] is True

    def test_success_is_counted_as_success(self, monkeypatch, capsys):
        monkeypatch.setenv("NS_COOKIE", "c1")
        _install_fakes(monkeypatch, sign_result="success")

        assert nodeseek_sign.run() == 0
        result = _parse_result(capsys)
        assert result["succeeded"] == 1
        assert result["already"] == 0
        assert result["success"] is True


class TestRunNotification:
    def test_summary_contains_each_account(self, monkeypatch, capsys):
        """通知汇总里应包含每个账号的状态。"""
        monkeypatch.setenv("NS_COOKIE", "c1&c2")
        _install_fakes(monkeypatch)

        sent = {}
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        monkeypatch.setattr(
            nodeseek_sign, "send", lambda title, content: sent.update(
                title=title, content=content
            )
        )

        nodeseek_sign.run()
        assert sent["title"] == "NodeSeek 签到"
        assert "账号 账号1" in sent["content"]
        assert "账号 账号2" in sent["content"]

    def test_truncated_stats_are_labelled(self, monkeypatch, capsys):
        """统计被截断时必须在展示中标注出来。"""
        monkeypatch.setenv("NS_COOKIE", "c1")
        _install_fakes(
            monkeypatch,
            stats={
                "total_amount": 10,
                "average": 5.0,
                "days_count": 2,
                "records": [],
                "period": "近30天(数据不完整)",
                "truncated": True,
            },
        )

        sent = {}
        monkeypatch.setattr(nodeseek_sign, "hadsend", True)
        monkeypatch.setattr(
            nodeseek_sign, "send", lambda title, content: sent.update(content=content)
        )

        nodeseek_sign.run()
        assert "数据不完整" in sent["content"]


class TestRunCookiePersistence:
    def test_docker_mode_persists_cookie_to_file(self, monkeypatch, tmp_path, capsys):
        """Docker 模式下重新登录后应写回 Cookie 文件，且保持槽位不变。"""
        cookie_file = tmp_path / "NS_COOKIE.txt"
        cookie_file.write_text("c1&&c3", encoding="utf-8")
        monkeypatch.setenv("IN_DOCKER", "true")
        monkeypatch.setenv("CLIENT_KEY", "key")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        monkeypatch.setenv("USER1", "u2")
        monkeypatch.setenv("PASS1", "p2")
        monkeypatch.setattr(nodeseek_sign, "COOKIE_FILE_PATH", str(cookie_file))
        _install_fakes(monkeypatch)

        # 第 1 个账号的 Cookie 失效；第 2 个账号没有 Cookie。
        # 两者都应通过重新登录拿到新 Cookie，并写回各自原来的槽位。
        def fake_sign(cookie, ns_random):
            return ("invalid", "未登录") if cookie == "c1" else ("success", "ok")

        def fake_login(user, password, solver_type, api_base_url, client_key):
            return f"fresh-{user}"

        monkeypatch.setattr(nodeseek_sign, "sign", fake_sign)
        monkeypatch.setattr(nodeseek_sign, "session_login", fake_login)

        exit_code = nodeseek_sign.run()
        content = cookie_file.read_text(encoding="utf-8")

        assert exit_code == 0
        # 第 2 个槽位原本为空，登录后被填充；第 3 个槽位保持不变。
        assert content == "fresh-u1&fresh-u2&c3"

    def test_unreadable_cookie_file_does_not_abort_run(self, monkeypatch, capsys):
        """Cookie 文件读取失败时必须给出明确提示，而不是抛未捕获异常中断签到。"""
        monkeypatch.setenv("IN_DOCKER", "true")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        _install_fakes(monkeypatch)

        def boom(path):
            raise nodeseek_sign.CookieFileError(f"无法读取 Cookie 文件 {path}")

        monkeypatch.setattr(nodeseek_sign, "load_cookie_file", boom)

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert "读取 Cookie 文件失败" in out
        # 读取失败按空 Cookie 处理：账号因缺 Cookie 失败，但没有未捕获异常。
        assert exit_code == 1

    def test_github_writeback_disabled_is_not_a_failure(self, monkeypatch, capsys):
        """默认关闭回写时不应报"保存失败"。"""
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("CLIENT_KEY", "key")
        monkeypatch.setenv("NS_COOKIE", "c1")
        monkeypatch.setenv("USER", "u1")
        monkeypatch.setenv("PASS", "p1")
        _install_fakes(monkeypatch)

        # 触发重新登录，使 cookies_updated 为真，从而走到保存分支。
        def fake_sign(cookie, ns_random):
            return ("invalid", "未登录") if cookie == "c1" else ("success", "ok")

        monkeypatch.setattr(nodeseek_sign, "sign", fake_sign)
        monkeypatch.setattr(
            nodeseek_sign, "session_login", lambda *a, **k: "fresh1"
        )

        exit_code = nodeseek_sign.run()
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "保存 Cookie 失败" not in out
        assert "已跳过保存 Cookie" in out
