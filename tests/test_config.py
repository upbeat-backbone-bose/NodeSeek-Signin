import importlib

import config


def test_env_string_trims_and_falls_back(monkeypatch):
    monkeypatch.setenv("NS_TEST_STR", "  value  ")
    assert config.get_env_str("NS_TEST_STR", "fallback") == "value"
    monkeypatch.setenv("NS_TEST_STR", "   ")
    assert config.get_env_str("NS_TEST_STR", "fallback") == "fallback"
    monkeypatch.delenv("NS_TEST_STR", raising=False)
    assert config.get_env_str("NS_TEST_STR", "fallback") == "fallback"


def test_env_int_handles_invalid(monkeypatch):
    monkeypatch.setenv("NS_TEST_INT", "42")
    assert config.get_env_int("NS_TEST_INT", 7) == 42
    monkeypatch.setenv("NS_TEST_INT", "not-a-number")
    assert config.get_env_int("NS_TEST_INT", 7) == 7


def test_env_bool_accepts_common_values(monkeypatch):
    for value in ("true", "1", "yes", "on", "TRUE"):
        monkeypatch.setenv("NS_TEST_BOOL", value)
        assert config.get_env_bool("NS_TEST_BOOL", False) is True
    for value in ("false", "0", "no", "off"):
        monkeypatch.setenv("NS_TEST_BOOL", value)
        assert config.get_env_bool("NS_TEST_BOOL", True) is False
    # 无法识别的值与空串都回退到调用方给的默认值，而不是静默变成 False。
    for value in ("", "maybe"):
        monkeypatch.setenv("NS_TEST_BOOL", value)
        assert config.get_env_bool("NS_TEST_BOOL", True) is True
        assert config.get_env_bool("NS_TEST_BOOL", False) is False


def test_module_constants_are_loaded(monkeypatch):
    monkeypatch.setenv("TIMEOUT", "23")
    monkeypatch.setenv("DEBUG", "true")
    reloaded = importlib.reload(config)
    assert reloaded.REQUEST_TIMEOUT == 23
    assert reloaded.DEBUG_MODE is True
    # Restore for other tests.
    monkeypatch.delenv("TIMEOUT", raising=False)
    monkeypatch.delenv("DEBUG", raising=False)
    importlib.reload(config)
