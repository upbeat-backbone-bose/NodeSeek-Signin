"""凭据持久化路径的回归测试：青龙面板、Docker 文件与统一分发。

覆盖 SPEC.md 的 N-4（save_cookie 的返回值语义）与负向约束 N-6。
这些路径负责把 Cookie 写到用户选择的存储介质上，写错位置或写失败
都会让用户丢凭据或把凭据写到不该写的地方。
"""

import os

import pytest

import nodeseek_sign


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith(("NS_", "USER", "PASS", "GH_", "GITHUB_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("IN_DOCKER", "CLIENT_KEY", "TIMEOUT", "DEBUG"):
        monkeypatch.delenv(key, raising=False)


class FakeQlApi:
    """模拟青龙面板 API。"""

    def __init__(self, get_envs_result=None, delete_result=None, create_result=None):
        self.get_envs_result = get_envs_result or {"code": 200, "data": []}
        self.delete_result = delete_result or {"code": 200}
        self.create_result = create_result or {"code": 200}
        self.created = []
        self.deleted = []

    def getEnvs(self, payload):
        return self.get_envs_result

    def deleteEnvs(self, payload):
        self.deleted.append(payload)
        return self.delete_result

    def createEnv(self, payload):
        self.created.append(payload)
        return self.create_result


class TestQinglongWriteback:
    """青龙面板变量写入与删除。"""

    def test_missing_qlapi_returns_false(self, monkeypatch):
        """没有 QLAPI 时报告失败并说明原因。"""
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: None)

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is False

    def test_creates_variable_when_none_exists(self, monkeypatch):
        """没有同名变量时直接创建。"""
        qlapi = FakeQlApi(get_envs_result={"code": 200, "data": []})
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is True
        assert len(qlapi.created) == 1
        env = qlapi.created[0]["envs"][0]
        assert env["name"] == "NS_COOKIE"
        assert env["value"] == "c1"

    def test_deletes_existing_variable_before_creating(self, monkeypatch):
        """已存在同名变量时先删除再创建，避免出现重复变量。"""
        qlapi = FakeQlApi(
            get_envs_result={"code": 200, "data": [{"name": "NS_COOKIE", "id": 7}]}
        )
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is True
        assert qlapi.deleted == [{"ids": [7]}]
        assert len(qlapi.created) == 1

    def test_create_failure_returns_false(self, monkeypatch):
        """创建失败时报告失败，不能假装成功。"""
        qlapi = FakeQlApi(create_result={"code": 500})
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is False

    def test_delete_failure_still_attempts_create(self, monkeypatch):
        """删除失败时仍尝试创建（宁可重复也不能丢凭据）。"""
        qlapi = FakeQlApi(delete_result={"code": 500})
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is True
        assert len(qlapi.created) == 1

    def test_api_exception_returns_false(self, monkeypatch):
        """API 抛异常时报告失败而不是向上抛。"""

        class Exploding:
            def getEnvs(self, payload):
                raise RuntimeError("boom")

        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: Exploding())

        assert nodeseek_sign.save_cookie_to_ql("NS_COOKIE", "c1") is False

    def test_delete_env_without_qlapi_returns_false(self, monkeypatch):
        """没有 QLAPI 时删除操作报告失败。"""
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: None)

        assert nodeseek_sign.delete_ql_env("NS_COOKIE") is False

    def test_delete_env_reports_success_when_absent(self, monkeypatch):
        """变量不存在时删除操作视为成功（目标已达成）。"""
        qlapi = FakeQlApi(get_envs_result={"code": 200, "data": []})
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.delete_ql_env("NS_COOKIE") is True
        assert qlapi.deleted == []


class TestDockerFileWriteback:
    """Docker 模式下 Cookie 写文件。"""

    def test_writes_to_cookie_file(self, monkeypatch, tmp_path):
        """Cookie 必须写到 cookie/NS_COOKIE.txt。"""
        target = tmp_path / "NS_COOKIE.txt"
        monkeypatch.setattr(nodeseek_sign, "COOKIE_FILE_PATH", str(target))

        assert nodeseek_sign.save_cookie_to_file("c1&&c3") is True
        assert target.read_text(encoding="utf-8") == "c1&&c3"

    def test_write_failure_returns_false(self, monkeypatch):
        """写入失败时报告失败并说明原因。"""

        def boom(*a, **k):
            raise OSError("disk full")

        monkeypatch.setattr(nodeseek_sign, "save_cookie_file", boom)

        assert nodeseek_sign.save_cookie_to_file("c1") is False


class TestSaveCookieDispatch:
    """save_cookie 按环境分发，且返回值语义一致。"""

    def test_docker_environment_writes_file(self, monkeypatch, tmp_path):
        """Docker 环境写文件。"""
        target = tmp_path / "NS_COOKIE.txt"
        monkeypatch.setattr(nodeseek_sign, "detect_environment", lambda: "docker")
        monkeypatch.setattr(nodeseek_sign, "COOKIE_FILE_PATH", str(target))

        assert nodeseek_sign.save_cookie("NS_COOKIE", "c1") is True
        assert target.read_text(encoding="utf-8") == "c1"

    def test_qinglong_environment_writes_variable(self, monkeypatch):
        """青龙环境写面板变量。"""
        qlapi = FakeQlApi()
        monkeypatch.setattr(nodeseek_sign, "detect_environment", lambda: "qinglong")
        monkeypatch.setattr(nodeseek_sign, "_get_qlapi", lambda: qlapi)

        assert nodeseek_sign.save_cookie("NS_COOKIE", "c1") is True
        assert qlapi.created[0]["envs"][0]["value"] == "c1"

    def test_github_environment_writes_secret(self, monkeypatch):
        """GitHub 环境写加密 Secret。"""
        monkeypatch.setattr(nodeseek_sign, "detect_environment", lambda: "github")
        monkeypatch.setattr(
            nodeseek_sign, "save_cookie_to_github_secret", lambda *a: True
        )

        assert nodeseek_sign.save_cookie("NS_COOKIE", "c1") is True

    def test_unsupported_environment_returns_none(self, monkeypatch):
        """不支持的环境返回 None（未执行保存），而非 False（失败）。"""
        monkeypatch.setattr(nodeseek_sign, "detect_environment", lambda: "unknown")

        assert nodeseek_sign.save_cookie("NS_COOKIE", "c1") is None
