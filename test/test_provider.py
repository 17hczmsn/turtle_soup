"""题目提供器补库链路测试（不触网，全部使用假件）。"""

from __future__ import annotations

import json
import time

import pytest

from .. import provider as provider_module
from ..models import TurtleSoupPuzzle
from ..parser import TurtleSoupPageParser
from ..provider import TurtleSoupProvider
from ..search import TurtleSoupSearchClient
from ..validator import TurtleSoupPuzzleValidator

SURFACE = "一个男人走进餐厅，点了一碗海龟汤，尝了一口后走出餐厅自杀了。"
ANSWER = "他曾在海难中靠同伴的肉汤幸存，认出眼前这碗是普通龟汤后崩溃自责。"

BANK_PAGE = f"标题：海龟汤\n汤面：{SURFACE}\n汤底：{ANSWER}"
BANK_URL = "https://example.com/bank"


class FakeCache:
    """内存题库缓存假件。"""

    def __init__(self, puzzles: list[TurtleSoupPuzzle] | None = None) -> None:
        self.items = list(puzzles or [])
        self.append_count = 0
        self.save_count = 0

    def load(self) -> list[TurtleSoupPuzzle]:
        return list(self.items)

    def save(self, puzzles: list[TurtleSoupPuzzle]) -> None:
        self.save_count += 1
        self.items = list(puzzles)

    def append_unique(self, puzzles: list[TurtleSoupPuzzle]) -> list[TurtleSoupPuzzle]:
        self.append_count += 1
        seen = {(p.surface, p.answer) for p in self.items}
        for puzzle in puzzles:
            key = (puzzle.surface, puzzle.answer)
            if key not in seen:
                self.items.append(puzzle)
                seen.add(key)
        return list(self.items)


class FakeFetcher:
    """按 URL 返回预置内容的抓取器假件。"""

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[str] = []

    async def fetch_text(self, url: str) -> str:
        self.calls.append(url)
        return self.responses.get(url, "")


