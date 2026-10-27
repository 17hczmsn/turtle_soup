"""海龟汤 Tool 组件。

互动组件全部注册为 Tool 而非 Action：这些调用的目的是把结构化事实
返回给聊天核心去组织回复，属于"查询"而非"副作用"。default_chatter
在 ``enable_action_suspend = true`` 时会在纯 Action 回合挂起会话、不再
生成后续回复；Tool 回合始终会把结果交回模型继续跟进，因此海龟汤在
该配置开关的两种状态下都能正常回复玩家。
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseTool

from ..config import TurtleSoupConfig
from ..service import TurtleSoupService


_SERVICE_SIGNATURE = "turtle_soup:service:turtle_soup"


def _get_service() -> TurtleSoupService | None:
    """获取海龟汤服务。"""

    service = get_service(_SERVICE_SIGNATURE)
    if service is None:
        return None
    return cast(TurtleSoupService, service)


def _get_plugin_config(plugin: Any) -> TurtleSoupConfig:
    """读取插件配置，未加载时退回默认值。"""

    config = getattr(plugin, "config", None)
    if isinstance(config, TurtleSoupConfig):
        return config
    return TurtleSoupConfig()


def _reply_instruction(task: str, facts: object, constraints: str) -> str:
    """构造交给 default_chatter 的回复指令。"""

    return (
        "请根据你的当前角色人设和聊天上下文，调用 action-send_text 回复玩家。\n"
        f"任务：{task}\n"
        f"结构化事实：{facts}\n"
        f"硬性约束：{constraints}"
    )


class StartTurtleSoupGameTool(BaseTool):
    """开始海龟汤游戏。"""

    name: str = "start_turtle_soup_game"
    description: str = "当用户想玩、开一局、来一局海龟汤或换一个海龟汤时触发。返回新汤面事实；后续由你按角色人设组织回复，但必须完整保留汤面。"

    async def execute(self) -> tuple[bool, str | dict[str, object]]:
        """执行开局。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        stream_key = self.get_current_stream_id()
        await service.start_game(stream_key, message=self.trigger_message)
        facts = service.create_opening_facts(stream_key)
        return True, _reply_instruction(
            "开始一局海龟汤",
            facts,
            "必须完整包含 surface 原文，不能改写汤面；不能提到汤底；可以按你的角色语气邀请玩家提问。",
        )


