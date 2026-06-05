"""海龟汤业务服务。"""

from __future__ import annotations

from src.app.plugin_system.base import BaseService

from .cache import TurtleSoupPuzzleCache
from .config import TurtleSoupConfig
from .fetcher import TurtleSoupPageFetcher
from .llm_client import TurtleSoupLLMClient
from .models import TurtleSoupHistoryItem, TurtleSoupState
from .parser import TurtleSoupPageParser
from .provider import TurtleSoupProvider
from .search import TurtleSoupSearchClient
from .state import state_store
from .validator import TurtleSoupPuzzleValidator


class TurtleSoupService(BaseService):
    """海龟汤游戏业务服务。"""

    service_name: str = "turtle_soup"
    service_description: str = "提供海龟汤开局、提问、提示、猜测、揭秘等自然语言游戏能力"
    version: str = "1.0.0"

    async def start_game(self, stream_key: str) -> TurtleSoupState:
        """开始一局新的海龟汤。"""

        provider = self._create_provider()
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
        return state

    def create_opening_facts(self, stream_key: str) -> dict[str, str]:
        """生成当前海龟汤开局事实。"""

        state = self._require_active_state(stream_key)
        return {
            "surface": state.current_question,
            "title": state.title,
        }

    async def ask_question(self, stream_key: str, question: str) -> tuple[bool, str]:
        """回答玩家对当前汤题的提问。"""

        state = self._require_active_state(stream_key)
        response = await self._create_llm_client().answer_question(state, question)
        state.add_history(TurtleSoupHistoryItem("question", question, response), self._get_config().game.max_history_items)
        return True, response

    async def request_hint(self, stream_key: str) -> tuple[bool, str]:
        """为当前汤题生成提示。"""

        state = self._require_active_state(stream_key)
        config = self._get_config()
        if state.hints_used >= config.game.max_hints:
            return False, f"本局提示次数已用完（{config.game.max_hints} 次）。"
        state.hints_used += 1
        response = await self._create_llm_client().create_hint(state)
        state.add_history(TurtleSoupHistoryItem("hint", "请求提示", response), config.game.max_history_items)
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

    async def guess_answer(self, stream_key: str, guess: str) -> tuple[bool, dict[str, object], bool]:
        """判断玩家是否猜中汤底。"""

        state = self._require_active_state(stream_key)
        is_correct, judge_response = await self._create_llm_client().judge_guess(state, guess)
        response = {
            "guess": guess,
            "is_correct": is_correct,
            "judge_feedback": self._clean_judge_feedback(judge_response),
            "answer": state.current_answer if is_correct else "",
        }
        if is_correct:
            state.game_over = True
            state.game_active = False
        history_response = "猜中" if is_correct else response["judge_feedback"]
        state.add_history(TurtleSoupHistoryItem("guess", guess, str(history_response)), self._get_config().game.max_history_items)
        return True, response, is_correct

    def reveal_answer(self, stream_key: str) -> tuple[bool, dict[str, str]]:
        """揭秘并结束当前游戏。"""

        state = self._require_active_state(stream_key)
        state.game_over = True
        state.game_active = False
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
        """获取当前有效游戏状态。"""

        state = state_store.get(stream_key)
        if state is None or not state.game_active:
            raise RuntimeError("当前没有正在进行的海龟汤，请先开一局。")
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

    def _create_provider(self) -> TurtleSoupProvider:
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
        )

    def _create_llm_client(self) -> TurtleSoupLLMClient:
        """创建 LLM 客户端。"""

        return TurtleSoupLLMClient(self._get_config().llm.model_task)
