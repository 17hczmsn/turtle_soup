"""海龟汤题目提供器。"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from src.kernel.logger import get_logger

from .cache import TurtleSoupPuzzleCache
from .fetcher import TurtleSoupPageFetcher
from .mcp_search import MCPSearchExecutor
from .models import TurtleSoupPuzzle
from .parser import TurtleSoupPageParser
from .search import TurtleSoupSearchClient
from .validator import TurtleSoupPuzzleValidator

if TYPE_CHECKING:
    from src.core.components.base.plugin import BasePlugin
    from src.core.models.message import Message

logger = get_logger("turtle_soup")

# MCP 搜索结果文本中的 "URL: https://..." 行
_MCP_URL_PATTERN = re.compile(r"URL[:：]\s*(https?://[^\s\"'<>]+)")

# 进程级补库冷却时间戳（monotonic 秒），跨 Provider 实例共享
_last_supplement_monotonic: float = 0.0


def _cooldown_expired(cooldown_minutes: int) -> bool:
    """判断补库冷却是否已过。"""

    if cooldown_minutes <= 0:
        return True
    return (time.monotonic() - _last_supplement_monotonic) >= cooldown_minutes * 60


def _mark_supplement_started() -> None:
    """记录本次补库开始时间，冷却从补库发起时计算。"""

    global _last_supplement_monotonic
    _last_supplement_monotonic = time.monotonic()


class TurtleSoupProvider:
    """按缓存、网络、本地兜底顺序提供完整汤题。

    网络补库分两路：
    1. MCP 路径：直接调用自动发现的 MCP 网络搜索工具，对返回文本解析抽题，
       并把结果中的 URL 作为内置抓取的额外候选页；
    2. 内置抓取：搜索引擎/固定 URL 种子页 → 链接提取 → 候选页并发抓取解析。
    两路受统一的补库冷却约束，任一路失败不影响另一路。
    """

    _FETCH_CONCURRENCY = 5
    # 浏览器抓取单页要真实导航（2-4 秒/页），且补库发生在开局工具调用内、
    # 受 chatter 单步超时约束，候选页数量必须设上限
    _BROWSER_FETCH_CAP = 8

    def __init__(
        self,
        cache: TurtleSoupPuzzleCache,
        search_client: TurtleSoupSearchClient,
        fetcher: TurtleSoupPageFetcher,
        parser: TurtleSoupPageParser,
        validator: TurtleSoupPuzzleValidator,
        fallback_bank_path: str,
        min_cache_items: int,
        max_fetch_pages: int,
        search_query: str,
        max_search_pages: int,
        *,
        plugin: "BasePlugin | None" = None,
        message: "Message | None" = None,
        supplement_cooldown_minutes: int = 30,
        use_mcp_search: bool = True,
        mcp_tool_signature: str = "",
    ) -> None:
        """初始化题目提供器。"""

        self.cache = cache
        self.search_client = search_client
        self.fetcher = fetcher
        self.parser = parser
        self.validator = validator
        self.fallback_bank_path = Path(fallback_bank_path)
        self.min_cache_items = min_cache_items
        self.max_fetch_pages = max_fetch_pages
        self.search_query = search_query
        self.max_search_pages = max_search_pages
        self.plugin = plugin
        self.message = message
        self.supplement_cooldown_minutes = supplement_cooldown_minutes
        self.use_mcp_search = use_mcp_search
        self.mcp_tool_signature = mcp_tool_signature

    async def get_puzzle(self, exclude_surfaces: set[str] | None = None) -> TurtleSoupPuzzle:
        """获取一个可用的完整汤题。"""

        excluded = exclude_surfaces or set()
        cached = self._valid_puzzles(self.cache.load())
        if len(cached) < self.min_cache_items and _cooldown_expired(self.supplement_cooldown_minutes):
            logger.info(f"缓存题目 {len(cached)} 低于阈值 {self.min_cache_items}，开始补充题库")
            _mark_supplement_started()
            fetched = await self._fetch_new_puzzles()
            fallback = self._load_fallback_bank()
            if fetched or fallback:
                cached = self._valid_puzzles(self.cache.append_unique([*fetched, *fallback]))
        if cached:
            puzzle = self._choose_puzzle(cached, excluded)
            puzzle.used_count += 1
            self.cache.save(cached)
            return puzzle

        fallback = self._valid_puzzles(self._load_fallback_bank())
        if fallback:
            return self._choose_puzzle(fallback, excluded)
        raise RuntimeError("没有可用的海龟汤题目")

    async def _fetch_new_puzzles(self) -> list[TurtleSoupPuzzle]:
        """从 MCP 搜索、浏览器 MCP、内置抓取三路补充新题目。

        优先级：专用搜索工具（如 tavily）→ 浏览器全链路（搜索页 +
        候选页都用浏览器会话抓取）→ 内置裸 HTTP 抓取（浏览器不可用
        时的最终兜底）。
        """

        mcp_puzzles, mcp_urls = await self._fetch_via_mcp()

        # 专用搜索已拿到题目时不再动用浏览器（避免无谓弹出浏览器窗口），
        # 仅在它颗粒无收时走浏览器全链路，浏览器也不可用才退回内置抓取
        browser_puzzles: list[TurtleSoupPuzzle] = []
        builtin_puzzles: list[TurtleSoupPuzzle] = []
        if not mcp_puzzles:
            browser_puzzles, browser_available = await self._fetch_via_browser(mcp_urls)
            if not browser_available:
                builtin_puzzles = await self._fetch_via_builtin(mcp_urls)

        logger.info(
            f"题库补充完成：MCP 搜索 {len(mcp_puzzles)} 题，浏览器抓取 {len(browser_puzzles)} 题，"
            f"内置抓取 {len(builtin_puzzles)} 题"
        )
        return self._valid_puzzles([*mcp_puzzles, *browser_puzzles, *builtin_puzzles])

    async def _fetch_via_mcp(self) -> tuple[list[TurtleSoupPuzzle], list[str]]:
        """通过专用 MCP 搜索工具补充题目并提取候选 URL。

        未启用、缺少插件或消息上下文、或工具不可用时返回空结果，
        由浏览器/内置抓取兜底。
        """

        if not self.use_mcp_search:
            logger.debug("MCP 补库未启用（use_mcp_search=false），跳过")
            return [], []
        if self.plugin is None or self.message is None:
            logger.debug("MCP 补库缺少插件或消息上下文，跳过")
            return [], []

        executor = MCPSearchExecutor(
            self.plugin,
            self.message,
            preferred_signature=self.mcp_tool_signature,
        )
        try:
            text = await executor.search(self.search_query)
        except Exception:
            logger.warning("MCP 补库搜索异常，退回浏览器/内置抓取", exc_info=True)
            return [], []
        if not text:
            logger.info("没有可用的专用搜索类 MCP 工具或全部调用失败，转浏览器/内置抓取")
            return [], []

        puzzles = self.parser.parse(text, source_url="mcp_search")
        urls = [
            url
            for url in _MCP_URL_PATTERN.findall(text)
            if self.search_client.is_candidate_url(url) and self.validator.is_url_allowed(url)
        ]
        logger.info(f"MCP 搜索返回 {len(puzzles)} 题、{len(urls)} 个候选页链接")
        return puzzles, list(dict.fromkeys(urls))

    async def _fetch_via_browser(self, extra_candidates: list[str]) -> tuple[list[TurtleSoupPuzzle], bool]:
        """浏览器 MCP 全链路补库：搜索页 → 候选页抓取 → 解析。

        候选页也通过浏览器会话抓取（真实 UA 与 Cookie），避免裸 HTTP
        被知乎等反爬站点拦截。返回 (题目列表, 浏览器链路是否可用)；
        不可用时由调用方退回内置抓取。
        """

        if not self.use_mcp_search or self.plugin is None or self.message is None:
            return [], False
        executor = MCPSearchExecutor(
            self.plugin,
            self.message,
            preferred_signature=self.mcp_tool_signature,
        )
        try:
            search_pages = await executor.search_via_browser(self.search_query)
        except Exception:
            logger.warning("浏览器 MCP 搜索异常，退回内置抓取", exc_info=True)
            return [], False
        if not search_pages:
            return [], False

        puzzles: list[TurtleSoupPuzzle] = []
        candidate_urls: list[str] = list(extra_candidates or [])
        for html, page_url in search_pages:
            puzzles.extend(self.parser.parse(html, source_url="mcp_search"))
            candidate_urls.extend(
                url
                for url in self.search_client.extract_result_urls(page_url, html, self.max_fetch_pages)
                if self.validator.is_url_allowed(url)
            )
        candidate_urls = list(dict.fromkeys(candidate_urls))
        browser_cap = min(self.max_fetch_pages, self._BROWSER_FETCH_CAP)
        if len(candidate_urls) > browser_cap:
            logger.info(
                f"浏览器补库候选页 {len(candidate_urls)} 个，为控制单步耗时只抓取前 {browser_cap} 个"
            )
            candidate_urls = candidate_urls[:browser_cap]

        fetched_count = 0
        for url in candidate_urls:
            try:
                page_html = await executor.fetch_via_browser(url)
            except Exception:
                continue
            if not page_html:
                continue
            fetched_count += 1
            puzzles.extend(self.parser.parse(page_html, source_url=url))
        logger.info(
            f"浏览器补库：候选页 {len(candidate_urls)} 个，成功抓取 {fetched_count} 个，共解析 {len(puzzles)} 题"
        )
        return puzzles, True

    async def _fetch_via_builtin(self, extra_candidates: list[str]) -> list[TurtleSoupPuzzle]:
        """内置抓取：种子页发现候选，再并发抓取解析。

        Args:
            extra_candidates: 其他来源（如 MCP 搜索结果）给出的候选 URL，优先抓取。
        """

        puzzles: list[TurtleSoupPuzzle] = []
        candidate_urls: list[str] = list(extra_candidates)

        seed_urls = await self.search_client.search(self.search_query, self.max_search_pages)
        for url in seed_urls:
            if not self.validator.is_url_allowed(url):
                continue
            content = await self.fetcher.fetch_text(url)
            if not content:
                continue
            parsed = self.parser.parse(content, source_url=url)
            if parsed:
                # 种子页本身就是题库页，直接收录，避免二次抓取
                puzzles.extend(parsed)
                continue
            candidate_urls.extend(
                self.search_client.extract_result_urls(url, content, self.max_fetch_pages)
            )

        candidate_urls = list(dict.fromkeys(candidate_urls))[: self.max_fetch_pages]
        puzzles.extend(await self._collect_puzzles(candidate_urls))
        if not puzzles:
            logger.warning("内置抓取未获得任何题目：网络不可用，或白名单域名内没有可解析的题库页")
        return puzzles

    async def _collect_puzzles(self, urls: list[str]) -> list[TurtleSoupPuzzle]:
        """并发抓取候选页并解析题目，单页失败不影响其他页。"""

        semaphore = asyncio.Semaphore(self._FETCH_CONCURRENCY)

        async def _fetch_one(url: str) -> list[TurtleSoupPuzzle]:
            if not self.validator.is_url_allowed(url):
                return []
            async with semaphore:
                try:
                    content = await self.fetcher.fetch_text(url)
                except Exception:
                    return []
            if not content:
                return []
            return self.parser.parse(content, source_url=url)

        results = await asyncio.gather(*(_fetch_one(url) for url in urls))
        return [puzzle for batch in results for puzzle in batch]

    def _load_fallback_bank(self) -> list[TurtleSoupPuzzle]:
        """读取本地兜底题库。"""

        if not self.fallback_bank_path.exists():
            return []
        try:
            raw = json.loads(self.fallback_bank_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(raw, list):
            return []
        puzzles: list[TurtleSoupPuzzle] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                puzzles.append(TurtleSoupPuzzle.from_dict(item))
            except (TypeError, ValueError):
                continue
        return puzzles

    def _valid_puzzles(self, puzzles: list[TurtleSoupPuzzle]) -> list[TurtleSoupPuzzle]:
        """过滤有效题目。"""

        return [puzzle for puzzle in puzzles if self.validator.is_valid(puzzle)]

    def _choose_puzzle(self, puzzles: list[TurtleSoupPuzzle], exclude_surfaces: set[str]) -> TurtleSoupPuzzle:
        """按最少使用次数选择题目，并尽量避开当前题。"""

        candidates = [puzzle for puzzle in puzzles if puzzle.surface not in exclude_surfaces]
        if not candidates:
            candidates = puzzles
        min_used_count = min(puzzle.used_count for puzzle in candidates)
        least_used = [puzzle for puzzle in candidates if puzzle.used_count == min_used_count]
        return random.choice(least_used)
