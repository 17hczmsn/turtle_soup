"""海龟汤工具函数。"""

from __future__ import annotations

import re

from .models import TurtleSoupState

# 一次调用最多回答的问题数，防止群聊突发大量提问拖垮互动回合
MAX_QUESTIONS_PER_CALL = 5

# 多问题输入的常见分隔符：换行、分号
_QUESTION_SEPARATOR_PATTERN = re.compile(r"[\n；;]+")

# 标准回答词
STANDARD_ANSWERS = ("是", "否", "不重要", "部分正确")

# 回答归一化时要剔除的标点与空白
_ANSWER_NOISE_PATTERN = re.compile(r"[\s。，,.！!？?“”\"'`*_#：:]")

# 提示默认兜底文案
HINT_FALLBACK = "请关注汤面里最反常的变化。"


def split_questions(questions: list[str] | str) -> list[str]:
    """把一次调用传入的提问输入规范化为问题列表。

    兼容三种输入：单个问题字符串、多问题合并的字符串（换行或分号分隔）、
    问题列表。会清理首尾标点与空白、去重并保序，超出上限时只保留前若干条。
    """

    if isinstance(questions, str):
        raw_parts = _QUESTION_SEPARATOR_PATTERN.split(questions)
    else:
        raw_parts = []
        for item in questions:
            raw_parts.extend(_QUESTION_SEPARATOR_PATTERN.split(str(item)))

    cleaned: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        question = part.strip(" \u3000\t?？!！。.…")
        if not question:
            continue
        dedupe_key = question.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        cleaned.append(question)
    return cleaned[:MAX_QUESTIONS_PER_CALL]


def normalize_answer(response: str) -> str:
    """把模型输出的判定归一化为海龟汤标准回答词。

    先做整句精确匹配（去标点后完全等于标准词），再做关键词匹配；
    否定形式必须先于肯定形式识别，避免“不是”被当成“是”。
    """

    cleaned = _ANSWER_NOISE_PATTERN.sub("", response or "")
    if cleaned in STANDARD_ANSWERS:
        return cleaned
    if "部分正确" in cleaned:
        return "部分正确"
    if "不重要" in cleaned:
        return "不重要"
    if "不是" in cleaned or "不对" in cleaned or "否" in cleaned:
        return "否"
    if "是" in cleaned:
        return "是"
    return "不重要"


def normalize_hint(response: str, answer: str) -> str:
    """清理提示输出，避免推理过程和完整汤底泄露。"""

    # 模型可能返回空文本或纯空白，取首个非空行前必须先判空
    hint = next((line.strip() for line in (response or "").splitlines() if line.strip()), "")
    hint = re.sub(r"^(提示|线索|方向)[:：]\s*", "", hint)
    if not hint:
        return HINT_FALLBACK

    compact_answer = re.sub(r"\s+", "", answer)
    compact_hint = re.sub(r"\s+", "", hint)
    if compact_answer and (
        compact_answer in compact_hint or compact_hint in compact_answer and len(compact_hint) >= 18
    ):
        return HINT_FALLBACK

    return hint[:35]


# 猜测命中结论的常见真/假写法
_VERDICT_TRUE = {"true", "yes", "correct", "1", "是", "猜中", "命中", "对"}
_VERDICT_FALSE = {"false", "no", "wrong", "0", "否", "未猜中", "未命中", "不对"}


def coerce_verdict(value: object) -> bool | None:
    """把模型给出的命中结论解析为布尔值，无法解析时返回 None。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _VERDICT_TRUE:
            return True
        if lowered in _VERDICT_FALSE:
            return False
    return None


def summarize_known_info(state: TurtleSoupState) -> tuple[list[str], list[str], list[str]]:
    """把历史交互归纳为玩家已知信息：已确认、已排除、已给提示。"""

    confirmed: list[str] = []
    rejected: list[str] = []
    given_hints: list[str] = []
    for item in state.history:
        if item.item_type == "question":
            if item.response in {"是", "部分正确"}:
                confirmed.append(f"{item.content}（{item.response}）")
            elif item.response == "否":
                rejected.append(item.content)
        elif item.item_type == "hint":
            given_hints.append(item.response)
        elif item.item_type == "guess" and item.response != "猜中":
            rejected.append(f"玩家猜测过“{item.content}”（未猜中）")
    return confirmed, rejected, given_hints


def format_known_info(state: TurtleSoupState) -> str:
    """把玩家已知信息格式化为可嵌入 reminder 的文本。"""

    confirmed, rejected, given_hints = summarize_known_info(state)

    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- 暂无"

    return (
        "玩家已知信息归纳：\n"
        f"已确认的事实：\n{_bullets(confirmed)}\n"
        f"已排除的方向：\n{_bullets(rejected)}\n"
        f"已给过的提示：\n{_bullets(given_hints)}"
    )