class AskTurtleSoupQuestionTool(BaseTool):
    """回答海龟汤提问。"""

    name: str = "ask_turtle_soup_question"
    description: str = (
        "当海龟汤游戏进行中，玩家询问是/否类问题或调查细节时触发，用于把问答记录进游戏历史。"
        "如果系统提醒里提供了汤底，请先依据汤底自行判定每个问题（从严判定，标准词只能是“是/否/不重要/部分正确”），"
        "把 questions 与你的判定 answers 一一对应传入，并放在本轮调用的最前面，随后在同一轮直接调用 action-send_text 回复玩家，无需等待工具返回；"
        "本轮不要调用 action-pass_and_wait，等待留到下一轮记录回执之后再调用。"
        "没有汤底提醒时只传 questions，等工具返回判定结果后再回复。"
        "群聊里多名玩家同时提问时，把所有未回答的问题放进同一次调用，一次问完，避免漏答。"
    )

    async def execute(
        self,
        questions: Annotated[list[str], "玩家的问题列表；每项一个独立的是/否类问题"],
        answers: Annotated[list[str], "与 questions 一一对应的判定结果列表，每项只能是“是”“否”“不重要”“部分正确”之一"] = [],
    ) -> tuple[bool, str | dict[str, object]]:
        """执行提问回答记录。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        supplied = any(str(answer or "").strip() for answer in (answers or []))
        try:
            ok, results = await service.ask_questions(
                self.get_current_stream_id(),
                questions,
                answers=list(answers or []),
            )
        except RuntimeError as exc:
            return False, str(exc)
        if not supplied:
            # 小模型判定模式：模型需要拿到判定结果才能组织中转回复
            return ok, _reply_instruction(
                "逐一回答玩家的海龟汤提问",
                {"qa_list": results},
                "必须逐条回答每个 question，以对应 answer 的标准词为核心；不能自行推理、解释、扩写新事实或透露汤底。",
            )
        # actor 模式：判定来自模型自身，回执只用于确认记录与兜底引导
        return ok, (
            "问答已记录（qa_list 中 answer 为规范化后的标准词）。"
            "若本轮尚未向玩家回复：立即调用 action-send_text 按 qa_list 逐条回复，措辞可按角色润色，标准词不能变；"
            "若已回复完毕：直接调用 action-pass_and_wait 进入等待，不要把同样的话再说一遍。"
        )


class RequestTurtleSoupHintTool(BaseTool):
    """请求海龟汤提示。"""

    name: str = "request_turtle_soup_hint"
    description: str = (
        "当海龟汤游戏进行中，用户表示想要提示、线索、方向时触发，用于把提示记录进游戏历史。"
        "如果系统提醒里提供了汤底，请依据汤底和玩家已知信息自行生成一条不泄底的短线索（不超过35字），"
        "把该线索传入 hint 参数并放在本轮调用的最前面，随后在同一轮直接调用 action-send_text 围绕该线索回复，无需等待工具返回；"
        "本轮不要调用 action-pass_and_wait，等待留到下一轮记录回执之后再调用。"
        "没有汤底提醒时直接调用本工具，等返回的提示事实再组织回复。"
    )

    async def execute(
        self,
        hint: Annotated[str, "你依据汤底和玩家已知信息生成的提示线索，一句话，不超过35字，不泄露汤底关键内容"] = "",
    ) -> tuple[bool, str | dict[str, object]]:
        """执行提示请求。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        stream_key = self.get_current_stream_id()
        supplied = bool(str(hint or "").strip())
        try:
            ok, response = await service.request_hint(stream_key, hint_text=str(hint or ""))
        except RuntimeError as exc:
            return False, str(exc)
        if not ok:
            return False, response
        max_hints = _get_plugin_config(self.plugin).game.max_hints
        hints_used = int(service.get_state(stream_key).get("hints_used", 0))
        if not supplied:
            # 小模型判定模式：回执里的提示与剩余次数是模型组织回复的依据
            facts = {
                "hint": response,
                "hints_used": hints_used,
                "max_hints": max_hints,
            }
            return True, _reply_instruction(
                "给玩家一个海龟汤提示",
                facts,
                "只能围绕 hint 表达，不能添加新线索，不能透露汤底；可以顺带告知剩余提示次数（max_hints 减 hints_used）；语气可符合你的角色。",
            )
        # actor 模式：提示来自模型自身，回执确认记录并给出规范化结果与剩余次数
        remaining = max(0, max_hints - hints_used)
        return True, (
            f"提示已记录（规范化后：{response}；本局还剩 {remaining} 次提示）。"
            "若本轮尚未回复：立即调用 action-send_text 围绕该提示组织回复，可顺带告知剩余次数，不得透露汤底；"
            "若已回复完毕：直接调用 action-pass_and_wait 进入等待，不要重复回复。"
        )


