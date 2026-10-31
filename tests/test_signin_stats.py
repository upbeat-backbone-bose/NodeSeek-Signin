"""签到收益统计的端到端测试。

不访问网络：替换 _request_with_impersonate_fallback 返回构造好的分页数据，
验证：
  - 正常覆盖 30 天窗口时，period 不带"数据不完整"。
  - 页数上限用尽仍未触及窗口下界时，必须标记为"数据不完整"。
  - 触及窗口下界属于完整数据，不应标记截断。
"""

import datetime

import nodeseek_sign


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.text = ""
        self._payload = payload

    def json(self):
        return self._payload


def _record(days_ago, amount=5, description="签到收益，获得 5 个鸡腿"):
    """构造一条积分流水记录。"""
    stamp = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        days=days_ago
    )
    return [amount, 100, description, stamp.isoformat().replace("+00:00", "Z")]


def _install(monkeypatch, pages):
    """pages: {页码: 记录列表}；返回实际请求的页码列表。"""
    requested = []
    # 去掉分页之间的等待，避免测试变慢。
    monkeypatch.setattr(nodeseek_sign.time, "sleep", lambda _seconds: None)

    def fake_request(method, url, *, headers, json_data=None, timeout=None):
        page = int(url.rsplit("page-", 1)[1])
        requested.append(page)
        records = pages.get(page, [])
        return (
            FakeResponse({"success": True, "data": records}),
            "chrome146",
            None,
        )

    monkeypatch.setattr(
        nodeseek_sign, "_request_with_impersonate_fallback", fake_request
    )
    return requested


class TestGetSigninStats:
    def test_complete_window_is_not_marked_truncated(self, monkeypatch):
        # 第 1 页覆盖最近 1 天，第 2 页覆盖 40 天前（越过窗口下界）。
        _install(monkeypatch, {1: [_record(0)], 2: [_record(40)]})

        stats, _msg = nodeseek_sign.get_signin_stats("session=abc", days=30)

        assert stats is not None
        assert stats["truncated"] is False
        assert "数据不完整" not in stats["period"]
        assert stats["days_count"] == 1

    def test_page_limit_truncation_is_marked(self, monkeypatch):
        # 每一页都只含最近一天的数据，永远碰不到 30 天前的下界，
        # 因此循环会因页数上限退出 —— 此时数据是不完整的。
        pages = {
            page: [_record(0)] for page in range(1, nodeseek_sign.STATS_MAX_PAGES + 1)
        }
        _install(monkeypatch, pages)

        stats, _msg = nodeseek_sign.get_signin_stats("session=abc", days=30)

        assert stats is not None
        assert stats["truncated"] is True
        assert "数据不完整" in stats["period"]
        # 已获取的部分数据仍被统计（每页 1 条，共 STATS_MAX_PAGES 条）。
        assert stats["days_count"] == nodeseek_sign.STATS_MAX_PAGES

    def test_truncated_flag_absent_when_no_records(self, monkeypatch):
        _install(monkeypatch, {1: []})

        stats, _msg = nodeseek_sign.get_signin_stats("session=abc", days=30)

        assert stats is not None
        assert stats["total_amount"] == 0
        assert "truncated" in stats

    def test_default_page_budget_covers_full_window(self, monkeypatch):
        """默认页数上限必须足以覆盖 30 天窗口（历史行为为 20 页）。"""
        assert nodeseek_sign.STATS_MAX_PAGES == 20

    def test_stats_message_mentions_incomplete_data(self, monkeypatch):
        pages = {
            page: [_record(0)] for page in range(1, nodeseek_sign.STATS_MAX_PAGES + 1)
        }
        _install(monkeypatch, pages)

        stats, _msg = nodeseek_sign.get_signin_stats("session=abc", days=30)

        message = nodeseek_sign._stats_message(stats)
        assert "数据不完整" in message
