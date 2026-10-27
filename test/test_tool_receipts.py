"""工具回执的模式感知测试。

actor 模式（模型自带判定/提示/结论）下，工具回执应是"记录确认"而非
旧中转流程的"组织回复指令"；fallback 模式（模型未传结果，由小模型
判定）下才返回中转指令。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from .. import tools as tools_module
from ..config import TurtleSoupConfig
from ..tools import (
    AskTurtleSoupQuestionTool,
    GuessTurtleSoupAnswerTool,
    RequestTurtleSoupHintTool,
)


class StubService:
    """记录调用并返回固定结果的服务假件。"""

    def __init__(self) -> None:
        self.ask_calls: list[tuple] = []
        self.hint_calls: list[tuple] = []
        self.guess_calls: list[tuple] = []
        self.state = {"hints_used": 1}

    async def ask_questions(self, stream_key, questions, answers=None):
        self.ask_calls.append((stream_key, questions, answers))
        return True, [{"question": q, "answer": "是"} for q in questions]

    async def request_hint(self, stream_key, hint_text=""):
        self.hint_calls.append((stream_key, hint_text))
        return True, hint_text or "小模型提示"

    async def guess_answer(self, stream_key, guess, model_verdict=None):
        self.guess_calls.append((stream_key, guess, model_verdict))
        correct = bool(model_verdict)
        return True, {"guess": guess, "is_correct": correct, "answer": "汤底" if correct else ""}, correct

    def get_state(self, stream_key):
        return dict(self.state)


@pytest.fixture()
def stub_service(monkeypatch):
    service = StubService()
    monkeypatch.setattr(tools_module, "_get_service", lambda: service)
    return service


def _make_tool(cls):
    tool = cls.__new__(cls)
    tool.stream_id = "s1"
    tool.trigger_message = None
    tool.plugin = SimpleNamespace(config=TurtleSoupConfig())
    return tool


def _run(coro):
    return asyncio.run(coro)


class TestAskReceipt:
    def test_actor_mode_returns_record_receipt(self, stub_service) -> None:
        tool = _make_tool(AskTurtleSoupQuestionTool)
        ok, receipt = _run(tool.execute(["A是吗"], answers=["是"]))

        assert ok is True
        assert "问答已记录" in receipt
        assert "不要把同样的话再说一遍" in receipt
        assert "结构化事实" not in receipt  # 不再使用旧中转指令

    def test_fallback_mode_returns_relay_instruction(self, stub_service) -> None:
        tool = _make_tool(AskTurtleSoupQuestionTool)
        ok, receipt = _run(tool.execute(["A是吗"]))

        assert ok is True
        assert "结构化事实" in receipt
        assert "标准词为核心" in receipt

    def test_blank_answers_treated_as_fallback(self, stub_service) -> None:
        tool = _make_tool(AskTurtleSoupQuestionTool)
        ok, receipt = _run(tool.execute(["A是吗"], answers=["", "  "]))

        assert "结构化事实" in receipt


class TestHintReceipt:
    def test_actor_mode_returns_record_receipt_with_remaining(self, stub_service) -> None:
        tool = _make_tool(RequestTurtleSoupHintTool)
        ok, receipt = _run(tool.execute("注意闹钟的声音"))

        assert ok is True
        assert "提示已记录" in receipt
        assert "规范化后：注意闹钟的声音" in receipt
        assert "还剩 2 次提示" in receipt  # max_hints=3 - hints_used=1

    def test_fallback_mode_returns_relay_instruction(self, stub_service) -> None:
        tool = _make_tool(RequestTurtleSoupHintTool)
        ok, receipt = _run(tool.execute(""))

        assert ok is True
        assert "结构化事实" in receipt
        assert "小模型提示" in receipt


class TestGuessReceipt:
    def test_actor_correct_returns_announce_receipt(self, stub_service) -> None:
        tool = _make_tool(GuessTurtleSoupAnswerTool)
        ok, receipt = _run(tool.execute("猜对了", is_correct=True))

        assert ok is True
        assert "判定已记录：玩家猜中" in receipt
        assert "公布 answer 原文" in receipt
        assert "action-pass_and_wait" in receipt  # 引导正规等待，避免纯文本输出

    def test_actor_wrong_returns_feedback_receipt(self, stub_service) -> None:
        tool = _make_tool(GuessTurtleSoupAnswerTool)
        ok, receipt = _run(tool.execute("猜错了", is_correct=False))

        assert ok is True
        assert "判定已记录：未猜中" in receipt
        assert "不得透露汤底" in receipt

    def test_fallback_mode_returns_relay_instruction(self, stub_service) -> None:
        tool = _make_tool(GuessTurtleSoupAnswerTool)
        ok, receipt = _run(tool.execute("随便猜的"))

        assert ok is True
        assert "结构化事实" in receipt
