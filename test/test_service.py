"""海龟汤服务层测试（提示额度、多问题回答、reminder 生命周期，全部使用假件）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from .. import service as service_module
from ..config import TurtleSoupConfig
from ..models import TurtleSoupPuzzle, TurtleSoupState
from ..service import TurtleSoupService
from ..state import state_store

_STREAM_KEY = "test"


class FakeLLMClient:
    """按预置结果返回的 LLM 客户端假件。"""

    def __init__(
        self,
        hint_result: str = "一条模糊线索",
        hint_error: Exception | None = None,
        answers: dict[str, str] | None = None,
        judge_result: tuple[bool, str] = (False, "WRONG\n还没有猜中"),
    ) -> None:
        self.hint_result = hint_result
        self.hint_error = hint_error
        self.answers = answers or {}
        self.judge_result = judge_result
        self.judged_questions: list[str] = []
        self.hint_calls = 0
        self.judge_calls = 0

    async def create_hint(self, state: TurtleSoupState, max_hints: int = 3) -> str:
        self.hint_calls += 1
        if self.hint_error is not None:
            raise self.hint_error
        return self.hint_result

    async def answer_question(self, state: TurtleSoupState, question: str) -> str:
        self.judged_questions.append(question)
        return self.answers.get(question, "否")

    async def judge_guess(self, state: TurtleSoupState, guess: str) -> tuple[bool, str]:
        self.judge_calls += 1
        return self.judge_result


class FakeProvider:
    """固定返回一题的题目提供器假件。"""

    async def get_puzzle(self, exclude_surfaces=None) -> TurtleSoupPuzzle:
        return TurtleSoupPuzzle(title="测试汤", surface="测试汤面", answer="测试汤底")


def _make_service(client: FakeLLMClient) -> TurtleSoupService:
    plugin = SimpleNamespace(config=TurtleSoupConfig())
    service = TurtleSoupService(plugin)
    service._create_llm_client = lambda: client  # type: ignore[method-assign]
    return service


def _seed_state(hints_used: int = 0) -> TurtleSoupState:
    state = TurtleSoupState(
        stream_key=_STREAM_KEY,
        current_question="汤面",
        current_answer="汤底",
        game_active=True,
    )
    state.hints_used = hints_used
    state_store.set(state)
    return state


@pytest.fixture(autouse=True)
def _clean_state():
    yield
    state_store.clear(_STREAM_KEY)
    from src.app.plugin_system.api import prompt_api

    try:
        prompt_api.clear_stream_reminders(_STREAM_KEY)
    except Exception:
        pass


class TestRequestHintQuota:
    async def test_llm_failure_does_not_consume_quota(self) -> None:
        service = _make_service(FakeLLMClient(hint_error=RuntimeError("网络异常")))
        state = _seed_state(hints_used=0)

        ok, message = await service.request_hint(_STREAM_KEY)

        assert ok is False
        assert "失败" in message
        assert state.hints_used == 0
        assert all(item.item_type != "hint" for item in state.history)

    async def test_success_consumes_quota(self) -> None:
        service = _make_service(FakeLLMClient(hint_result="注意闹钟"))
        state = _seed_state(hints_used=1)

        ok, hint = await service.request_hint(_STREAM_KEY)

        assert ok is True
        assert hint == "注意闹钟"
        assert state.hints_used == 2
        assert state.history[-1].item_type == "hint"

    async def test_limit_reached_returns_false(self) -> None:
        service = _make_service(FakeLLMClient())
        state = _seed_state(hints_used=3)

        ok, message = await service.request_hint(_STREAM_KEY)

        assert ok is False
        assert "已用完" in message
        assert state.hints_used == 3


class TestAskQuestions:
    async def test_multiple_questions_answered_in_one_call(self) -> None:
        service = _make_service(FakeLLMClient(answers={"A是吗": "是", "B是吗": "否"}))
        state = _seed_state()

        ok, results = await service.ask_questions(_STREAM_KEY, ["A是吗", "B是吗"])

        assert ok is True
        assert results == [
            {"question": "A是吗", "answer": "是"},
            {"question": "B是吗", "answer": "否"},
        ]
        assert [item.content for item in state.history] == ["A是吗", "B是吗"]

    async def test_merged_string_input_is_split(self) -> None:
        service = _make_service(FakeLLMClient(answers={"A是吗": "是", "B是吗": "否"}))
        _seed_state()

        ok, results = await service.ask_questions(_STREAM_KEY, "A是吗\nB是吗")

        assert ok is True
        assert [item["question"] for item in results] == ["A是吗", "B是吗"]

    async def test_ask_question_returns_single_answer(self) -> None:
        service = _make_service(FakeLLMClient(answers={"A是吗": "是"}))
        _seed_state()

        ok, answer = await service.ask_question(_STREAM_KEY, "A是吗")

        assert ok is True
        assert answer == "是"


class TestMainModelJudgement:
    async def test_provided_answers_recorded_without_small_model(self) -> None:
        client = FakeLLMClient(answers={"绝不": "是"})
        service = _make_service(client)
        state = _seed_state()

        ok, results = await service.ask_questions(
            _STREAM_KEY,
            ["A是吗？", "B是吗？", "C是吗？"],
            answers=["是的", "不是", "部分正确"],
        )

        assert ok is True
        assert results == [
            {"question": "A是吗", "answer": "是"},
            {"question": "B是吗", "answer": "否"},
            {"question": "C是吗", "answer": "部分正确"},
        ]
        # 主模型判定不应触发小模型兜底
        assert client.judged_questions == []
        assert [item.response for item in state.history] == ["是", "否", "部分正确"]

    async def test_mismatched_answers_fall_back_to_small_model(self) -> None:
        client = FakeLLMClient(answers={"A是吗": "是", "B是吗": "否"})
        service = _make_service(client)
        _seed_state()

        ok, results = await service.ask_questions(_STREAM_KEY, ["A是吗", "B是吗"], answers=["是"])

        assert ok is True
        assert results == [
            {"question": "A是吗", "answer": "是"},
            {"question": "B是吗", "answer": "否"},
        ]
        assert client.judged_questions == ["A是吗", "B是吗"]

    async def test_partial_blank_answers_use_small_model(self) -> None:
        client = FakeLLMClient(answers={"B是吗": "否"})
        service = _make_service(client)
        _seed_state()

        ok, results = await service.ask_questions(_STREAM_KEY, ["A是吗", "B是吗"], answers=["", "否"])

        assert ok is True
        assert results[0]["answer"] == "否"  # 小模型兜底默认值
        assert results[1]["answer"] == "否"
        assert client.judged_questions == ["A是吗"]


@pytest.fixture()
def reminder_calls(monkeypatch):
    """记录 service 层对 reminder 注入/移除的调用。"""

    calls = {"inject": [], "remove": []}
    monkeypatch.setattr(
        service_module,
        "inject_host_reminder",
        lambda stream_key, title, surface, answer, known_summary="", max_hints=3: calls["inject"].append(
            (stream_key, title, surface, answer, known_summary, max_hints)
        ),
    )
    monkeypatch.setattr(
        service_module,
        "remove_host_reminder",
        lambda stream_key: calls["remove"].append(stream_key),
    )
    return calls


class TestReminderLifecycle:
    def _service_with_provider(self, client: FakeLLMClient) -> TurtleSoupService:
        service = _make_service(client)
        service._create_provider = lambda message=None: FakeProvider()  # type: ignore[method-assign]
        return service

    async def test_start_game_injects_reminder(self, reminder_calls) -> None:
        service = self._service_with_provider(FakeLLMClient())

        state = await service.start_game(_STREAM_KEY)

        assert state.game_active is True
        assert len(reminder_calls["inject"]) == 1
        stream_key, title, surface, answer, known_summary, max_hints = reminder_calls["inject"][0]
        assert (stream_key, title, surface, answer) == (_STREAM_KEY, "测试汤", "测试汤面", "测试汤底")
        assert known_summary == ""  # 开局尚无已知信息
        assert max_hints == 3  # 默认提示额度
        state_store.clear(_STREAM_KEY)

    async def test_start_game_removes_stale_reminder_first(self, reminder_calls) -> None:
        """换汤/重开时必须先移除旧 reminder（可能含旧汤底），再按配置注入。"""

        service = self._service_with_provider(FakeLLMClient())
        config = TurtleSoupConfig()
        config.llm.answer_in_actor_model = False
        service.plugin = SimpleNamespace(config=config)

        await service.start_game(_STREAM_KEY)

        # actor 关闭也要先清理旧机密
        assert reminder_calls["remove"] == [_STREAM_KEY]
        assert reminder_calls["inject"] == []
        state_store.clear(_STREAM_KEY)

    async def test_start_game_skips_reminder_when_disabled(self, reminder_calls, monkeypatch) -> None:
        service = self._service_with_provider(FakeLLMClient())
        config = TurtleSoupConfig()
        config.llm.answer_in_actor_model = False
        service.plugin = SimpleNamespace(config=config)

        await service.start_game(_STREAM_KEY)

        assert reminder_calls["inject"] == []
        state_store.clear(_STREAM_KEY)

    async def test_exit_game_removes_reminder(self, reminder_calls) -> None:
        service = _make_service(FakeLLMClient())
        _seed_state()

        ok, _ = service.exit_game(_STREAM_KEY)

        assert ok is True
        assert reminder_calls["remove"] == [_STREAM_KEY]

    def test_reveal_answer_removes_reminder(self, reminder_calls) -> None:
        service = _make_service(FakeLLMClient())
        _seed_state()

        ok, _ = service.reveal_answer(_STREAM_KEY)

        assert ok is True
        assert reminder_calls["remove"] == [_STREAM_KEY]

    async def test_correct_guess_removes_reminder(self, reminder_calls) -> None:
        client = FakeLLMClient(judge_result=(True, "CORRECT\n猜中了"))
        service = _make_service(client)
        _seed_state()

        ok, _, correct = await service.guess_answer(_STREAM_KEY, "测试猜测")

        assert correct is True
        assert client.judge_calls == 1  # 未传判定，走小模型路径
        assert reminder_calls["remove"] == [_STREAM_KEY]


class TestHintInActorModel:
    async def test_model_hint_recorded_without_small_model(self) -> None:
        client = FakeLLMClient()
        service = _make_service(client)
        state = _seed_state()

        ok, hint = await service.request_hint(_STREAM_KEY, hint_text="提示：注意闹钟的声音")

        assert ok is True
        assert hint == "注意闹钟的声音"
        assert client.hint_calls == 0
        assert state.hints_used == 1
        assert state.history[-1].response == "注意闹钟的声音"

    async def test_leaky_model_hint_replaced_by_fallback(self) -> None:
        client = FakeLLMClient()
        service = _make_service(client)
        state = _seed_state()

        ok, hint = await service.request_hint(_STREAM_KEY, hint_text=state.current_answer)

        assert ok is True
        assert hint == "请关注汤面里最反常的变化。"

    async def test_empty_hint_falls_back_to_small_model(self) -> None:
        client = FakeLLMClient(hint_result="小模型线索")
        service = _make_service(client)
        _seed_state()

        ok, hint = await service.request_hint(_STREAM_KEY, hint_text="  ")

        assert ok is True
        assert hint == "小模型线索"
        assert client.hint_calls == 1


class TestGuessInActorModel:
    async def test_model_verdict_true_ends_game(self, reminder_calls) -> None:
        client = FakeLLMClient()
        service = _make_service(client)
        state = _seed_state()

        ok, facts, correct = await service.guess_answer(_STREAM_KEY, "测试汤底", model_verdict=True)

        assert correct is True
        assert facts["is_correct"] is True
        assert facts["answer"] == "汤底"
        assert client.judge_calls == 0
        assert state.game_active is False
        assert reminder_calls["remove"] == [_STREAM_KEY]

    async def test_model_verdict_false_records_miss(self, reminder_calls) -> None:
        client = FakeLLMClient()
        service = _make_service(client)
        state = _seed_state()

        ok, facts, correct = await service.guess_answer(_STREAM_KEY, "错误猜测", model_verdict=False)

        assert correct is False
        assert facts["answer"] == ""
        assert client.judge_calls == 0
        assert state.game_active is True
        assert state.history[-1].item_type == "guess"
        # 未猜中是新的已排除方向，reminder 应被刷新而非移除
        assert reminder_calls["remove"] == []
        assert len(reminder_calls["inject"]) == 1

    async def test_unparseable_verdict_falls_back_to_small_model(self) -> None:
        client = FakeLLMClient(judge_result=(False, "WRONG\n还没有猜中"))
        service = _make_service(client)
        _seed_state()

        ok, facts, correct = await service.guess_answer(_STREAM_KEY, "测试", model_verdict="maybe")

        assert correct is False
        assert client.judge_calls == 1
        assert facts["judge_feedback"] == "还没有猜中"
