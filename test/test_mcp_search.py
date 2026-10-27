"""MCP 搜索工具打分与参数适配测试。"""

from __future__ import annotations

from ..mcp_search import (
    _looks_successful,
    _resolve_url_param,
    build_search_urls,
    discover_browser_fetch_tools,
    score_search_tool,
    _resolve_params,
)

_URL_SCHEMA = {
    "function": {"parameters": {"properties": {"url": {"type": "string"}}}}
}


class _FakeTool:
    """注册表假件：按签名提供名称。"""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description


class TestScoreSearchTool:
    def test_web_search_tools_scored(self) -> None:
        assert score_search_tool("mcp-tavily-web-search", "使用 Tavily API 进行实时网络搜索") > 0
        assert score_search_tool("mcp-brave-web_search", "Search the web with Brave") > 0
        assert score_search_tool("mcp-duckduckgo-search", "search the internet") > 0

    def test_local_file_search_rejected(self) -> None:
        assert score_search_tool("mcp-filesystem-search_files", "Search for files in a given directory") == 0

    def test_search_without_web_signal_rejected(self) -> None:
        assert score_search_tool("mcp-notes-search", "搜索你的本地笔记") == 0

    def test_desc_only_search_with_web_name_accepted(self) -> None:
        assert score_search_tool("mcp-tavily-query", "search the web for information") > 0

    def test_code_search_rejected(self) -> None:
        assert score_search_tool("mcp-github-search_code", "web search code in repositories") == 0

    def test_negative_signal_in_name_rejected(self) -> None:
        assert score_search_tool("mcp-memory-web-search", "search the web") == 0
        assert score_search_tool("mcp-media-video_search", "网络搜索视频") == 0

    def test_negative_signal_only_in_description_still_accepted(self) -> None:
        # 回归：tavily 工具描述的使用示例含“数据库连接问题”，
        # 不能因此排除整个搜索工具
        tavily_description = (
            "使用 Tavily API 进行实时网络搜索。\n"
            "使用示例：\n4. \"如何解决数据库连接问题\"\n"
            "注意：搜索结果是实时的，来自当前的网络信息。"
        )
        assert score_search_tool("mcp-tavily-web-search", tavily_description) > 0


class TestResolveUrlParam:
    def test_prefers_url_key(self) -> None:
        assert _resolve_url_param(_URL_SCHEMA) == "url"

    def test_falls_back_to_first_string_param(self) -> None:
        schema = {
            "function": {"parameters": {"properties": {"address": {"type": "string"}}}}
        }
        assert _resolve_url_param(schema) == "address"

    def test_no_string_param_returns_none(self) -> None:
        schema = {"function": {"parameters": {"properties": {"count": {"type": "integer"}}}}}
        assert _resolve_url_param(schema) is None


class TestLooksSuccessful:
    def test_ok_prefix_is_success(self) -> None:
        assert _looks_successful("[OK] HTTP 200\n\n<html>...</html>") is True

    def test_success_true_json_is_success(self) -> None:
        assert _looks_successful('{"success": true, "message": "已打开"}') is True

    def test_success_false_json_is_failure(self) -> None:
        assert _looks_successful('{"success": false, "error_code": "browser_not_open"}') is False

    def test_empty_is_failure(self) -> None:
        assert _looks_successful("") is False
        assert _looks_successful("   ") is False

    def test_plain_text_is_success(self) -> None:
        assert _looks_successful("一段普通文本内容") is True


class TestBuildSearchUrls:
    def test_bing_before_baidu_with_encoded_query(self) -> None:
        urls = build_search_urls("海龟汤 题库")
        assert urls[0].startswith("https://www.bing.com/search?q=")
        assert urls[1].startswith("https://www.baidu.com/s?wd=")
        assert "%E6%B5%B7%E9%BE%9F%E6%B1%A4" in urls[0]


