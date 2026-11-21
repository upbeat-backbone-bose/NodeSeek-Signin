import importlib
import inspect
import re

import notify


def test_config_bool_accepts_strings_and_bools():
    assert notify._config_bool(True) is True
    assert notify._config_bool("true") is True
    assert notify._config_bool("1") is True
    assert notify._config_bool("yes") is True
    assert notify._config_bool("on") is True
    assert notify._config_bool(False) is False
    assert notify._config_bool("false") is False
    assert notify._config_bool("0") is False
    assert notify._config_bool(None) is False


def test_console_false_string_does_not_enable_channel(monkeypatch):
    monkeypatch.setitem(notify.push_config, "CONSOLE", "false")
    assert notify.console not in notify.add_notify_function()


def test_console_true_string_enables_channel(monkeypatch):
    monkeypatch.setitem(notify.push_config, "CONSOLE", "true")
    assert notify.console in notify.add_notify_function()


def test_notify_config_json_overrides_env(monkeypatch):
    """NOTIFY_CONFIG_JSON 中的值优先于同名环境变量。"""
    monkeypatch.setenv("TG_USER_ID", "env值")
    monkeypatch.setenv("NOTIFY_CONFIG_JSON", '{"TG_USER_ID": "42"}')
    try:
        importlib.reload(notify)
        assert notify.push_config["TG_USER_ID"] == "42"
    finally:
        monkeypatch.delenv("NOTIFY_CONFIG_JSON", raising=False)
        monkeypatch.delenv("TG_USER_ID", raising=False)
        importlib.reload(notify)


def test_notify_config_json_ignores_unregistered_keys(monkeypatch):
    """未在 push_config 中登记的键会被忽略，不会静默丢失已登记渠道。"""
    monkeypatch.setenv(
        "NOTIFY_CONFIG_JSON",
        '{"TG_USER_ID": "42", "NOT_A_REAL_CHANNEL": "x"}',
    )
    try:
        importlib.reload(notify)
        assert notify.push_config["TG_USER_ID"] == "42"
        assert "NOT_A_REAL_CHANNEL" not in notify.push_config
    finally:
        monkeypatch.delenv("NOTIFY_CONFIG_JSON", raising=False)
        importlib.reload(notify)


def _registered_channel_names():
    """从 add_notify_function 源码中提取登记的渠道函数名。"""
    source = inspect.getsource(notify.add_notify_function)
    return set(re.findall(r"notify_function\.append\((\w+)\)", source))


def test_every_registered_channel_exists_in_module():
    """add_notify_function 引用的每个渠道函数都必须在模块中定义。"""
    for name in _registered_channel_names():
        assert callable(getattr(notify, name, None)), name


def _channel_functions():
    """模块内所有 (title, content) 签名的公开函数——即通知渠道实现。"""
    names = []
    for name, func in vars(notify).items():
        if name.startswith("_") or not inspect.isfunction(func):
            continue
        if func.__module__ != notify.__name__:
            continue
        params = list(inspect.signature(func).parameters.values())
        if [p.name for p in params] == ["title", "content"]:
            names.append(name)
    return set(names)


def test_every_channel_function_is_registered():
    """新增渠道只写函数、不在 add_notify_function 登记时必须被发现。"""
    registered = _registered_channel_names()
    assert _channel_functions() == registered


def test_all_channels_are_registered_when_fully_configured(monkeypatch):
    """所有渠道键都配置时，每个渠道函数都必须被登记（防止只改一处）。"""
    for key in notify.push_config:
        monkeypatch.setitem(notify.push_config, key, "true")

    registered = _registered_channel_names()
    selected = {func.__name__ for func in notify.add_notify_function()}

    assert selected == registered
    assert len(notify.add_notify_function()) == len(registered)
