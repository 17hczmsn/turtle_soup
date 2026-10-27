"""search 链接解析与过滤测试。"""

from __future__ import annotations

from ..search import TurtleSoupSearchClient


def _make_client(**kwargs) -> TurtleSoupSearchClient:
    defaults = {
        "fixed_urls": [],
        "allowed_domains": ["example.com", "bing.com", "baidu.com", "zhihu.com"],
        "enable_web_search": True,
    }
    defaults.update(kwargs)
    return TurtleSoupSearchClient(**defaults)


class TestResolveUrl:
    def test_encoded_absolute_url_kept_as_is(self) -> None:
        # 回归：Bing 结果中的百分号编码中文 URL 不再被解码成裸中文
        url = "https://baike.baidu.com/item/%E6%B5%B7%E9%BE%9F/34663"
        assert _make_client()._resolve_url("https://www.bing.com/search", url) == url

    def test_redirect_param_decoded(self) -> None:
        client = _make_client()
        resolved = client._resolve_url(
            "https://www.bing.com/search",
            "/link?url=https%3A%2F%2Fexample.com%2Fa%3Fb%3D1",
        )
        assert resolved == "https://example.com/a?b=1"

    def test_relative_url_joined_with_base(self) -> None:
        assert (
            _make_client()._resolve_url("https://example.com/dir/page", "/other/page")
            == "https://example.com/other/page"
        )

    def test_javascript_and_mailto_rejected(self) -> None:
        client = _make_client()
        assert client._resolve_url("https://example.com", "javascript:void(0)") == ""
        assert client._resolve_url("https://example.com", "mailto:a@b.c") == ""


class TestResultUrlFiltering:
    def test_static_assets_filtered(self) -> None:
        client = _make_client()
        for path in ("/a.css", "/a.js", "/a.min.js", "/a.png", "/a.woff2", "/a.svg", "/a.css?v=1"):
            assert not client.is_candidate_url(f"https://example.com{path}"), path

    def test_search_engine_hosts_blocked(self) -> None:
        client = _make_client()
        assert not client.is_candidate_url("https://www.bing.com/search?q=x")
        assert not client.is_candidate_url("https://cn.bing.com/top")

    def test_whitelist_enforced(self) -> None:
        client = _make_client()
        assert client.is_candidate_url("https://sub.example.com/bank")
        assert not client.is_candidate_url("https://evil.com/bank")

    def test_extract_result_urls_filters_assets(self) -> None:
        client = _make_client()
        page = (
            '<a href="https://example.com/bank">题库</a>'
            '<a href="https://r.bing.com/rb/x.css">样式</a>'
            '<a href="https://evil.com/x">坏人</a>'
        )
        urls = client.extract_result_urls("https://www.bing.com/search", page, 10)
        assert urls == ["https://example.com/bank"]


class TestSearchSeeds:
    async def test_fixed_urls_plus_engines_capped(self) -> None:
        client = _make_client(fixed_urls=["https://example.com/bank"])
        urls = await client.search("海龟汤", 3)
        assert urls[0] == "https://example.com/bank"
        assert any("bing.com" in url for url in urls)
        assert any("baidu.com" in url for url in urls)
        assert len(urls) <= 3

    async def test_web_search_disabled(self) -> None:
        client = _make_client(fixed_urls=["https://example.com/bank"], enable_web_search=False)
        assert await client.search("海龟汤", 5) == ["https://example.com/bank"]