def _make_provider(
    cache: FakeCache,
    fetcher: FakeFetcher,
    fallback_path,
    *,
    fixed_urls: list[str] | None = None,
    min_cache_items: int = 100,
    cooldown_minutes: int = 30,
    **kwargs,
) -> TurtleSoupProvider:
    return TurtleSoupProvider(
        cache=cache,
        search_client=TurtleSoupSearchClient(
            fixed_urls if fixed_urls is not None else [BANK_URL],
            ["example.com"],
            enable_web_search=False,
        ),
        fetcher=fetcher,
        parser=TurtleSoupPageParser(),
        validator=TurtleSoupPuzzleValidator(["example.com"]),
        fallback_bank_path=str(fallback_path),
        min_cache_items=min_cache_items,
        max_fetch_pages=5,
        search_query="海龟汤 汤面 汤底 题库",
        max_search_pages=3,
        supplement_cooldown_minutes=cooldown_minutes,
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _reset_cooldown():
    provider_module._last_supplement_monotonic = 0.0
    yield
    provider_module._last_supplement_monotonic = 0.0


def _write_fallback(path, puzzles: list[dict[str, str]]) -> None:
    path.write_text(json.dumps(puzzles, ensure_ascii=False), encoding="utf-8")


class TestCooldown:
    async def test_cooldown_blocks_supplement(self, tmp_path) -> None:
        fallback = tmp_path / "bank.json"
        _write_fallback(fallback, [{"title": "t", "surface": SURFACE, "answer": ANSWER}])
        cache = FakeCache()
        fetcher = FakeFetcher({BANK_URL: BANK_PAGE})
        provider = _make_provider(cache, fetcher, fallback)

        provider_module._mark_supplement_started()
        puzzle = await provider.get_puzzle()

        assert puzzle.surface == SURFACE
        assert fetcher.calls == []
        assert cache.append_count == 0

    async def test_supplement_runs_when_cooldown_expired(self, tmp_path) -> None:
        fallback = tmp_path / "bank.json"
        cache = FakeCache()
        fetcher = FakeFetcher({BANK_URL: BANK_PAGE})
        provider = _make_provider(cache, fetcher, fallback)

        provider_module._last_supplement_monotonic = time.monotonic() - 31 * 60
        puzzle = await provider.get_puzzle()

        assert puzzle.surface == SURFACE
        assert fetcher.calls == [BANK_URL]
        assert cache.append_count == 1
        assert cache.save_count == 1
        # 种子页就是题库页，不应被重复抓取
        assert fetcher.calls.count(BANK_URL) == 1


class TestMcpPath:
    async def test_mcp_text_parsed_and_urls_extracted(self, tmp_path, monkeypatch) -> None:
        mcp_text = (
            "[1] 海龟汤题库\n"
            "URL: https://example.com/page\n"
            f"内容: 汤面：{SURFACE} 汤底：{ANSWER}\n"
            "---\n"
            "[2] 样式\n"
            "URL: https://example.com/style.css\n"
        )

        class FakeExecutor:
            def __init__(self, plugin, message, preferred_signature: str = "") -> None:
                pass

            async def search(self, query: str) -> str:
                return mcp_text

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", FakeExecutor)
        provider = _make_provider(FakeCache(), FakeFetcher(), tmp_path / "bank.json", plugin=object(), message=object())

        puzzles, urls = await provider._fetch_via_mcp()

        assert len(puzzles) == 1
        assert puzzles[0].surface == SURFACE
        assert urls == ["https://example.com/page"]

    async def test_mcp_disabled_skips_executor(self, tmp_path, monkeypatch) -> None:
        class BoomExecutor:
            def __init__(self, *args, **kwargs) -> None:
                raise AssertionError("不应创建 MCP 执行器")

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", BoomExecutor)
        provider = _make_provider(
            FakeCache(),
            FakeFetcher(),
            tmp_path / "bank.json",
            plugin=object(),
            message=object(),
            use_mcp_search=False,
        )
        assert await provider._fetch_via_mcp() == ([], [])

    async def test_mcp_failure_falls_back_to_builtin(self, tmp_path, monkeypatch) -> None:
        class BrokenExecutor:
            def __init__(self, plugin, message, preferred_signature: str = "") -> None:
                pass

            async def search(self, query: str) -> str:
                return ""

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", BrokenExecutor)
        fetcher = FakeFetcher({BANK_URL: BANK_PAGE})
        cache = FakeCache()
        provider = _make_provider(cache, fetcher, tmp_path / "bank.json", plugin=object(), message=object())

        puzzle = await provider.get_puzzle()

        assert puzzle.surface == SURFACE
        assert fetcher.calls == [BANK_URL]
        assert cache.append_count == 1

    async def test_browser_html_yields_candidate_urls(self, tmp_path, monkeypatch) -> None:
        search_page_url = "https://www.bing.com/search"
        html = (
            "<html><body>"
            '<a href="https://example.com/bank">题库</a>'
            '<a href="https://evil.com/x">不允许的域名</a>'
            '<a href="https://example.com/style.css">静态资源</a>'
            "</body></html>"
        )

        class BrowserFallbackExecutor:
            def __init__(self, plugin, message, preferred_signature: str = "") -> None:
                self.fetched: list[str] = []

            async def search(self, query: str) -> str:
                return ""

            async def search_via_browser(self, query: str) -> list[tuple[str, str]]:
                return [(html, search_page_url)]

            async def fetch_via_browser(self, url: str) -> str:
                self.fetched.append(url)
                return BANK_PAGE

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", BrowserFallbackExecutor)
        fetcher = FakeFetcher()
        cache = FakeCache()
        provider = _make_provider(cache, fetcher, tmp_path / "bank.json", plugin=object(), message=object())

        puzzles, browser_available = await provider._fetch_via_browser([])

        assert browser_available is True
        # 候选页用浏览器会话抓取（裸 HTTP fetcher 不参与），正文按题库页解析
        assert fetcher.calls == []
        assert [p.surface for p in puzzles] == [SURFACE]

    async def test_mcp_puzzles_skip_browser_and_builtin(self, tmp_path, monkeypatch) -> None:
        class NoBrowserExpectedExecutor:
            def __init__(self, plugin, message, preferred_signature: str = "") -> None:
                pass

            async def search(self, query: str) -> str:
                return f"汤面：{SURFACE}\n汤底：{ANSWER}"

            async def search_via_browser(self, query: str) -> list[tuple[str, str]]:
                raise AssertionError("MCP 搜索已出题，不应启用浏览器链路")

            async def fetch_via_browser(self, url: str) -> str:
                raise AssertionError("MCP 搜索已出题，不应抓取候选页")

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", NoBrowserExpectedExecutor)
        fetcher = FakeFetcher()
        cache = FakeCache()
        provider = _make_provider(cache, fetcher, tmp_path / "bank.json", plugin=object(), message=object())

        puzzle = await provider.get_puzzle()

        assert puzzle.surface == SURFACE
        assert fetcher.calls == []
        assert cache.append_count == 1

    async def test_browser_unavailable_falls_back_to_builtin(self, tmp_path, monkeypatch) -> None:
        class NoBrowserExecutor:
            def __init__(self, plugin, message, preferred_signature: str = "") -> None:
                pass

            async def search(self, query: str) -> str:
                return ""

            async def search_via_browser(self, query: str) -> list[tuple[str, str]]:
                return []

        monkeypatch.setattr(provider_module, "MCPSearchExecutor", NoBrowserExecutor)
        fetcher = FakeFetcher({BANK_URL: BANK_PAGE})
        cache = FakeCache()
        provider = _make_provider(cache, fetcher, tmp_path / "bank.json", plugin=object(), message=object())

        puzzle = await provider.get_puzzle()

        # 浏览器不可用 → 内置抓取兜底
        assert puzzle.surface == SURFACE
        assert fetcher.calls == [BANK_URL]


class TestCollectPuzzles:
    async def test_concurrent_collect_filters_disallowed(self) -> None:
        responses = {}
        for index in range(3):
            surface = f"{SURFACE}第{index}题补充"
            answer = f"{ANSWER}第{index}题补充"
            responses[f"https://example.com/p{index}"] = f"汤面：{surface}\n汤底：{answer}"
        responses["https://evil.com/p"] = "汤面：不应该被抓到。汤底：因为域名不在白名单。"

        fetcher = FakeFetcher(responses)
        provider = _make_provider(FakeCache(), fetcher, "nonexistent.json")
        puzzles = await provider._collect_puzzles(list(responses))

        assert len(puzzles) == 3
        assert all("example.com" in (p.source_url or "") for p in puzzles)


class TestChoosePuzzle:
    def test_excludes_current_surface_and_prefers_least_used(self, tmp_path) -> None:
        first = TurtleSoupPuzzle(title="a", surface=SURFACE, answer=ANSWER, used_count=5)
        second = TurtleSoupPuzzle(title="b", surface=SURFACE + "二", answer=ANSWER, used_count=0)
        provider = _make_provider(FakeCache(), FakeFetcher(), tmp_path / "bank.json")

        chosen = provider._choose_puzzle([first, second], {SURFACE})
        assert chosen is second


class TestFallbackOnly:
    async def test_no_network_yields_fallback_puzzle(self, tmp_path) -> None:
        fallback = tmp_path / "bank.json"
        _write_fallback(fallback, [{"title": "t", "surface": SURFACE, "answer": ANSWER}])
        provider = _make_provider(FakeCache(), FakeFetcher({}), fallback)

        puzzle = await provider.get_puzzle()

        assert puzzle.surface == SURFACE

    async def test_all_sources_empty_raises(self, tmp_path) -> None:
        provider = _make_provider(FakeCache(), FakeFetcher({}), tmp_path / "empty.json")
        with pytest.raises(RuntimeError):
            await provider.get_puzzle()
