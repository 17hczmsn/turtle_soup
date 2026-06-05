"""海龟汤 Action 组件。"""

from __future__ import annotations

from typing import Annotated, cast

from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseAction

from ..service import TurtleSoupService
from ..utils import get_stream_key


_SERVICE_SIGNATURE = "turtle_soup:service:turtle_soup"


def _get_service() -> TurtleSoupService | None:
    """获取海龟汤服务。"""

    service = get_service(_SERVICE_SIGNATURE)
    if service is None:
        return None
    return cast(TurtleSoupService, service)


def _reply_instruction(task: str, facts: object, constraints: str) -> str:
    """构造交给 default_chatter 的回复指令。"""

    return (
        "请根据你的当前角色人设和聊天上下文，调用 action-send_text 回复玩家。\n"
        f"任务：{task}\n"
        f"结构化事实：{facts}\n"
        f"硬性约束：{constraints}"
    )


class StartTurtleSoupGameAction(BaseAction):
    """开始海龟汤游戏。"""

    action_name: str = "start_turtle_soup_game"
    action_description: str = "当用户想玩、开一局、来一局海龟汤或换一个海龟汤时触发。返回新汤面事实；后续由你按角色人设组织回复，但必须完整保留汤面。"
    primary_action: bool = True

    async def execute(self) -> tuple[bool, str]:
        """执行开局。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        stream_key = get_stream_key(self.chat_stream)
        await service.start_game(stream_key)
        facts = service.create_opening_facts(stream_key)
        return True, _reply_instruction(
            "开始一局海龟汤",
            facts,
            "必须完整包含 surface 原文，不能改写汤面；不能提到汤底；可以按你的角色语气邀请玩家提问。",
        )


class AskTurtleSoupQuestionAction(BaseAction):
    """回答海龟汤提问。"""

    action_name: str = "ask_turtle_soup_question"
    action_description: str = "当海龟汤游戏进行中，用户询问是/否类问题或调查细节时触发。返回标准事实答案；后续可以按角色语气发送，但不能改变答案词。"
    primary_action: bool = True

    async def execute(self, question: Annotated[str, "玩家对当前海龟汤提出的问题"]) -> tuple[bool, str]:
        """执行提问回答。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, response = await service.ask_question(get_stream_key(self.chat_stream), question)
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "回答玩家的海龟汤提问",
            {"question": question, "answer": response},
            "最终回复必须以 answer 的标准词为核心，不能自行推理、解释、扩写新事实或透露汤底。",
        )


class RequestTurtleSoupHintAction(BaseAction):
    """请求海龟汤提示。"""

    action_name: str = "request_turtle_soup_hint"
    action_description: str = "当海龟汤游戏进行中，用户表示想要提示、线索、方向时触发。返回提示事实；后续由你按角色人设组织回复，但不能扩展提示事实。"
    primary_action: bool = True

    async def execute(self) -> tuple[bool, str]:
        """执行提示请求。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, response = await service.request_hint(get_stream_key(self.chat_stream))
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "给玩家一个海龟汤提示",
            {"hint": response},
            "只能围绕 hint 表达，不能添加新线索，不能透露汤底；语气可符合你的角色。",
        )


class SummarizeTurtleSoupCluesAction(BaseAction):
    """整理海龟汤线索。"""

    action_name: str = "summarize_turtle_soup_clues"
    action_description: str = "当海龟汤游戏进行中，用户要求复盘、整理当前线索、总结已知信息时触发。返回公开历史事实；后续由你按角色人设整理，但不能新增未确认内容。"
    primary_action: bool = True

    async def execute(self) -> tuple[bool, str]:
        """执行线索整理。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, facts = service.summarize_clues(get_stream_key(self.chat_stream))
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "整理当前海龟汤公开线索",
            facts,
            "只能使用 history 中已经公开的问答和提示；不能根据汤底补充事实；不要使用 Markdown 星号或报告格式。",
        )


class GuessTurtleSoupAnswerAction(BaseAction):
    """猜测海龟汤汤底。"""

    action_name: str = "guess_turtle_soup_answer"
    action_description: str = "当海龟汤游戏进行中，用户明确给出对真相、答案、汤底的猜测时触发。返回猜测判断事实；后续由你按角色人设组织回复。"
    primary_action: bool = True

    async def execute(self, guess: Annotated[str, "玩家对汤底真相的猜测"]) -> tuple[bool, str]:
        """执行猜测判断。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, facts, _ = await service.guess_answer(get_stream_key(self.chat_stream), guess)
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "反馈玩家的汤底猜测",
            facts,
            "如果 is_correct 为 true，必须公布 answer 原文；如果为 false，绝不能透露 answer 或编造新事实。",
        )


class RevealTurtleSoupAnswerAction(BaseAction):
    """揭秘海龟汤汤底。"""

    action_name: str = "reveal_turtle_soup_answer"
    action_description: str = "当海龟汤游戏进行中，用户要求公布答案、揭秘、看汤底、结束并揭晓时触发。返回汤面和汤底事实；后续由你按角色人设揭晓。"
    primary_action: bool = True

    async def execute(self) -> tuple[bool, str]:
        """执行揭秘。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, facts = service.reveal_answer(get_stream_key(self.chat_stream))
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "揭秘当前海龟汤汤底",
            facts,
            "必须完整包含 answer 原文，不能改写汤底；可以按你的角色语气收束本局。",
        )


class ExitTurtleSoupGameAction(BaseAction):
    """退出海龟汤游戏。"""

    action_name: str = "exit_turtle_soup_game"
    action_description: str = "当用户表示退出、结束当前海龟汤但不要求公布答案时触发。返回退出事实；后续由你按角色人设确认结束。"
    primary_action: bool = True

    async def execute(self) -> tuple[bool, str]:
        """执行退出。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        ok, facts = service.exit_game(get_stream_key(self.chat_stream))
        return ok, _reply_instruction(
            "确认退出当前海龟汤",
            facts,
            "不能揭秘，不能透露或暗示汤底；只确认本局已结束。",
        )
