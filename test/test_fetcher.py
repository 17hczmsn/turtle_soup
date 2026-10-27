"""fetcher URL 规范化与异常兜底测试。"""

from __future__ import annotations

from ..fetcher import TurtleSoupPageFetcher


def _make_fetcher() -> TurtleSoupPageFetcher:
    return TurtleSoupPageFetcher(timeout_seconds=5.0, max_page_bytes=1024)


class TestNormalizeUrl:
    def test_plain_ascii_url_unchanged(self) -> None:
        url = "https://example.com/bank?page=1&lang=zh"
        assert TurtleSoupPageFetcher._normalize_url(url) == url

    def test_chinese_path_gets_encoded(self) -> None:
        normalized = TurtleSoupPageFetcher._normalize_url("https://baike.baidu.com/item/海龟/34663")
        assert normalized.startswith("https://baike.baidu.com/item/")
        assert "海龟" not in normalized
        assert "%E6%B5%B7%E9%BE%9F" in normalized

    def test_existing_percent_encoding_not_doubled(self) -> None:
        url = "https://example.com/item/%E6%B5%B7%E9%BE%9F?a=1&b=%20x"
        assert TurtleSoupPageFetcher._normalize_url(url) == url

    def test_missing_scheme_or_host_returns_empty(self) -> None:
        assert TurtleSoupPageFetcher._normalize_url("not-a-url") == ""
        assert TurtleSoupPageFetcher._normalize_url("http://") == ""
        assert TurtleSoupPageFetcher._normalize_url("") == ""


class TestFetchErrorHandling:
    def test_invalid_url_returns_empty_without_raising(self) -> None:
        fetcher = _make_fetcher()
        import asyncio

        assert asyncio.run(fetcher.fetch_text("http://")) == ""

    def test_non_ascii_host_returns_empty_without_raising(self) -> None:
        # 曾经的线上崩溃点：非法 URL 必须被吞掉而不是抛 UnicodeEncodeError
        fetcher = _make_fetcher()
        import asyncio

        assert asyncio.run(fetcher.fetch_text("http://例子.测试/汤")) == ""