class TestDiscoverBrowserFetchTools:
    def _patch_registry(self, monkeypatch, tools: dict[str, _FakeTool]) -> None:
        import src.app.plugin_system.api.tool_api as tool_api

        monkeypatch.setattr(tool_api, "get_all_tools", lambda: tools)
        monkeypatch.setattr(tool_api, "get_tool_schema", lambda signature: _URL_SCHEMA)

    def test_finds_open_request_and_observe(self, monkeypatch) -> None:
        self._patch_registry(
            monkeypatch,
            {
                "mcp_provider:tool:mcp-browser-web-open": _FakeTool("mcp-browser-web-open"),
                "mcp_provider:tool:mcp-browser-web-request": _FakeTool("mcp-browser-web-request"),
                "mcp_provider:tool:mcp-browser-browser-observe": _FakeTool("mcp-browser-browser-observe"),
                "mcp_provider:tool:mcp-browser-web-close": _FakeTool("mcp-browser-web-close"),
                "mcp_provider:tool:mcp-system-run-command": _FakeTool("mcp-system-run-command"),
            },
        )

        tools = discover_browser_fetch_tools()

        assert tools is not None
        assert tools.open_signature == "mcp_provider:tool:mcp-browser-web-open"
        assert tools.request_signature == "mcp_provider:tool:mcp-browser-web-request"
        assert tools.observe_signature == "mcp_provider:tool:mcp-browser-browser-observe"
        assert tools.open_url_param == "url"
        assert tools.request_url_param == "url"

    def test_observe_optional(self, monkeypatch) -> None:
        self._patch_registry(
            monkeypatch,
            {
                "mcp_provider:tool:mcp-browser-web-open": _FakeTool("mcp-browser-web-open"),
                "mcp_provider:tool:mcp-browser-web-request": _FakeTool("mcp-browser-web-request"),
            },
        )
        tools = discover_browser_fetch_tools()
        assert tools is not None
        assert tools.observe_signature == ""

    def test_missing_request_tool_returns_none(self, monkeypatch) -> None:
        self._patch_registry(
            monkeypatch,
            {
                "mcp_provider:tool:mcp-browser-web-open": _FakeTool("mcp-browser-web-open"),
                "mcp_provider:tool:mcp-browser-browser-observe": _FakeTool("mcp-browser-browser-observe"),
            },
        )
        assert discover_browser_fetch_tools() is None

    def test_underscore_names_also_matched(self, monkeypatch) -> None:
        self._patch_registry(
            monkeypatch,
            {
                "mcp_provider:tool:mcp-browser-web_open": _FakeTool("mcp-browser-web_open"),
                "mcp_provider:tool:mcp-browser-web_request": _FakeTool("mcp-browser-web_request"),
            },
        )
        tools = discover_browser_fetch_tools()
        assert tools is not None


class TestResolveParams:
    def test_common_query_and_count_names(self) -> None:
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "query": {"type": "string"},
                        "search_depth": {"type": "string"},
                        "max_results": {"type": "integer"},
                    }
                }
            }
        }
        assert _resolve_params(schema) == ("query", "max_results")

    def test_alternative_names(self) -> None:
        schema = {
            "function": {
                "parameters": {
                    "properties": {
                        "q": {"type": "string"},
                        "count": {"type": "integer"},
                    }
                }
            }
        }
        assert _resolve_params(schema) == ("q", "count")

    def test_falls_back_to_any_string_param(self) -> None:
        schema = {
            "function": {"parameters": {"properties": {"question": {"type": "string"}, "depth": {"type": "string"}}}}
        }
        assert _resolve_params(schema) == ("question", None)

    def test_empty_schema_defaults(self) -> None:
        assert _resolve_params({}) == ("query", None)


_LONG_BODY = "汤面：" + "他每天都被闹钟叫醒。" * 30 + "\n汤底：" + "他靠闹钟确认安全。" * 30


