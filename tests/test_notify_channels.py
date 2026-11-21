"""通知渠道的 HTTP 契约测试。

覆盖每个渠道真正发请求的那一段：URL 构造、请求方法、响应判定。
这些是"用户以为推了、其实没推"的高发区。

注意各渠道的失败处理方式**不一样**，这是既有设计，不是缺陷：
只有个别渠道自己 try/except，其余渠道让异常冒泡，
由 _run_notifier 在线程边界统一隔离（见 test_notify_runtime.py）。
因此这里分别断言"成功时发一次请求""未配置时不发请求"
以及"异常是否被渠道自己吞掉"。
"""

import json

import pytest

import notify


class FakeResponse:
    """覆盖所有渠道用到的响应字段。"""

    def __init__(self, payload=None, status_code=200, text=None):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        # 企业微信 APP 的 get_access_token 会走 json.loads(resp.text)。
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload

    @property
    def ok(self):
        return 200 <= self.status_code < 300


# 成功响应：把所有渠道读到的键都给上
SUCCESS_PAYLOAD = {
    "code": 200,
    "errcode": 0,
    "errno": 0,
    "ok": True,
    "status": "ok",
    "ret": 0,
    "StatusCode": 0,
    "id": 1,
    "reason": "",
    "content": {"result": ["x"]},
    "hitokoto": "一句",
    "from": "出处",
    # 企业微信 APP 先取 access_token 再发消息。
    "access_token": "token-value",
    "errmsg": "ok",
}


@pytest.fixture
def captured(monkeypatch):
    """替换 requests.post / requests.get，记录调用并返回成功响应。"""
    calls = []

    def fake_post(url=None, data=None, headers=None, timeout=None, **kwargs):
        calls.append({"method": "POST", "url": url, "data": data, "headers": headers})
        return FakeResponse(dict(SUCCESS_PAYLOAD))

    def fake_get(url=None, headers=None, timeout=None, params=None, **kwargs):
        calls.append({"method": "GET", "url": url, "headers": headers})
        return FakeResponse(dict(SUCCESS_PAYLOAD))

    class _Requests:
        post = staticmethod(fake_post)
        get = staticmethod(fake_get)
        request = staticmethod(fake_post)

    monkeypatch.setattr(notify, "requests", _Requests)
    return calls


# 每个渠道：(函数名, 必填配置键, 预期请求次数)
# 企业微信 APP 需要先取 access_token 再发消息，因此是两次请求。
CHANNELS = [
    ("bark", {"BARK_PUSH": "device-key"}, 1),
    ("dingding_bot", {"DD_BOT_SECRET": "s", "DD_BOT_TOKEN": "t"}, 1),
    ("feishu_bot", {"FSKEY": "k"}, 1),
    ("go_cqhttp", {"GOBOT_URL": "http://g", "GOBOT_QQ": "1"}, 1),
    ("gotify", {"GOTIFY_URL": "http://g", "GOTIFY_TOKEN": "t"}, 1),
    ("iGot", {"IGOT_PUSH_KEY": "k"}, 1),
    ("serverJ", {"PUSH_KEY": "k"}, 1),
    ("pushdeer", {"DEER_KEY": "k"}, 1),
    ("chat", {"CHAT_URL": "http://c", "CHAT_TOKEN": "t"}, 1),
    ("pushplus_bot", {"PUSH_PLUS_TOKEN": "t"}, 1),
    ("weplus_bot", {"WE_PLUS_BOT_TOKEN": "t"}, 1),
    ("qmsg_bot", {"QMSG_KEY": "k", "QMSG_TYPE": "text"}, 1),
    ("wecom_app", {"QYWX_AM": "id,secret,user,agent"}, 2),
    ("wecom_bot", {"QYWX_KEY": "k"}, 1),
    ("telegram_bot", {"TG_BOT_TOKEN": "t", "TG_USER_ID": "1"}, 1),
    ("aibotk", {"AIBOTK_KEY": "k", "AIBOTK_TYPE": "contact", "AIBOTK_NAME": "n"}, 1),
    ("pushme", {"PUSHME_KEY": "k"}, 1),
    (
        "chronocat",
        {
            "CHRONOCAT_URL": "http://c",
            "CHRONOCAT_QQ": "user_id=1",
            "CHRONOCAT_TOKEN": "t",
        },
        1,
    ),
    ("custom_notify", {"WEBHOOK_URL": "http://h/$title", "WEBHOOK_METHOD": "POST"}, 1),
]


def _reset_config(monkeypatch, config):
    """把所有字符串配置清空，再填入该渠道的必填项。"""
    for key in list(notify.push_config):
        if isinstance(notify.push_config[key], str):
            monkeypatch.setitem(notify.push_config, key, "")
    for key, value in config.items():
        monkeypatch.setitem(notify.push_config, key, value)


