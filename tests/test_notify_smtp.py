"""通知模块的端到端测试。

不发送真实邮件：用桩替换 smtplib.SMTP / SMTP_SSL，验证
  - TLS 上下文确实校验服务器证书（审计发现原实现不校验，可被中间人劫持）。
  - SMTP_SSL=false 时走 STARTTLS 且同样启用证书校验。
  - 服务器地址解析（host / host:port）。
"""

import ssl

import notify


class FakeSmtpServer:
    """记录被调用的方法序列。"""

    instances = []

    def __init__(self, host="", port=0, *args, **kwargs):
        self.host = host
        self.port = port
        self.timeout = kwargs.get("timeout")
        self.context = kwargs.get("context")
        self.calls = []
        FakeSmtpServer.instances.append(self)

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.starttls_context = context

    def login(self, user, password):
        self.calls.append("login")

    def sendmail(self, from_addr, to_addr, message):
        self.calls.append("sendmail")

    def quit(self):
        self.calls.append("quit")


class TestSmtpContext:
    def test_context_verifies_certificates(self):
        ctx = notify._smtp_ssl_context()
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    def test_ssl_path_uses_verifying_context(self, monkeypatch):
        FakeSmtpServer.instances.clear()
        monkeypatch.setattr(notify.smtplib, "SMTP_SSL", FakeSmtpServer)
        monkeypatch.setitem(notify.push_config, "SMTP_SERVER", "smtp.example.com:465")
        monkeypatch.setitem(notify.push_config, "SMTP_EMAIL", "a@example.com")
        monkeypatch.setitem(notify.push_config, "SMTP_PASSWORD", "pw")
        monkeypatch.setitem(notify.push_config, "SMTP_NAME", "n")
        monkeypatch.setitem(notify.push_config, "SMTP_SSL", "true")

        notify.smtp("标题", "内容")

        server = FakeSmtpServer.instances[-1]
        assert server.host == "smtp.example.com"
        assert server.port == 465
        assert server.context is not None
        assert server.context.verify_mode == ssl.CERT_REQUIRED
        assert server.timeout == notify.REQUEST_TIMEOUT
        assert server.timeout is not None

    def test_starttls_path_uses_verifying_context(self, monkeypatch):
        FakeSmtpServer.instances.clear()
        monkeypatch.setattr(notify.smtplib, "SMTP", FakeSmtpServer)
        monkeypatch.setitem(notify.push_config, "SMTP_SERVER", "smtp.example.com")
        monkeypatch.setitem(notify.push_config, "SMTP_EMAIL", "a@example.com")
        monkeypatch.setitem(notify.push_config, "SMTP_PASSWORD", "pw")
        monkeypatch.setitem(notify.push_config, "SMTP_NAME", "n")
        monkeypatch.setitem(notify.push_config, "SMTP_SSL", "false")

        notify.smtp("标题", "内容")

        server = FakeSmtpServer.instances[-1]
        assert "starttls" in server.calls
        assert server.starttls_context is not None
        assert server.starttls_context.verify_mode == ssl.CERT_REQUIRED
        assert server.timeout == notify.REQUEST_TIMEOUT
        assert server.timeout is not None
        # 登录必须发生在 TLS 升级之后，密码才不会明文传输。
        assert server.calls.index("starttls") < server.calls.index("login")


class TestParseSmtpServer:
    def test_host_only_uses_ssl_default_port(self):
        assert notify._parse_smtp_server("smtp.example.com", True) == (
            "smtp.example.com",
            465,
        )

    def test_host_only_uses_starttls_default_port(self):
        assert notify._parse_smtp_server("smtp.example.com", False) == (
            "smtp.example.com",
            587,
        )

    def test_host_and_port_are_split(self):
        assert notify._parse_smtp_server("smtp.example.com:2525", True) == (
            "smtp.example.com",
            2525,
        )

    def test_invalid_port_falls_back_to_defaults(self):
        # 非法端口被丢弃，不能留在主机名里。
        assert notify._parse_smtp_server("smtp.example.com:notaport", True) == (
            "smtp.example.com",
            465,
        )
