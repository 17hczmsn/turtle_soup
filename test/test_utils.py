"""多问题输入规范化与通用工具函数测试。"""

from __future__ import annotations

from ..models import TurtleSoupHistoryItem, TurtleSoupState
from ..utils import (
    coerce_verdict,
    format_known_info,
    normalize_answer,
    normalize_hint,
    split_questions,
)


class TestSplitQuestions:
    def test_single_string(self) -> None:
        assert split_questions("他是自杀吗？") == ["他是自杀吗"]

    def test_multiline_string(self) -> None:
        assert split_questions("A是吗？\nB是吗？") == ["A是吗", "B是吗"]

    def test_semicolon_separated(self) -> None:
        assert split_questions("A是吗；B是吗;C是吗") == ["A是吗", "B是吗", "C是吗"]

    def test_list_input(self) -> None:
        assert split_questions(["A是吗", "B是吗\nC是吗"]) == ["A是吗", "B是吗", "C是吗"]

    def test_dedupe_and_drop_empty(self) -> None:
        assert split_questions(["A是吗", "a是吗？", "", "   ", "A是吗"]) == ["A是吗"]

    def test_caps_question_count(self) -> None:
        questions = [f"问题{i}是吗" for i in range(8)]
        assert split_questions(questions) == questions[:5]


class TestNormalizeAnswer:
    def test_exact_and_padded(self) -> None:
        assert normalize_answer("是") == "是"
        assert normalize_answer("是的。") == "是"
        assert normalize_answer("不重要") == "不重要"

    def test_negation_before_positive(self) -> None:
        assert normalize_answer("不是") == "否"
        assert normalize_answer("不是的") == "否"
        assert normalize_answer("不对，没有这回事。") == "否"

    def test_default(self) -> None:
        assert normalize_answer("汤底里没有提到") == "不重要"
        assert normalize_answer("") == "不重要"


class TestNormalizeHint:
    def test_empty_returns_fallback(self) -> None:
        assert normalize_hint("", "汤底") == "请关注汤面里最反常的变化。"
        assert normalize_hint("   \n  ", "汤底") == "请关注汤面里最反常的变化。"

    def test_first_line_and_prefix_strip(self) -> None:
        assert normalize_hint("\n提示：注意闹钟\n第二行", "汤底") == "注意闹钟"

    def test_leak_replaced(self) -> None:
        # 提示完整包含汤底原文时视为泄底，替换为兜底
        assert normalize_hint("注意：他靠闹钟确认机器还在运转", "他靠闹钟确认机器还在运转") == (
            "请关注汤面里最反常的变化。"
        )

    def test_truncated_to_35(self) -> None:
        assert len(normalize_hint("长" * 50, "汤底")) == 35


class TestCoerceVerdict:
    def test_bool_passthrough(self) -> None:
        assert coerce_verdict(True) is True
        assert coerce_verdict(False) is False

    def test_common_strings(self) -> None:
        assert coerce_verdict("true") is True
        assert coerce_verdict("猜中") is True
        assert coerce_verdict("False") is False
        assert coerce_verdict("未命中") is False

    def test_unparseable_returns_none(self) -> None:
        assert coerce_verdict("maybe") is None
        assert coerce_verdict(None) is None
        assert coerce_verdict("") is None


class TestFormatKnownInfo:
    def test_sections_and_items(self) -> None:
        state = TurtleSoupState(stream_key="s", current_question="q", current_answer="a")
        state.history = [
            TurtleSoupHistoryItem("question", "和机器有关吗", "是"),
            TurtleSoupHistoryItem("question", "他是聋子吗", "否"),
            TurtleSoupHistoryItem("hint", "请求提示", "注意闹钟"),
            TurtleSoupHistoryItem("guess", "是炸弹", "未猜中"),
        ]

        text = format_known_info(state)

        assert "已确认的事实" in text
        assert "和机器有关吗（是）" in text
        assert "已排除的方向" in text
        assert "他是聋子吗" in text
        assert '玩家猜测过“是炸弹”（未猜中）' in text
        assert "已给过的提示" in text
        assert "注意闹钟" in text

    def test_empty_history_shows_placeholder(self) -> None:
        state = TurtleSoupState(stream_key="s")
        assert "- 暂无" in format_known_info(state)
