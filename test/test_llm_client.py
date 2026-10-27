"""海龟汤 LLM 客户端纯函数与提示词测试（不触网）。"""

from __future__ import annotations

from ..llm_client import TurtleSoupLLMClient
from ..models import TurtleSoupHistoryItem, TurtleSoupState


def _make_state(
    history: list[TurtleSoupHistoryItem] | None = None,
    hints_used: int = 0,
) -> TurtleSoupState:
    state = TurtleSoupState(
        stream_key="test",
        current_question="他每天都被闹钟叫醒。",
        current_answer="他靠闹钟确认机器还在运转。",
        game_active=True,
    )
    state.history = list(history or [])
    state.hints_used = hints_used
    return state


class TestNormalizeHint:
    def test_empty_response_returns_fallback(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        assert client._normalize_hint("", _make_state()) == "请关注汤面里最反常的变化。"

    def test_whitespace_response_returns_fallback(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        assert client._normalize_hint("   \n  \n", _make_state()) == "请关注汤面里最反常的变化。"

    def test_takes_first_nonempty_line_and_strips_prefix(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        hint = client._normalize_hint("\n提示：注意闹钟的用途\n第二行不该出现", _make_state())
        assert hint == "注意闹钟的用途"

    def test_leaking_answer_replaced_by_fallback(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        state = _make_state()
        hint = client._normalize_hint(state.current_answer, state)
        assert hint == "请关注汤面里最反常的变化。"

    def test_truncates_to_35_chars(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        assert len(client._normalize_hint("长" * 50, _make_state())) == 35


class TestNormalizeQuestionAnswer:
    def _client(self) -> TurtleSoupLLMClient:
        return TurtleSoupLLMClient("utils_small")

    def test_exact_words(self) -> None:
        client = self._client()
        assert client._normalize_question_answer("是") == "是"
        assert client._normalize_question_answer("否") == "否"
        assert client._normalize_question_answer("不重要") == "不重要"
        assert client._normalize_question_answer("部分正确") == "部分正确"

    def test_negation_not_mistaken_as_yes(self) -> None:
        client = self._client()
        assert client._normalize_question_answer("不是") == "否"
        assert client._normalize_question_answer("不是的") == "否"
        assert client._normalize_question_answer("不对，没有这回事。") == "否"

    def test_padded_positive(self) -> None:
        client = self._client()
        assert client._normalize_question_answer("是的。") == "是"
        assert client._normalize_question_answer("“部分正确”，方向对但细节有偏差") == "部分正确"
        assert client._normalize_question_answer("这个问题不重要。") == "不重要"

    def test_unmatched_defaults_to_unimportant(self) -> None:
        client = self._client()
        assert client._normalize_question_answer("汤底里没有提到这一点") == "不重要"
        assert client._normalize_question_answer("") == "不重要"


class TestAnswerQuestionPrompt:
    async def test_prompt_contains_strict_criteria(self, monkeypatch) -> None:
        client = TurtleSoupLLMClient("utils_small")
        captured: dict[str, str] = {}

        async def fake_send(prompt: str, request_name: str) -> str:
            captured["prompt"] = prompt
            return "否"

        monkeypatch.setattr(client, "_send", fake_send)
        state = _make_state()

        answer = await client.answer_question(state, "闹钟是炸弹吗？")

        assert answer == "否"
        prompt = captured["prompt"]
        assert "玩家问题：闹钟是炸弹吗？" in prompt
        assert "从严掌握" in prompt
        assert "必然推出" in prompt
        assert "不得回答“是”" in prompt


class TestSummarizeKnownInfo:
    def test_classifies_history_items(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        state = _make_state(
            history=[
                TurtleSoupHistoryItem("question", "闹钟和机器有关吗", "是"),
                TurtleSoupHistoryItem("question", "他是聋子吗", "否"),
                TurtleSoupHistoryItem("question", "闹钟是定时的吗", "部分正确"),
                TurtleSoupHistoryItem("hint", "请求提示", "注意闹钟的声音"),
                TurtleSoupHistoryItem("guess", "闹钟是炸弹", "不对，方向偏离"),
                TurtleSoupHistoryItem("clues", "整理线索", "已请求整理公开线索"),
            ]
        )

        confirmed, rejected, given_hints = client._summarize_known_info(state)

        assert confirmed == ["闹钟和机器有关吗（是）", "闹钟是定时的吗（部分正确）"]
        assert rejected == ["他是聋子吗", "玩家猜测过“闹钟是炸弹”（未猜中）"]
        assert given_hints == ["注意闹钟的声音"]

    def test_empty_history(self) -> None:
        client = TurtleSoupLLMClient("utils_small")
        assert client._summarize_known_info(_make_state()) == ([], [], [])


class TestCreateHintPrompt:
    async def test_prompt_contains_known_info_and_progress(self, monkeypatch) -> None:
        client = TurtleSoupLLMClient("utils_small")
        captured: dict[str, str] = {}

        async def fake_send(prompt: str, request_name: str) -> str:
            captured["prompt"] = prompt
            return "一条模糊线索"

        monkeypatch.setattr(client, "_send", fake_send)
        state = _make_state(
            history=[
                TurtleSoupHistoryItem("question", "闹钟和机器有关吗", "是"),
                TurtleSoupHistoryItem("question", "他是聋子吗", "否"),
                TurtleSoupHistoryItem("hint", "请求提示", "注意闹钟的声音"),
            ],
            hints_used=1,
        )

        hint = await client.create_hint(state, max_hints=3)

        assert hint == "一条模糊线索"
        prompt = captured["prompt"]
        assert "已确认的事实" in prompt
        assert "闹钟和机器有关吗（是）" in prompt
        assert "已排除的方向" in prompt
        assert "他是聋子吗" in prompt
        assert "已给过的提示" in prompt
        assert "注意闹钟的声音" in prompt
        assert "第 2 次提示" in prompt
        assert "最多 35 字" in prompt

    async def test_empty_llm_output_returns_fallback(self, monkeypatch) -> None:
        client = TurtleSoupLLMClient("utils_small")

        async def fake_send(prompt: str, request_name: str) -> str:
            return ""

        monkeypatch.setattr(client, "_send", fake_send)
        hint = await client.create_hint(_make_state(), max_hints=3)
        assert hint == "请关注汤面里最反常的变化。"