class TestFetchViaBrowser:
    """两级抓取链测试：web-request 优先，失败走 web-open + observe。"""

    def _patch_browser_env(self, monkeypatch, execute_fake) -> list[str]:
        import src.app.plugin_system.api.tool_api as tool_api
        import json as _json

        registry = {
            "mcp_provider:tool:mcp-browser-web-open": _FakeTool("mcp-browser-web-open"),
            "mcp_provider:tool:mcp-browser-web-request": _FakeTool("mcp-browser-web-request"),
            "mcp_provider:tool:mcp-browser-browser-observe": _FakeTool("mcp-browser-browser-observe"),
        }
        monkeypatch.setattr(tool_api, "get_all_tools", lambda: registry)
        monkeypatch.setattr(tool_api, "get_tool_schema", lambda signature: _URL_SCHEMA)

        calls: list[str] = []

        async def fake_execute(signature, plugin=None, message=None, **kwargs):
            calls.append(signature)
            return await execute_fake(signature, kwargs)

        monkeypatch.setattr(tool_api, "execute_tool", fake_execute)
        return calls

    async def test_request_success_skips_navigation(self, monkeypatch) -> None:
        from ..mcp_search import MCPSearchExecutor

        async def fake(signature, kwargs):
            if signature.endswith("web-request"):
                return True, "[OK] HTTP 200\n\n<html>" + "x" * 600 + "</html>"
            raise AssertionError("不应调用其他工具")

        calls = self._patch_browser_env(monkeypatch, fake)
        executor = MCPSearchExecutor(plugin=object(), message=object())
        result = await executor.fetch_via_browser("https://example.com/a")
        assert result.startswith("[OK] HTTP 200")
        assert calls == ["mcp_provider:tool:mcp-browser-web-request"]

    async def test_falls_back_to_open_and_observe(self, monkeypatch) -> None:
        from ..mcp_search import MCPSearchExecutor

        async def fake(signature, kwargs):
            if signature.endswith("web-request"):
                return True, '{"success": false, "error_code": "auth_required"}'
            if signature.endswith("web-open"):
                return True, '{"success": true, "message": "已导航到"}'
            if signature.endswith("browser-observe"):
                import json as _json

                return True, _json.dumps(
                    {"success": True, "data": {"body_text": _LONG_BODY}}, ensure_ascii=False
                )
            raise AssertionError(f"意外调用: {signature}")

        calls = self._patch_browser_env(monkeypatch, fake)
        executor = MCPSearchExecutor(plugin=object(), message=object())
        result = await executor.fetch_via_browser("https://example.com/a")
        assert "汤面：" in result and "汤底：" in result
        assert calls == [
            "mcp_provider:tool:mcp-browser-web-request",
            "mcp_provider:tool:mcp-browser-web-open",
            "mcp_provider:tool:mcp-browser-browser-observe",
        ]

    async def test_open_failure_stops_chain(self, monkeypatch) -> None:
        from ..mcp_search import MCPSearchExecutor

        async def fake(signature, kwargs):
            if signature.endswith("web-request"):
                return True, '{"success": false, "error_code": "auth_required"}'
            if signature.endswith("web-open"):
                return True, '{"success": false, "error_code": "navigation_timeout"}'
            raise AssertionError(f"意外调用: {signature}")

        calls = self._patch_browser_env(monkeypatch, fake)
        executor = MCPSearchExecutor(plugin=object(), message=object())
        assert await executor.fetch_via_browser("https://example.com/a") == ""
        assert calls == [
            "mcp_provider:tool:mcp-browser-web-request",
            "mcp_provider:tool:mcp-browser-web-open",
        ]

    def test_extract_observed_body(self) -> None:
        from ..mcp_search import MCPSearchExecutor
        import json as _json

        ok = _json.dumps({"success": True, "data": {"body_text": _LONG_BODY}}, ensure_ascii=False)
        assert "汤面：" in MCPSearchExecutor._extract_observed_body(ok)
        assert MCPSearchExecutor._extract_observed_body("not json") == ""
        short = _json.dumps({"success": True, "data": {"body_text": "太短"}}, ensure_ascii=False)
        assert MCPSearchExecutor._extract_observed_body(short) == ""
