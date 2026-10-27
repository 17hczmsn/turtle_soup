"""海龟汤主持人 system reminder 管理。

游戏进行期间，把汤底与主持规则写入当前聊天流的私有 ``actor`` bucket：
default_chatter 的主回复模型通过 ``create_request(with_reminder="actor")``
自动拾取，从而在提问判定时无需再调用额外的小模型。

汤底只进入 reminder，不进入任何工具参数或公开回复；游戏结束
（揭秘、退出、猜中）时必须移除，避免失效的机密上下文残留。
"""

from __future__ import annotations

from src.app.plugin_system.api import prompt_api
from src.kernel.logger import get_logger

logger = get_logger("turtle_soup")

_REMINDER_BUCKET = "actor"
_REMINDER_NAME = "turtle_soup_host"


def build_host_reminder(
    title: str,
    surface: str,
    answer: str,
    known_summary: str = "",
    max_hints: int = 3,
) -> str:
    """构造主持人机密 reminder 内容。"""

    known_section = f"\n{known_summary}\n" if known_summary else ""
    return (
        "【海龟汤主持人机密上下文（仅你可见）】\n"
        f"当前聊天正在进行海龟汤游戏《{title}》，你是主持人。以下机密信息禁止以任何形式向玩家透露、暗示或总结：\n"
        f"汤面：{surface}\n"
        f"汤底：{answer}\n"
        f"本局提示额度：每局共 {max_hints} 次（你调用提示工具后回执会告知剩余次数）。\n\n"
        "主持规则：\n"
        "1. 玩家提问是非题时，依据汤底自行判定，只能用『是』『否』『不重要』『部分正确』四个标准词作答；"
        "可以按你的角色语气润色，但判定不能改变。\n"
        "2. 判定从严：『是』仅当该内容在汤底中直接成立或必然可推出；方向沾边但细节无法确认时不得答『是』；"
        "拿不准优先『否』或『不重要』；不要与已给过的回答矛盾。\n"
        "3. 判定后调用 ask_turtle_soup_question 记录问答（questions 与 answers 一一对应，answers 填你的判定标准词），"
        "并把它放在本轮调用的最前面；随后在同一轮直接调用 action-send_text 向玩家回复你的判定。"
        "逐条回复不同玩家时尽量携带 reply_to 指向各自的问题，避免内容相同时被去重跳过。"
        "工具返回只是记录回执，不要等它返回才开始回复，也不要据回执把同样的话再说一遍。"
        "本轮不要调用 action-pass_and_wait；下一轮看到记录回执后，若已回复完毕，再调用 action-pass_and_wait 进入等待。"
        "任何工具参数和回复里都不得出现汤底。\n"
        "4. 玩家要提示时，依据汤底和下方『玩家已知信息归纳』，选一个玩家尚未确认、尚未排除、也没提示过的方向，"
        "生成一条不超过 35 字、不泄露汤底关键名词/身份/动机/结局的方向性线索，"
        "调用 request_turtle_soup_hint 把线索传入 hint 参数记录，并在同一轮调用 action-send_text 围绕该线索回复玩家"
        "（可顺带告知剩余提示次数）；工具返回会给出规范化后的提示，若与你传入的不同，以回执为准。"
        "本轮不要调用 action-pass_and_wait，下一轮看到回执后再等待。不得复述已给过的提示。\n"
        "5. 玩家给出汤底猜测时，自行判断是否基本命中：只有当猜测覆盖汤底的核心因果与关键事实时才算命中，只沾边不算。"
        "调用 guess_turtle_soup_answer 把结论传入 is_correct 参数，并在同一轮调用 action-send_text 给出反馈："
        "猜中时必须完整公布汤底原文并收束本局，未猜中时按你的角色简短反馈、不得透露或编造。"
        "本轮不要调用 action-pass_and_wait；后续需要等待时在下一轮调用。\n"
        "6. 玩家要求揭秘时调用 reveal_turtle_soup_answer；要退出时调用 exit_turtle_soup_game。"
        f"{known_section}"
    )


def inject_host_reminder(
    stream_id: str,
    title: str,
    surface: str,
    answer: str,
    known_summary: str = "",
    max_hints: int = 3,
) -> None:
    """向聊天流注入（或覆盖）主持人 reminder。"""

    if not stream_id:
        return
    content = build_host_reminder(title, surface, answer, known_summary, max_hints)
    try:
        prompt_api.add_stream_reminder(stream_id, _REMINDER_BUCKET, _REMINDER_NAME, content)
    except Exception:
        logger.warning("注入海龟汤主持人 reminder 失败", exc_info=True)


def remove_host_reminder(stream_id: str) -> None:
    """移除聊天流的主持人 reminder；没有游戏在进行时静默。"""

    if not stream_id:
        return
    try:
        if prompt_api.delete_stream_reminder(stream_id, _REMINDER_BUCKET, _REMINDER_NAME):
            logger.info(f"已移除海龟汤主持人 reminder（流 {stream_id}）")
    except Exception:
        logger.warning("移除海龟汤主持人 reminder 失败", exc_info=True)
