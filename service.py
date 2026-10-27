"""海龟汤业务服务。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.app.plugin_system.base import BaseService
from src.kernel.logger import get_logger

from .cache import TurtleSoupPuzzleCache
from .config import TurtleSoupConfig
from .fetcher import TurtleSoupPageFetcher
from .llm_client import TurtleSoupLLMClient
from .models import TurtleSoupHistoryItem, TurtleSoupState
from .parser import TurtleSoupPageParser
from .provider import TurtleSoupProvider
from .reminder import inject_host_reminder, remove_host_reminder
from .search import TurtleSoupSearchClient
from .state import state_store
from .utils import (
    MAX_QUESTIONS_PER_CALL,
    coerce_verdict,
    format_known_info,
    normalize_answer,
    normalize_hint,
    split_questions,
)
from .validator import TurtleSoupPuzzleValidator

if TYPE_CHECKING:
    from src.core.models.message import Message

logger = get_logger("turtle_soup")


class TurtleSoupService(BaseService):
    """海龟汤游戏业务服务。"""

    service_name: str = "turtle_soup"
    service_description: str = "提供海龟汤开局、提问、提示、猜测、揭秘等自然语言游戏能力"
    version: str = "1.2.0"

    async def start_game(self, stream_key: str, message: "Message | None" = None) -> TurtleSoupState:
        """开始一局新的海龟汤。

        Args:
            stream_key: 聊天流键。
            message: 触发消息，用于补库时调用 MCP 搜索工具，可为空。
        """

        provider = self._create_provider(message)
        current_state = state_store.get(stream_key)
        excluded = {current_state.current_question} if current_state and current_state.current_question else set()
        puzzle = await provider.get_puzzle(exclude_surfaces=excluded)
        state = TurtleSoupState(
            stream_key=stream_key,
            current_question=puzzle.surface,
            current_answer=puzzle.answer,
            title=puzzle.title,
            source_url=puzzle.source_url,
            game_active=True,
            game_over=False,
        )
        state_store.set(state)
        # 先清旧机密再按配置注入：换汤/重开时旧局 reminder 若残留会泄露旧汤底
        remove_host_reminder(stream_key)
        if self._get_config().llm.answer_in_actor_model:
            # 汤底直接进入主回复模型上下文，问答/提示/猜测均由主模型完成
            inject_host_reminder(
                stream_key,
                state.title,
                state.current_question,
                state.current_answer,
                max_hints=self._get_config().game.max_hints,
            )
        return state

    def expire_if_idle(self, stream_key: str) -> bool:
        """闲置超时则结束本局并移除 reminder，返回是否发生了过期。

        供事件处理器在每次主模型请求前调用，防止玩家散场后
        主持人机密上下文残留在后续无关对话的模型请求里。
        无游戏状态时的 reminder 残留（如插件热重载）也会顺带自愈清理。
        """

        state = state_store.get(stream_key)
        if state is None:
            # 正常无游戏时 reminder 不应存在；存在即残留，静默清理
            remove_host_reminder(stream_key)
            return False
        if not state.game_active:
            return False
        timeout = self._get_config().game.idle_timeout_minutes
        if not state.is_idle_expired(timeout):
            return False
        state.game_active = False
        state.game_over = True
        remove_host_reminder(stream_key)
        logger.info(
            f"海龟汤闲置超过 {timeout} 分钟，本局已自动结束并移除主持人 reminder（流 {stream_key}）"
        )
        return True

    def create_opening_facts(self, stream_key: str) -> dict[str, str]:
        """生成当前海龟汤开局事实。"""

        state = self._require_active_state(stream_key)
        return {
            "surface": state.current_question,
            "title": state.title,
        }

    async def ask_question(self, stream_key: str, question: str) -> tuple[bool, str]:
        """回答玩家对当前汤题的单个提问。"""

        results = await self.ask_questions(stream_key, [question])
        answer = str(results[1][0]["answer"]) if results[1] else "不重要"
        return results[0], answer

    async def ask_questions(
        self,
        stream_key: str,
        questions: list[str] | str,
        answers: list[str] | None = None,
    ) -> tuple[bool, list[dict[str, str]]]:
        """回答一个或多个玩家问题。

        ``answers`` 为主回复模型依据 reminder 中的汤底自行给出的判定；
        缺失或与问题数量不匹配时，逐条退回小模型判定，保证游戏不中断。
        群聊中多名玩家可能同时提问，由调用方把所有待回答的问题
        合并进一次调用，这里逐条记录历史，避免漏答。
        """

        state = self._require_active_state(stream_key)
        client = self._create_llm_client()
        config = self._get_config()
        question_list = split_questions(questions)
        if not question_list:
            logger.info("ask_questions 收到空问题输入，跳过")
            return False, []
        if len(question_list) >= MAX_QUESTIONS_PER_CALL:
            logger.info(f"单次问答达到上限 {MAX_QUESTIONS_PER_CALL} 条，超出部分本轮不回答")
        answer_list = [str(answer or "").strip() for answer in (answers or [])]
        if len(answer_list) != len(question_list):
            if answer_list:
                logger.warning(
                    f"问答数量不匹配（{len(question_list)} 问 / {len(answer_list)} 答），改用小模型判定"
                )
            answer_list = []

        results: list[dict[str, str]] = []
        for index, question in enumerate(question_list):
            if index < len(answer_list) and answer_list[index]:
                answer = normalize_answer(answer_list[index])
            else:
                answer = await client.answer_question(state, question)
            state.add_history(TurtleSoupHistoryItem("question", question, answer), config.game.max_history_items)
            results.append({"question": question, "answer": answer})
        self._refresh_reminder_if_actor(stream_key, state)
        return True, results

    async def request_hint(self, stream_key: str, hint_text: str = "") -> tuple[bool, str]:
        """为当前汤题生成提示。

        ``hint_text`` 为主回复模型依据 reminder 中的汤底与玩家已知信息
        自行生成的线索；为空时退回小模型生成。提示次数只在成功生成后
        消耗，生成失败不占用本局额度。
        """

        state = self._require_active_state(stream_key)
        config = self._get_config()
        if state.hints_used >= config.game.max_hints:
            return False, f"本局提示次数已用完（{config.game.max_hints} 次）。"
        hint_text = str(hint_text or "").strip()
        if hint_text:
            response = normalize_hint(hint_text, state.current_answer)
        else:
            try:
                response = await self._create_llm_client().create_hint(state, config.game.max_hints)
            except Exception:
                logger.warning("海龟汤提示生成失败", exc_info=True)
                return False, "提示生成失败，请稍后再试一次。"
        state.hints_used += 1
        state.add_history(TurtleSoupHistoryItem("hint", "请求提示", response), config.game.max_history_items)
        self._refresh_reminder_if_actor(stream_key, state)
        return True, response

    def summarize_clues(self, stream_key: str) -> tuple[bool, dict[str, object]]:
        """整理当前公开线索事实。"""

        state = self._require_active_state(stream_key)
        public_history = [
            item.to_dict()
            for item in state.history
            if item.item_type in {"question", "hint", "guess"}
        ]
        state.add_history(TurtleSoupHistoryItem("clues", "整理线索", "已请求整理公开线索"), self._get_config().game.max_history_items)
        return True, {
            "surface": state.current_question,
            "history": public_history,
            "hints_used": state.hints_used,
        }

    async def guess_answer(
        self,
        stream_key: str,
        guess: str,
        model_verdict: bool | str | None = None,
    ) -> tuple[bool, dict[str, object], bool]:
        """判断玩家是否猜中汤底。

        ``model_verdict`` 为主回复模型依据 reminder 中的汤底自行给出的
        命中结论；未提供或无法解析时退回小模型判定。
        """

        state = self._require_active_state(stream_key)
        verdict = coerce_verdict(model_verdict)
        if verdict is None:
            is_correct, judge_response = await self._create_llm_client().judge_guess(state, guess)
            feedback = self._clean_judge_feedback(judge_response)
        else:
            is_correct = verdict
            # actor 模式下反馈话术由主模型按语境自行组织
            feedback = "猜中" if is_correct else "未猜中"
        response = {
            "guess": guess,
            "is_correct": is_correct,
            "judge_feedback": feedback,
            "answer": state.current_answer if is_correct else "",
        }
        if is_correct:
            state.game_over = True
            state.game_active = False
            # 汤底已公开，主持人机密上下文不再需要
            remove_host_reminder(stream_key)
        history_response = "猜中" if is_correct else feedback
        state.add_history(TurtleSoupHistoryItem("guess", guess, str(history_response)), self._get_config().game.max_history_items)
        if not is_correct:
            # 猜错是新的已排除方向，刷新要包含本次猜测，放在 add_history 之后
            self._refresh_reminder_if_actor(stream_key, state)
        return True, response, is_correct

    def reveal_answer(self, stream_key: str) -> tuple[bool, dict[str, str]]:
        """揭秘并结束当前游戏。"""

        state = self._require_active_state(stream_key)
        state.game_over = True
        state.game_active = False
        remove_host_reminder(stream_key)
        response = {
            "surface": state.current_question,
            "answer": state.current_answer,
        }
        state.add_history(TurtleSoupHistoryItem("reveal", "揭秘", state.current_answer), self._get_config().game.max_history_items)
        return True, response

    def exit_game(self, stream_key: str) -> tuple[bool, dict[str, str] | str]:
        """退出当前游戏。"""

        state = state_store.get(stream_key)
        if state is None or not state.game_active:
            return False, "当前没有正在进行的海龟汤。"
        surface = state.current_question
        state.game_active = False
        state.game_over = True
        remove_host_reminder(stream_key)
        return True, {"surface": surface}

    def get_state(self, stream_key: str) -> dict[str, object]:
        """获取公开游戏状态。"""

        state = state_store.get(stream_key)
        if state is None:
            return {"game_active": False, "game_over": False, "history_count": 0}
        return state.to_public_dict()

    def get_question(self, stream_key: str) -> tuple[bool, str]:
        """获取当前汤面。"""

        state = state_store.get(stream_key)
        if state is None or not state.current_question:
            return False, "当前没有海龟汤汤面。"
        return True, state.current_question

    def _require_active_state(self, stream_key: str) -> TurtleSoupState:
        """获取当前有效游戏状态；闲置超时会先自动结束本局。"""

        self.expire_if_idle(stream_key)
        state = state_store.get(stream_key)
        if state is None or not state.game_active:
            raise RuntimeError("当前没有正在进行的海龟汤，请先开一局。")
        state.touch()
        return state

    def _clean_judge_feedback(self, judge_response: str) -> str:
        """清理猜测判断结果中的控制标记。"""

        lines = [line.strip() for line in judge_response.splitlines() if line.strip()]
        if lines and lines[0].upper().startswith(("CORRECT", "WRONG")):
            lines = lines[1:]
        return "\n".join(lines).strip() or "还没有猜中。"

    def _get_config(self) -> TurtleSoupConfig:
        """获取插件配置。"""

        if isinstance(self.plugin.config, TurtleSoupConfig):
            return self.plugin.config
        return TurtleSoupConfig()

    def _refresh_reminder_if_actor(self, stream_key: str, state: TurtleSoupState) -> None:
        """actor 模式下，用最新玩家已知信息刷新主持人 reminder。"""

        if not self._get_config().llm.answer_in_actor_model:
            return
        inject_host_reminder(
            stream_key,
            state.title,
            state.current_question,
            state.current_answer,
            known_summary=format_known_info(state),
            max_hints=self._get_config().game.max_hints,
        )

    def _create_provider(self, message: "Message | None" = None) -> TurtleSoupProvider:
        """创建题目提供器。"""

        config = self._get_config()
        return TurtleSoupProvider(
            cache=TurtleSoupPuzzleCache(config.puzzle.cache_path),
            search_client=TurtleSoupSearchClient(
                config.puzzle.search_urls,
                config.puzzle.allowed_domains,
                config.puzzle.enable_web_search,
            ),
            fetcher=TurtleSoupPageFetcher(config.puzzle.request_timeout_seconds, config.puzzle.max_page_bytes),
            parser=TurtleSoupPageParser(),
            validator=TurtleSoupPuzzleValidator(config.puzzle.allowed_domains),
            fallback_bank_path=config.puzzle.fallback_bank_path,
            min_cache_items=config.puzzle.min_cache_items,
            max_fetch_pages=config.puzzle.max_fetch_pages,
            search_query=config.puzzle.search_query,
            max_search_pages=config.puzzle.max_search_pages,
            plugin=self.plugin,
            message=message,
            supplement_cooldown_minutes=config.puzzle.supplement_cooldown_minutes,
            use_mcp_search=config.puzzle.use_mcp_search,
            mcp_tool_signature=config.puzzle.mcp_tool_signature,
        )

    def _create_llm_client(self) -> TurtleSoupLLMClient:
        """创建 LLM 客户端。"""

        return TurtleSoupLLMClient(self._get_config().llm.model_task)
