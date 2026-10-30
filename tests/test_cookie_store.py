"""端到端测试：Cookie 解析与持久化。

覆盖审计发现的问题：
  - 末尾多余分隔符不应造出"幽灵账号"（否则退出码恒为 1）。
  - 中间的空槽位必须保留（位置即身份）。
  - 文件持久化必须保持槽位不变。
"""

import os
import stat

import pytest

from cookie_store import (
    CookieFileError,
    align_cookies,
    join_cookies,
    load_cookie_file,
    save_cookie_file,
    split_cookies,
)


class TestSplitCookies:
    def test_middle_empty_slot_is_preserved(self):
        # 第 2 个账号没有 Cookie，但第 3 个有 —— 位置不能被压缩。
        assert split_cookies("cookie1&&cookie3") == ["cookie1", "", "cookie3"]

    def test_trailing_separator_does_not_create_phantom_slot(self):
        # 末尾多余的 "&" 不携带任何 Cookie 信息，不应产生额外的账号槽位。
        assert split_cookies("c1&c2&") == ["c1", "c2"]
        assert split_cookies("c1&c2&&") == ["c1", "c2"]

    def test_trailing_newline_does_not_create_phantom_slot(self):
        assert split_cookies("c1\nc2\n") == ["c1", "c2"]
        assert split_cookies("c1\r\nc2\r\n") == ["c1", "c2"]

    def test_leading_separator_is_kept(self):
        # 开头的空槽位表示"第 1 个账号没有 Cookie"，必须保留。
        assert split_cookies("&c1") == ["", "c1"]

    def test_line_breaks_are_separators(self):
        assert split_cookies("c1\nc2\r\nc3") == ["c1", "c2", "c3"]

    def test_empty_input(self):
        assert split_cookies("") == []
        assert split_cookies("   ") == []
        assert split_cookies(None) == []

    def test_newline_is_a_separator_not_an_error(self):
        # 换行是分隔符，与 "&" 等价，不会抛异常。
        assert split_cookies("c1\nc2") == ["c1", "c2"]


class TestJoinCookies:
    def test_join_preserves_positions(self):
        assert join_cookies(["a", "", "c"]) == "a&&c"

    def test_join_of_trailing_empty_is_stable(self):
        # 序列化后再解析，结果应保持一致（不会凭空多出槽位）。
        slots = split_cookies("c1&c2&")
        assert split_cookies(join_cookies(slots)) == slots


class TestAlignCookies:
    def test_align_pads_without_compacting(self):
        assert align_cookies(["a", "", "c"], 5) == ["a", "", "c", "", ""]

    def test_align_keeps_longer_list(self):
        assert align_cookies(["a", "b", "c"], 2) == ["a", "b", "c"]


class TestFilePersistence:
    def test_round_trip_keeps_empty_slot(self, tmp_path):
        path = tmp_path / "cookie.txt"
        assert save_cookie_file(["cookie1", "", "cookie3"], str(path)) is True
        assert load_cookie_file(str(path)) == "cookie1&&cookie3"
        assert split_cookies(load_cookie_file(str(path))) == ["cookie1", "", "cookie3"]

    def test_round_trip_is_stable_across_writes(self, tmp_path):
        path = tmp_path / "cookie.txt"
        slots = ["c1", "", "c3"]
        save_cookie_file(slots, str(path))
        reloaded = split_cookies(load_cookie_file(str(path)))
        save_cookie_file(reloaded, str(path))
        assert split_cookies(load_cookie_file(str(path))) == reloaded

    @pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX modes")
    def test_saved_file_is_private(self, tmp_path):
        path = tmp_path / "cookie.txt"
        save_cookie_file(["secret"], str(path))
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_no_temp_files_left_behind(self, tmp_path):
        path = tmp_path / "cookie.txt"
        save_cookie_file(["secret"], str(path))
        assert [item.name for item in tmp_path.iterdir()] == ["cookie.txt"]

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_cookie_file(str(tmp_path / "missing.txt")) == ""

    def test_unreadable_file_raises_cookie_file_error(self, tmp_path, monkeypatch):
        """文件存在但读取失败（如 bind mount 权限不足）必须抛可捕获的异常。"""
        path = tmp_path / "cookie.txt"
        path.write_text("c1", encoding="utf-8")

        def boom(*args, **kwargs):
            raise PermissionError("permission denied")

        monkeypatch.setattr("builtins.open", boom)
        with pytest.raises(CookieFileError):
            load_cookie_file(str(path))

    def test_save_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "cookie.txt"
        assert save_cookie_file(["c1"], str(path)) is True
        assert path.exists()
        assert os.path.exists(str(path))
