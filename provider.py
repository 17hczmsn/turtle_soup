"""海龟汤题目提供器。"""

from __future__ import annotations

import json
import random
from pathlib import Path

from .cache import TurtleSoupPuzzleCache
from .fetcher import TurtleSoupPageFetcher
from .models import TurtleSoupPuzzle
from .parser import TurtleSoupPageParser
from .search import TurtleSoupSearchClient
from .validator import TurtleSoupPuzzleValidator


class TurtleSoupProvider:
    """按缓存、网络、本地兜底顺序提供完整汤题。"""

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

    async def get_puzzle(self, exclude_surfaces: set[str] | None = None) -> TurtleSoupPuzzle:
        """获取一个可用的完整汤题。"""

        excluded = exclude_surfaces or set()
        cached = self._valid_puzzles(self.cache.load())
        if len(cached) < self.min_cache_items:
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
        """从网络候选页面补充新题目。"""

        urls = await self.search_client.search(self.search_query, self.max_search_pages)
        candidate_urls: list[str] = []
        direct_urls: list[str] = []
        for url in urls:
            if not self.validator.is_url_allowed(url):
                continue
            content = await self.fetcher.fetch_text(url)
            if not content:
                continue
            parsed = self.parser.parse(content, source_url=url)
            if parsed:
                candidate_urls.append(url)
                continue
            direct_urls.extend(self.search_client.extract_result_urls(url, content, self.max_fetch_pages))

        candidate_urls.extend(direct_urls)
        candidate_urls = list(dict.fromkeys(candidate_urls))[: self.max_fetch_pages]

        puzzles: list[TurtleSoupPuzzle] = []
        for url in candidate_urls:
            if not self.validator.is_url_allowed(url):
                continue
            content = await self.fetcher.fetch_text(url)
            if not content:
                continue
            puzzles.extend(self.parser.parse(content, source_url=url))
        return self._valid_puzzles(puzzles)

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
        return [TurtleSoupPuzzle.from_dict(item) for item in raw if isinstance(item, dict)]

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