@pytest.mark.parametrize("channel_name,config,expected_calls", CHANNELS)
def test_channel_sends_exactly_one_request(
    monkeypatch, captured, channel_name, config, expected_calls
):
    """每个渠道在配置齐全时必须发出预期次数的 HTTP 请求（真的推了）。"""
    _reset_config(monkeypatch, config)

    getattr(notify, channel_name)("标题", "内容")

    assert len(captured) == expected_calls, (
        f"{channel_name} 应发出 {expected_calls} 次请求，实际 {len(captured)} 次"
    )


@pytest.mark.parametrize("channel_name,config,expected_calls", CHANNELS)
def test_channel_without_config_does_not_send(
    monkeypatch, captured, channel_name, config, expected_calls
):
    """配置缺失时不得发请求（避免用空凭据打无效接口）。"""
    _reset_config(monkeypatch, {})

    getattr(notify, channel_name)("标题", "内容")

    assert captured == [], f"{channel_name} 在未配置时不应发请求"


@pytest.mark.parametrize("channel_name,config,expected_calls", CHANNELS)
def test_channel_failure_is_either_caught_or_propagates(
    monkeypatch, capsys, channel_name, config, expected_calls
):
    """HTTP 失败时，渠道要么自己吞掉并提示，要么把异常交给 _run_notifier 隔离。

    两种处理都合法，但必须可观测：自己吞掉的要打印失败提示。
    """
    _reset_config(monkeypatch, config)

    class Exploding:
        @staticmethod
        def post(*a, **k):
            raise RuntimeError("network down")

        @staticmethod
        def get(*a, **k):
            raise RuntimeError("network down")

        @staticmethod
        def request(*a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(notify, "requests", Exploding)

    channel = getattr(notify, channel_name)
    try:
        channel("标题", "内容")
    except RuntimeError:
        # 交给 _run_notifier 隔离 —— 这是多数渠道的既有设计。
        return

    out = capsys.readouterr().out
    assert "失败" in out or "取消推送" in out, f"{channel_name} 吞掉异常却没有提示"


class TestWebhookValidation:
    """自定义通知的入参校验。"""

    def test_non_http_url_rejected(self, monkeypatch, captured):
        """非 http(s) URL 必须被拒绝。"""
        monkeypatch.setitem(notify.push_config, "WEBHOOK_URL", "ftp://host/$title")
        monkeypatch.setitem(notify.push_config, "WEBHOOK_METHOD", "POST")

        notify.custom_notify("标题", "内容")

        assert captured == []

    def test_unsupported_method_rejected(self, monkeypatch, captured):
        """不支持的 HTTP 方法必须被拒绝。"""
        monkeypatch.setitem(notify.push_config, "WEBHOOK_URL", "http://host/$title")
        monkeypatch.setitem(notify.push_config, "WEBHOOK_METHOD", "TRACE")

        notify.custom_notify("标题", "内容")

        assert captured == []

    def test_missing_title_placeholder_rejected(self, monkeypatch, captured):
        """URL 与 body 中都没有 $title 时必须被拒绝。"""
        monkeypatch.setitem(notify.push_config, "WEBHOOK_URL", "http://host/hook")
        monkeypatch.setitem(notify.push_config, "WEBHOOK_METHOD", "POST")
        monkeypatch.setitem(notify.push_config, "WEBHOOK_BODY", "{}")

        notify.custom_notify("标题", "内容")

        assert captured == []


class TestParseHelpers:
    """Webhook 的头/体解析。"""

    def test_parse_headers_splits_lines(self):
        """多行头按行拆分（键统一小写，这是既有行为）。"""
        result = notify.parse_headers("A: 1\nB: 2")
        assert result == {"a": "1", "b": "2"}

    def test_parse_headers_empty_returns_empty(self):
        """空头返回空字典。"""
        assert notify.parse_headers("") == {}
        assert notify.parse_headers(None) == {}

    def test_parse_string_keeps_non_json_as_string(self):
        """不是合法 JSON 的值按原字符串保留。"""
        result = notify.parse_string("k: not-json")
        assert result == {"k": "not-json"}

    def test_parse_string_parses_json_values(self):
        """合法 JSON 的值被解析成对应类型。"""
        result = notify.parse_string('k: {"a": 1}')
        assert result == {"k": {"a": 1}}

    def test_parse_body_form_encoded(self):
        """application/x-www-form-urlencoded 走 urlencode。"""
        result = notify.parse_body("k: v", "application/x-www-form-urlencoded")
        assert result == "k=v"

    def test_parse_body_json(self):
        """application/json 返回重新序列化后的 JSON 字符串。

        注意 parse_body 解析的是 "key: value" 形式的正文，不是裸 JSON；
        裸 JSON 走的是 custom_notify 里直接透传 body 的路径。
        """
        result = notify.parse_body("k: v", "application/json")
        assert json.loads(result) == {"k": "v"}

    def test_parse_body_text_plain_returns_body(self):
        """text/plain 原样返回。"""
        assert notify.parse_body("plain", "text/plain") == "plain"

    def test_parse_body_with_placeholder_substitution(self):
        """占位符被替换。"""
        result = notify.parse_body(
            "k: $title", "text/plain", lambda v: v.replace("$title", "T")
        )
        assert result == "k: T"


class TestOne:
    """一言。"""

    def test_one_returns_quote(self, monkeypatch):
        """成功时返回一言文本。"""
        monkeypatch.setattr(
            notify.requests,
            "get",
            staticmethod(lambda *a, **k: FakeResponse(dict(SUCCESS_PAYLOAD))),
        )

        assert "一句" in notify.one()

    def test_one_returns_empty_on_failure(self, monkeypatch):
        """失败时返回空字符串，不影响主通知。"""

        def boom(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(notify.requests, "get", staticmethod(boom))

        assert notify.one() == ""


class TestNotifyConfigJson:
    """NOTIFY_CONFIG_JSON 的解析边界。"""

    def _reload_with(self, monkeypatch, raw):
        import importlib

        monkeypatch.setenv("NOTIFY_CONFIG_JSON", raw)
        try:
            importlib.reload(notify)
        finally:
            monkeypatch.delenv("NOTIFY_CONFIG_JSON", raising=False)
            importlib.reload(notify)

    def test_non_object_json_is_ignored(self, monkeypatch, capsys):
        """不是 JSON 对象的值必须被忽略并给出提示。"""
        self._reload_with(monkeypatch, "[1, 2, 3]")

        out = capsys.readouterr().out
        assert "JSON 对象" in out

    def test_malformed_json_is_ignored(self, monkeypatch, capsys):
        """非法 JSON 必须被忽略并给出提示。"""
        self._reload_with(monkeypatch, "{not json")

        out = capsys.readouterr().out
        assert "解析失败" in out

    def test_valid_object_overrides_registered_keys(self, monkeypatch):
        """合法 JSON 覆盖已登记的键。"""
        import importlib

        monkeypatch.setenv("NOTIFY_CONFIG_JSON", '{"TG_USER_ID": "42"}')
        try:
            importlib.reload(notify)
            assert notify.push_config["TG_USER_ID"] == "42"
        finally:
            monkeypatch.delenv("NOTIFY_CONFIG_JSON", raising=False)
            importlib.reload(notify)


class TestSmtpFailure:
    """SMTP 失败路径。"""

    def test_smtp_failure_is_reported(self, monkeypatch, capsys):
        """SMTP 抛异常时必须提示失败，不得让通知线程静默死掉。"""

        class Boom:
            def __init__(self, *a, **k):
                raise RuntimeError("smtp down")

        monkeypatch.setattr(notify.smtplib, "SMTP_SSL", Boom)
        monkeypatch.setitem(notify.push_config, "SMTP_SERVER", "smtp.example.com:465")
        monkeypatch.setitem(notify.push_config, "SMTP_EMAIL", "a@example.com")
        monkeypatch.setitem(notify.push_config, "SMTP_PASSWORD", "pw")
        monkeypatch.setitem(notify.push_config, "SMTP_NAME", "n")
        monkeypatch.setitem(notify.push_config, "SMTP_SSL", "true")

        notify.smtp("标题", "内容")

        out = capsys.readouterr().out
        assert "推送失败" in out


class TestSendEdgeCases:
    """send() 的边界。"""

    def test_hitokoto_appends_a_quote(self, monkeypatch):
        """开启一言时，通知内容必须追加一言。"""
        sent = {}

        def channel(title, content):
            sent.update(title=title, content=content)

        monkeypatch.setattr(notify, "_config_bool", lambda v: True)
        monkeypatch.setattr(notify, "one", lambda: "一句")
        monkeypatch.setattr(notify, "add_notify_function", lambda: [channel])

        notify.send("标题", "内容")

        assert "一句" in sent["content"]

    def test_channel_timeout_is_reported(self, monkeypatch, capsys):
        """渠道超时未完成时必须给出提示（不得静默放弃）。"""

        def slow_channel(title, content):
            import time as _time

            _time.sleep(5)

        monkeypatch.setattr(notify, "_config_bool", lambda v: False)
        monkeypatch.setattr(notify, "add_notify_function", lambda: [slow_channel])
        monkeypatch.setattr(notify, "NOTIFY_THREAD_TIMEOUT", 1)

        notify.send("标题", "内容")

        out = capsys.readouterr().out
        assert "超时未完成" in out