class SummarizeTurtleSoupCluesTool(BaseTool):
    """整理海龟汤线索。"""

    name: str = "summarize_turtle_soup_clues"
    description: str = "当海龟汤游戏进行中，用户要求复盘、整理当前线索、总结已知信息时触发。返回公开历史事实；后续由你按角色人设整理，但不能新增未确认内容。"

    async def execute(self) -> tuple[bool, str | dict[str, object]]:
        """执行线索整理。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, facts = service.summarize_clues(self.get_current_stream_id())
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "整理当前海龟汤公开线索",
            facts,
            "只能使用 history 中已经公开的问答和提示；不能根据汤底补充事实；不要使用 Markdown 星号或报告格式。",
        )


class GuessTurtleSoupAnswerTool(BaseTool):
    """猜测海龟汤汤底。"""

    name: str = "guess_turtle_soup_answer"
    description: str = (
        "当海龟汤游戏进行中，用户明确给出对真相、答案、汤底的猜测时触发，用于把猜测与判定记录进游戏历史。"
        "如果系统提醒里提供了汤底，请自行判断猜测是否基本命中（只有覆盖汤底核心因果与关键事实才算命中，只沾边不算），"
        "把结论传入 is_correct 参数并放在本轮调用的最前面，随后在同一轮直接调用 action-send_text 给出反馈，无需等待工具返回；"
        "本轮不要调用 action-pass_and_wait，等待留到下一轮记录回执之后再调用。"
        "没有汤底提醒时直接调用本工具，等返回的判定事实再组织回复。"
        "多名玩家各自给出猜测时，可分别调用本工具逐个判断。"
    )

    async def execute(
        self,
        guess: Annotated[str, "玩家对汤底真相的猜测"],
        is_correct: Annotated[bool | None, "你依据汤底判断该猜测是否基本命中；无法自行判断时留空"] = None,
    ) -> tuple[bool, str | dict[str, object]]:
        """执行猜测判断。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        supplied = is_correct is not None
        try:
            ok, facts, _ = await service.guess_answer(self.get_current_stream_id(), guess, model_verdict=is_correct)
        except RuntimeError as exc:
            return False, str(exc)
        if not supplied:
            # 小模型判定模式：模型需要拿到判定结果才能组织中转回复
            return ok, _reply_instruction(
                "反馈玩家的汤底猜测",
                facts,
                "如果 is_correct 为 true，必须公布 answer 原文；如果为 false，绝不能透露 answer 或编造新事实。",
            )
        # actor 模式：判定来自模型自身，回执只用于确认记录与兜底引导
        if facts.get("is_correct"):
            receipt = (
                "判定已记录：玩家猜中，本局已结束。若本轮尚未回复：立即调用 action-send_text 完整公布 answer 原文并收束本局，"
                "不能改写汤底；若已回复完毕：调用 action-pass_and_wait 进入等待即可。"
            )
        else:
            receipt = (
                "判定已记录：未猜中。若本轮尚未回复：立即调用 action-send_text 按你的角色给出简短反馈，不得透露汤底或编造新事实；"
                "若已回复完毕：直接调用 action-pass_and_wait 进入等待，不要重复回复。"
            )
        return ok, receipt


class RevealTurtleSoupAnswerTool(BaseTool):
    """揭秘海龟汤汤底。"""

    name: str = "reveal_turtle_soup_answer"
    description: str = "当海龟汤游戏进行中，用户要求公布答案、揭秘、看汤底、结束并揭晓时触发。返回汤面和汤底事实；后续由你按角色人设揭晓。"

    async def execute(self) -> tuple[bool, str | dict[str, object]]:
        """执行揭秘。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        try:
            ok, facts = service.reveal_answer(self.get_current_stream_id())
        except RuntimeError as exc:
            return False, str(exc)
        return ok, _reply_instruction(
            "揭秘当前海龟汤汤底",
            facts,
            "必须完整包含 answer 原文，不能改写汤底；可以按你的角色语气收束本局。",
        )


class ExitTurtleSoupGameTool(BaseTool):
    """退出海龟汤游戏。"""

    name: str = "exit_turtle_soup_game"
    description: str = "当用户表示退出、结束当前海龟汤但不要求公布答案时触发。返回退出事实；后续由你按角色人设确认结束。"

    async def execute(self) -> tuple[bool, str | dict[str, object]]:
        """执行退出。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        ok, facts = service.exit_game(self.get_current_stream_id())
        return ok, _reply_instruction(
            "确认退出当前海龟汤",
            facts,
            "不能揭秘，不能透露或暗示汤底；只确认本局已结束。",
        )


class GetTurtleSoupStateTool(BaseTool):
    """获取海龟汤公开状态。"""

    name: str = "get_turtle_soup_state"
    description: str = "只读查询当前会话海龟汤游戏状态，不包含汤底。"

    async def execute(self, stream_key: str) -> tuple[bool, str | dict[str, object]]:
        """执行状态查询。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        return True, service.get_state(stream_key)


class GetTurtleSoupQuestionTool(BaseTool):
    """获取当前海龟汤汤面。"""

    name: str = "get_turtle_soup_question"
    description: str = "只读查询当前会话海龟汤汤面，不包含汤底。"

    async def execute(self, stream_key: str) -> tuple[bool, str | dict[str, object]]:
        """执行汤面查询。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        ok, question = service.get_question(stream_key)
        return ok, question
