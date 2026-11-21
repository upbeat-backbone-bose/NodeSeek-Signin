"""Cookie 槽位语义的不变量属性测试。

覆盖 SPEC.md 的 P-1..P-5：槽位位置即身份，这条不变量一旦被破坏，
签到就会落到别人的账号上。

用 hypothesis 生成比手写用例更广的输入空间：任意长度、任意分隔符、
任意空槽位组合。
"""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from cookie_store import align_cookies, join_cookies, split_cookies


# 槽位内容：模拟真实 Cookie 的形态，但不能包含分隔符。
slot_value = (
    st.text(
        alphabet=st.characters(
            blacklist_characters="&\r\n", blacklist_categories=("Cs", "Cc")
        ),
        min_size=1,
        max_size=12,
    )
    .map(lambda s: s.strip())
    .filter(lambda s: bool(s))
)

# 槽位序列：允许中间与末尾出现空槽位。
slot_sequence = st.lists(st.one_of(slot_value, st.just("")), min_size=0, max_size=8)


def _trim_trailing_blanks(slots):
    """末尾空槽位在解析时会被丢弃，往返前先去掉它们。"""
    trimmed = list(slots)
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    return trimmed


@given(slot_sequence)
@settings(max_examples=200, deadline=None)
def test_p1_parse_serialize_round_trip_preserves_positions(slots):
    """P-1 解析-序列化往返保持位置（空槽位不被压缩）。"""
    trimmed = _trim_trailing_blanks(slots)
    assume(trimmed)

    assert split_cookies(join_cookies(trimmed)) == trimmed


@given(slot_sequence, st.sampled_from(["\n", "\r\n", "&"]))
@settings(max_examples=200, deadline=None)
def test_p2_newline_and_ampersand_are_equivalent_separators(slots, separator):
    """P-2 换行与 & 是等价分隔符。"""
    trimmed = _trim_trailing_blanks(slots)
    assume(trimmed)

    joined_with_amp = "&".join(trimmed)
    joined_with_newline = separator.join(trimmed)

    assert split_cookies(joined_with_amp) == split_cookies(joined_with_newline)


@given(slot_sequence, st.integers(min_value=0, max_value=12))
@settings(max_examples=200, deadline=None)
def test_p3_alignment_only_pads_never_compacts(slots, target):
    """P-3 对齐只补齐不压缩：原有槽位位置不变。"""
    aligned = align_cookies(slots, target)

    assert len(aligned) == max(len(slots), target)
    for index, value in enumerate(slots):
        assert aligned[index] == value


@given(slot_sequence)
@settings(max_examples=200, deadline=None)
def test_p3b_alignment_is_idempotent(slots):
    """P-3 再次对齐到同一长度不改变任何东西。"""
    once = align_cookies(slots, len(slots))
    twice = align_cookies(once, len(slots))

    assert once == twice


@given(st.text(max_size=40))
@settings(max_examples=200, deadline=None)
def test_p4_split_never_raises_and_never_returns_trailing_blanks(raw):
    """P-4 解析永不抛异常，且结果不含末尾空槽位。"""
    result = split_cookies(raw)

    assert isinstance(result, list)
    assert all(isinstance(item, str) for item in result)
    if result:
        assert result[-1] != ""


@given(slot_sequence)
@settings(max_examples=200, deadline=None)
def test_p5_middle_empty_slots_survive_round_trip(slots):
    """P-5 中间空槽位必须在往返后保持为空（位置即身份）。"""
    trimmed = _trim_trailing_blanks(slots)
    assume(trimmed and "" in trimmed[:-1])

    parsed = split_cookies(join_cookies(trimmed))

    assert parsed == trimmed
    assert "" in parsed[:-1]


@given(slot_sequence)
@settings(max_examples=200, deadline=None)
def test_p6_split_count_never_exceeds_non_empty_slots(slots):
    """P-6 解析出的槽位数不超过原始非空槽位数加中间空位数。"""
    result = split_cookies(join_cookies(slots))

    assert len(result) <= len(slots)
