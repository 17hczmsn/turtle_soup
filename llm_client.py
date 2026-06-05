"""海龟汤 LLM 互动客户端。"""

from __future__ import annotations

import re

from src.app.plugin_system.api.llm_api import create_llm_request, get_model_set_by_task
from src.kernel.llm import LLMPayload, ROLE, Text

from .models import TurtleSoupHistoryItem, TurtleSoupState


class TurtleSoupLLMClient:
    """封装海龟汤互动所需的 LLM 调用。"""

    def __init__(self, model_task: str) -> None:
        """初始化 LLM 客户端。"""

        self.model_task = model_task

    async def answer_question(self, state: TurtleSoupState, question: str) -> str:
        """根据汤底回答玩家问题。"""

        prompt = self._build_prompt(
            state,
            f"玩家问题：{question}\n只能从“是”“否”“不重要”“部分正确”四个词中选择一个输出，不要输出任何解释、标点或额外文字。",
        )
        response = await self._send(prompt, "turtle_soup_question")
        return self._normalize_question_answer(response)

    async def create_opening(self, state: TurtleSoupState) -> str:
        """生成带角色口吻的开局主持话术。"""

        prompt = (
            "你是当前聊天中的海龟汤主持人。请发起一局海龟汤。\n"
            "要求：\n"
            "1. 必须完整包含汤面，且不能改写汤面文字。\n"
            "2. 不能透露、暗示或编造汤底。\n"
            "3. 可以自然邀请玩家提问、猜测、要提示或揭秘。\n"
            "4. 不要输出推理过程、思考过程或 <think> 标签。\n"
            "5. 不要解释规则太长。\n\n"
            f"题名：{state.title}\n"
            f"汤面：{state.current_question}\n"
        )
        response = await self._send(prompt, "turtle_soup_opening")
        return self._normalize_opening(response, state)

    async def create_hint(self, state: TurtleSoupState) -> str:
        """根据汤底和已公开进度生成递进提示。"""

        prompt = self._build_prompt(
            state,
            "请根据汤底和历史交互生成一个递进提示。要求：\n"
            "1. 必须严格贴合汤底，不能猜测、不能编造其他可能性。\n"
            "2. 必须结合玩家已经问过的问题和已得到的回答，优先提示玩家还没触及的关键方向。\n"
            "3. 不要直接说出完整汤底、身份、结局或关键反转；只给一条方向性线索。\n"
            "4. 如果历史里玩家已经问到某方向且回答为否，不要再沿那个方向提示。\n"
            "5. 最多 35 字，只输出给玩家看的提示，不要输出推理过程。",
        )
        response = await self._send(prompt, "turtle_soup_hint")
        return self._normalize_hint(response, state)

    async def summarize_clues(self, state: TurtleSoupState) -> str:
        """整理当前已知线索。"""

        prompt = self._build_public_prompt(
            state,
            "请用当前聊天里真实主持人的自然口吻，简短整理玩家已经确认的公开线索。要求：\n"
            "1. 只能整理历史交互里玩家已经问过、主持已经回答过的公开信息。\n"
            "2. 不能加入汤底事实，不能推断未确认内容，不能说破谜底。\n"
            "3. 不要写成报告、公告或攻略，不要使用 Markdown，不要使用星号、加粗标题或分级标题。\n"
            "4. 像平时聊天一样说，可以分行，但不要用“确认事实”“已排除方向”这类模板标题。",
        )
        response = await self._send(prompt, "turtle_soup_clues")
        return self._normalize_public_host_response(response, state, "目前公开线索还不多，可以继续问几个关键问题。")

    async def judge_guess(self, state: TurtleSoupState, guess: str) -> tuple[bool, str]:
        """判断玩家猜测是否命中汤底。"""

        prompt = self._build_prompt(
            state,
            "玩家猜测如下：\n"
            f"{guess}\n"
            "请判断是否基本命中汤底。输出第一行必须是 CORRECT 或 WRONG，第二行给出简短反馈。",
        )
        response = await self._send(prompt, "turtle_soup_guess")
        first_line = response.splitlines()[0].strip().upper() if response else "WRONG"
        return first_line.startswith("CORRECT"), response

    async def create_guess_feedback(
        self,
        state: TurtleSoupState,
        guess: str,
        is_correct: bool,
        judge_response: str,
    ) -> str:
        """生成带角色口吻的猜测反馈。"""

        if is_correct:
            prompt = self._build_prompt(
                state,
                "玩家已经基本猜中汤底。请用自然主持人口吻宣布猜对，并公布完整汤底。"
                "必须完整包含汤底原文，不要改写汤底。不要输出推理过程。\n"
                f"玩家猜测：{guess}\n"
                f"判断参考：{judge_response}",
            )
            response = await self._send(prompt, "turtle_soup_guess_feedback")
            return self._normalize_reveal(response, state)

        prompt = self._build_prompt(
            state,
            "玩家还没有猜中汤底。请用自然主持人口吻给出简短反馈。"
            "不能透露汤底，不能新增未公开事实，可以指出猜测的大方向是否接近。不要输出推理过程。\n"
            f"玩家猜测：{guess}\n"
            f"判断参考：{judge_response}",
        )
        response = await self._send(prompt, "turtle_soup_guess_feedback")
        return self._normalize_no_answer_response(response, state, "还没猜中，可以再换个方向试试。")

    async def create_reveal(self, state: TurtleSoupState) -> str:
        """生成带角色口吻的揭秘话术。"""

        prompt = self._build_prompt(
            state,
            "玩家要求揭秘。请用自然主持人口吻结束本局并公布汤底。"
            "必须完整包含汤底原文，不要改写汤底；可以简短收束气氛。不要输出推理过程。",
        )
        response = await self._send(prompt, "turtle_soup_reveal")
        return self._normalize_reveal(response, state)

    async def create_exit(self, state: TurtleSoupState) -> str:
        """生成带角色口吻的退出话术。"""

        prompt = self._build_public_prompt(
            state,
            "玩家要退出当前海龟汤，但没有要求揭秘。请用自然主持人口吻确认本局结束。"
            "不能透露、暗示或总结汤底；不要输出推理过程。",
        )
        response = await self._send(prompt, "turtle_soup_exit")
        return self._normalize_no_answer_response(response, state, "已结束当前海龟汤。")

    async def _send(self, prompt: str, request_name: str) -> str:
        """发送 LLM 请求并返回文本。"""

        model_set = get_model_set_by_task(self.model_task)
        request = create_llm_request(model_set, request_name=request_name)
        request.add_payload(LLMPayload(ROLE.USER, Text(prompt)))
        response = await request.send(stream=False)
        return self._strip_reasoning(str(getattr(response, "message", "") or ""))

    def _strip_reasoning(self, message: str) -> str:
        """移除模型输出中的思考标签内容。"""

        cleaned = re.sub(r"<think>.*?</think>", "", message, flags=re.S | re.I).strip()
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", cleaned, flags=re.S | re.I).strip()
        return cleaned

    def _normalize_question_answer(self, response: str) -> str:
        """将问答输出限制为海龟汤标准回答。"""

        for answer in ("部分正确", "不重要", "是", "否"):
            if answer in response:
                return answer
        return "不重要"

    def _normalize_opening(self, response: str, state: TurtleSoupState) -> str:
        """确保开局话术包含原始汤面且不泄露汤底。"""

        opening = response.strip()
        if not opening:
            opening = f"来一局海龟汤吧。\n\n{state.current_question}"

        if state.current_question not in opening:
            opening = f"{opening.rstrip()}\n\n{state.current_question}"

        answer = re.sub(r"\s+", "", state.current_answer)
        compact_opening = re.sub(r"\s+", "", opening)
        if answer and answer in compact_opening:
            return f"来一局海龟汤吧。\n\n{state.current_question}"

        return opening

    def _normalize_hint(self, response: str, state: TurtleSoupState) -> str:
        """清理提示输出，避免推理过程和完整汤底泄露。"""

        hint = response.strip().splitlines()[0].strip()
        hint = re.sub(r"^(提示|线索|方向)[:：]\s*", "", hint)
        if not hint:
            return "请关注汤面里最反常的变化。"

        answer = re.sub(r"\s+", "", state.current_answer)
        compact_hint = re.sub(r"\s+", "", hint)
        if answer and (answer in compact_hint or compact_hint in answer and len(compact_hint) >= 18):
            return "请关注汤面里最反常的变化。"

        return hint[:35]

    def _normalize_reveal(self, response: str, state: TurtleSoupState) -> str:
        """确保揭秘话术包含完整汤底。"""

        reveal = response.strip()
        if state.current_answer not in reveal:
            reveal = f"{reveal.rstrip()}\n\n汤底：{state.current_answer}" if reveal else f"汤底：{state.current_answer}"
        return reveal

    def _normalize_no_answer_response(self, response: str, state: TurtleSoupState, fallback: str) -> str:
        """清理不应泄露汤底的主持话术。"""

        message = response.strip() or fallback
        message = re.sub(r"^(CORRECT|WRONG)\s*", "", message, flags=re.I).strip() or fallback
        answer = re.sub(r"\s+", "", state.current_answer)
        compact_message = re.sub(r"\s+", "", message)
        if answer and answer in compact_message:
            return fallback
        return message

    def _normalize_public_host_response(self, response: str, state: TurtleSoupState, fallback: str) -> str:
        """清理公开主持话术中的格式化符号并避免泄底。"""

        message = self._normalize_no_answer_response(response, state, fallback)
        message = re.sub(r"[*_`#]", "", message)
        message = re.sub(r"^\s*[-•]\s*", "", message, flags=re.M)
        message = re.sub(r"\n{3,}", "\n\n", message).strip()
        return message or fallback

    def _build_prompt(self, state: TurtleSoupState, task: str) -> str:
        """构造海龟汤互动提示词。"""

        history = "\n".join(self._format_history(item) for item in state.history[-12:]) or "暂无"
        return (
            "你是海龟汤主持人。必须严格依据已给出的汤面和汤底回答，不能编造新真相。\n"
            "除非任务要求揭秘，否则绝不能直接透露汤底。\n"
            "不要输出推理过程、思考过程、分析过程或 <think> 标签，只输出给玩家看的最终回复。\n\n"
            f"汤面：{state.current_question}\n"
            f"汤底：{state.current_answer}\n\n"
            f"历史交互：\n{history}\n\n"
            f"任务：{task}"
        )

    def _build_public_prompt(self, state: TurtleSoupState, task: str) -> str:
        """构造不包含汤底的公开互动提示词。"""

        history = "\n".join(self._format_history(item) for item in state.history[-12:]) or "暂无"
        return (
            "你是当前聊天里的海龟汤主持人。你只能使用汤面和历史交互中已经公开的信息。\n"
            "不得补充、暗示或编造任何汤底事实。不要输出推理过程、分析过程或 <think> 标签。\n"
            "不要使用 Markdown、星号、加粗、标题模板或报告格式，只输出像日常聊天一样的最终回复。\n\n"
            f"汤面：{state.current_question}\n\n"
            f"历史交互：\n{history}\n\n"
            f"任务：{task}"
        )

    def _format_history(self, item: TurtleSoupHistoryItem) -> str:
        """格式化历史项。"""

        return f"[{item.item_type}] 玩家：{item.content}；主持：{item.response}"
