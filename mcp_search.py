"""MCP 网络搜索工具的自动发现与调用。

不同用户接入的 MCP 服务器各不相同，本模块在补库时按名称/描述信号
自动挑选"网络搜索"类 MCP 工具，并依据其参数 schema 适配调用参数：
查询参数依次尝试 query/q/keywords 等常见命名，数量参数同理。

没有专用搜索工具时，回退使用浏览器类 MCP（web-open + web-request）：
先打开搜索引擎首页建立浏览器会话，再直接请求搜索结果页，
把返回的原始 HTML 交给调用方做链接提取与题库解析。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote_plus

from src.kernel.logger import get_logger

if TYPE_CHECKING:
    from src.core.components.base.plugin import BasePlugin
    from src.core.models.message import Message

logger = get_logger("turtle_soup")

_MCP_SIGNATURE_PREFIX = "mcp_provider:tool:"

# 工具名中的搜索信号
_SEARCH_NAME_SIGNALS = ("search", "搜索", "检索")
# 名称或描述中的网络信号（含常见搜索服务品牌名）
_WEB_SIGNALS = (
    "web",
    "internet",
    "online",
    "网络",
    "互联网",
    "在线",
    "网页",
    "搜索引擎",
    "tavily",
    "brave",
    "exa",
    "serper",
    "serpapi",
    "duckduckgo",
    "searxng",
    "metaso",
    "bing",
    "google",
    "baidu",
    "sogou",
)
# 明显与网络搜索无关的负向信号，命中即排除
_NEGATIVE_SIGNALS = (
    "file",
    "filesystem",
    "folder",
    "directory",
    "目录",
    "本地",
    "local",
    "code",
    "代码",
    "repo",
    "仓库",
    "image",
    "图片",
    "video",
    "视频",
    "audio",
    "音频",
    "music",
    "音乐",
    "database",
    "数据库",
    "memory",
    "记忆",
)

# 常见查询参数命名，按优先级排列
_QUERY_PARAM_CANDIDATES = (
    "query",
    "q",
    "keywords",
    "keyword",
    "search_query",
    "search",
    "input",
    "question",
    "关键词",
)
# 常见结果数量参数命名，按优先级排列
_COUNT_PARAM_CANDIDATES = (
    "max_results",
    "count",
    "num",
    "limit",
    "top_k",
    "max_result",
)

_PREFERRED_SCORE = 10_000


@dataclass(frozen=True, slots=True)
class ResolvedSearchTool:
    """一个可调用的 MCP 搜索工具。"""

    signature: str
    query_param: str
    count_param: str | None


@dataclass(frozen=True, slots=True)
class BrowserFetchTools:
    """浏览器类 MCP 的页面打开、请求与观察工具。"""

    open_signature: str
    open_url_param: str
    request_signature: str
    request_url_param: str
    observe_signature: str = ""


def score_search_tool(tool_name: str, description: str) -> int:
    """按名称与描述信号给候选工具打分，0 表示不适合做网络搜索。

    要求同时具备"搜索"信号与"网络"信号；负向信号（文件/数据库/视频等）
    只对工具名生效——描述里常含使用示例（如"如何解决数据库连接问题"），
    不能因为示例提到无关领域就排除整个工具。
    """

    name_lower = tool_name.lower()
    desc_lower = description.lower()
    combined = f"{name_lower} {desc_lower}"

    if any(signal in name_lower for signal in _NEGATIVE_SIGNALS):
        return 0

    name_search = any(signal in name_lower for signal in _SEARCH_NAME_SIGNALS)
    desc_search = any(signal in desc_lower for signal in _SEARCH_NAME_SIGNALS)
    if not (name_search or desc_search):
        return 0
    if not any(signal in combined for signal in _WEB_SIGNALS):
        return 0

    score = 50 if name_search else 20
    if any(signal in name_lower for signal in _WEB_SIGNALS):
        score += 30
    return score


def _resolve_params(schema: dict[str, Any]) -> tuple[str, str | None]:
    """从 Tool schema 中解析查询与数量参数名。"""

    function = schema.get("function", {}) if isinstance(schema, dict) else {}
    parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    if not isinstance(properties, dict):
        properties = {}

    query_param = next((name for name in _QUERY_PARAM_CANDIDATES if name in properties), None)
    if query_param is None:
        query_param = next(
            (
                name
                for name, spec in properties.items()
                if isinstance(spec, dict) and spec.get("type") == "string"
            ),
            "query",
        )

    count_param = next((name for name in _COUNT_PARAM_CANDIDATES if name in properties), None)
    return query_param, count_param


def _resolve_url_param(schema: dict[str, Any]) -> str | None:
    """从 Tool schema 中解析 URL 参数名，找不到返回 None。"""

    function = schema.get("function", {}) if isinstance(schema, dict) else {}
    parameters = function.get("parameters", {}) if isinstance(function, dict) else {}
    properties = parameters.get("properties", {}) if isinstance(parameters, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    if "url" in properties:
        return "url"
    return next(
        (
            name
            for name, spec in properties.items()
            if isinstance(spec, dict) and spec.get("type") == "string"
        ),
        None,
    )


def _iter_mcp_tools() -> list[tuple[str, str, str]]:
    """枚举注册表中的 MCP 工具，返回 (签名, 名称, 描述) 列表。"""

    from src.app.plugin_system.api.tool_api import get_all_tools

    result: list[tuple[str, str, str]] = []
    for signature, tool_cls in get_all_tools().items():
        if not signature.startswith(_MCP_SIGNATURE_PREFIX):
            continue
        tool_name = str(getattr(tool_cls, "name", "") or signature.rsplit(":", 1)[-1])
        description = " ".join(
            part
            for part in (
                str(getattr(tool_cls, "description", "") or ""),
                str(getattr(tool_cls, "tool_description", "") or ""),
            )
            if part
        )
        result.append((signature, tool_name, description))
    return result


def _is_browser_open_name(name_lower: str) -> bool:
    """判断工具名是否像"打开网页"类浏览器工具。"""

    return "web" in name_lower and "open" in name_lower


def _is_browser_request_name(name_lower: str) -> bool:
    """判断工具名是否像"请求网页"类浏览器工具。"""

    return "web" in name_lower and ("request" in name_lower or "fetch" in name_lower)


def _is_browser_observe_name(name_lower: str) -> bool:
    """判断工具名是否像"观察页面"类浏览器工具。"""

    return "observe" in name_lower or "snapshot" in name_lower


def discover_browser_fetch_tools() -> BrowserFetchTools | None:
    """发现浏览器类 MCP 的 web-open / web-request（及可选 observe）工具。

    web-open 与 web-request 两件齐全才可用：web-request 依赖已打开的
    浏览器会话。browser-observe 为可选增强，用于真实导航后读取正文。
    """

    from src.app.plugin_system.api.tool_api import get_tool_schema

    open_tool: tuple[str, str] | None = None
    request_tool: tuple[str, str] | None = None
    observe_signature = ""
    for signature, tool_name, _description in _iter_mcp_tools():
        name_lower = tool_name.lower()
        if not observe_signature and _is_browser_observe_name(name_lower):
            observe_signature = signature
            continue
        url_param = _resolve_url_param(get_tool_schema(signature) or {})
        if url_param is None:
            continue
        if open_tool is None and _is_browser_open_name(name_lower):
            open_tool = (signature, url_param)
        elif request_tool is None and _is_browser_request_name(name_lower):
            request_tool = (signature, url_param)

    if open_tool is None or request_tool is None:
        return None
    return BrowserFetchTools(
        open_signature=open_tool[0],
        open_url_param=open_tool[1],
        request_signature=request_tool[0],
        request_url_param=request_tool[1],
        observe_signature=observe_signature,
    )


def build_search_urls(query: str) -> list[str]:
    """按优先级构造搜索引擎结果页 URL。"""

    escaped = quote_plus(query)
    return [
        f"https://www.bing.com/search?q={escaped}",
        f"https://www.baidu.com/s?wd={escaped}",
    ]


def _looks_successful(text: str) -> bool:
    """判断浏览器 MCP 返回文本是否为成功结果。

    成功形态是 ``[OK] HTTP ...`` 前缀的原始内容；失败形态是
    ``{"success": false, ...}`` 的 JSON 文本。
    """

    stripped = str(text or "").strip()
    if not stripped:
        return False
    if stripped.startswith("[OK]"):
        return True
    compact = stripped.replace(" ", "")
    if '"success":false' in compact:
        return False
    return '"success":true' in compact or not stripped.startswith("{")


def discover_search_tools(
    preferred_signature: str = "",
    limit: int = 3,
) -> list[ResolvedSearchTool]:
    """发现当前注册表中可用的 MCP 网络搜索工具，按得分降序返回。

    Args:
        preferred_signature: 用户显式指定的工具签名，存在时排在首位。
        limit: 最多返回的候选数量。
    """

    from src.app.plugin_system.api.tool_api import get_tool_schema

    scored: list[tuple[int, str]] = []
    for signature, tool_name, description in _iter_mcp_tools():
        if preferred_signature and signature == preferred_signature:
            score = _PREFERRED_SCORE
        else:
            score = score_search_tool(tool_name, description)
        if score > 0:
            scored.append((score, signature))

    scored.sort(key=lambda item: (-item[0], item[1]))

    resolved: list[ResolvedSearchTool] = []
    for _, signature in scored[:limit]:
        query_param, count_param = _resolve_params(get_tool_schema(signature) or {})
        resolved.append(
            ResolvedSearchTool(
                signature=signature,
                query_param=query_param,
                count_param=count_param,
            )
        )
    return resolved


class MCPSearchExecutor:
    """调用 MCP 网络搜索工具，失败时自动尝试下一候选。

    没有专用搜索工具时，可再调用 :meth:`search_via_browser`
    走浏览器类 MCP 的搜索页抓取回退。
    """

    def __init__(
        self,
        plugin: "BasePlugin",
        message: "Message",
        preferred_signature: str = "",
        max_attempts: int = 3,
    ) -> None:
        """初始化执行器。"""

        self.plugin = plugin
        self.message = message
        self.preferred_signature = preferred_signature
        self.max_attempts = max_attempts

    async def search(self, query: str) -> str:
        """执行搜索并返回文本结果，全部失败时返回空字符串。"""

        from src.app.plugin_system.api.tool_api import execute_tool

        tools = discover_search_tools(self.preferred_signature, self.max_attempts)
        if not tools:
            logger.info(
                "未发现专用搜索类 MCP 工具"
                + (f"（指定签名 {self.preferred_signature} 未注册）" if self.preferred_signature else "")
                + "，将尝试浏览器搜索回退"
            )
        for tool in tools:
            kwargs: dict[str, Any] = {tool.query_param: query}
            if tool.count_param:
                kwargs[tool.count_param] = 10
            try:
                success, result = await execute_tool(
                    tool.signature,
                    plugin=self.plugin,
                    message=self.message,
                    **kwargs,
                )
            except Exception:
                logger.warning(f"MCP 搜索工具 {tool.signature} 调用异常", exc_info=True)
                continue
            if success and isinstance(result, str) and result.strip():
                logger.info(f"MCP 搜索工具 {tool.signature} 调用成功")
                return result
            logger.warning(
                f"MCP 搜索工具 {tool.signature} 返回空结果（success={success}），尝试下一候选"
            )
        return ""

    async def search_via_browser(self, query: str) -> list[tuple[str, str]]:
        """浏览器类 MCP 搜索回退，返回每个引擎的 (搜索页 HTML, 搜索页 URL) 列表。

        流程：web-open 打开搜索引擎首页建立浏览器会话，再用
        web-request 依次请求各引擎搜索结果页拿原始 HTML。
        浏览器不可用（无工具或打开失败）时返回空列表。
        """

        from src.app.plugin_system.api.tool_api import execute_tool

        tools = discover_browser_fetch_tools()
        if tools is None:
            logger.info("未发现浏览器类 MCP 工具（web-open / web-request），跳过浏览器搜索回退")
            return []

        try:
            success, result = await execute_tool(
                tools.open_signature,
                plugin=self.plugin,
                message=self.message,
                **{tools.open_url_param: "https://www.bing.com"},
            )
        except Exception:
            logger.warning("浏览器 MCP 打开异常", exc_info=True)
            return []
        if not success or not _looks_successful(str(result or "")):
            logger.warning(f"浏览器 MCP 打开失败：{str(result)[:120]}")
            return []

        pages: list[tuple[str, str]] = []
        for search_url in build_search_urls(query):
            try:
                success, result = await execute_tool(
                    tools.request_signature,
                    plugin=self.plugin,
                    message=self.message,
                    **{tools.request_url_param: search_url},
                )
            except Exception:
                logger.warning(f"浏览器 MCP 抓取搜索页异常：{search_url}", exc_info=True)
                continue
            text = str(result or "")
            if success and _looks_successful(text) and len(text.strip()) > 500:
                logger.info(f"浏览器 MCP 搜索抓取成功：{search_url}")
                pages.append((text, search_url))
            else:
                logger.warning(f"浏览器 MCP 抓取搜索页未获得有效内容：{search_url}")
        return pages

    async def fetch_via_browser(self, url: str) -> str:
        """用浏览器抓取指定页面内容，失败返回空字符串。

        两级链路：
        1. ``web-request`` 复用已打开会话直接请求（快，但可能被反爬拦截）；
        2. 失败时 ``web-open`` 真实导航（执行 JS、完整浏览器指纹），
           再用 ``browser-observe`` 读取页面可见正文。
        """

        from src.app.plugin_system.api.tool_api import execute_tool

        tools = discover_browser_fetch_tools()
        if tools is None:
            return ""

        try:
            success, result = await execute_tool(
                tools.request_signature,
                plugin=self.plugin,
                message=self.message,
                **{tools.request_url_param: url},
            )
        except Exception:
            logger.debug(f"浏览器 web-request 抓取异常：{url}", exc_info=True)
            success, result = False, ""

        text = str(result or "")
        if success and _looks_successful(text) and len(text.strip()) > 500:
            return text
        logger.warning(
            f"浏览器 web-request 抓取未成功：{url} → 响应片段：{text[:120]!r}（success={success}），尝试真实导航"
        )

        # 真实导航：完整浏览器加载，随后读取可见正文
        try:
            success, result = await execute_tool(
                tools.open_signature,
                plugin=self.plugin,
                message=self.message,
                **{tools.open_url_param: url},
            )
        except Exception:
            logger.debug(f"浏览器 web-open 导航异常：{url}", exc_info=True)
            return ""
        open_text = str(result or "")
        if not success or not _looks_successful(open_text):
            logger.warning(f"浏览器 web-open 导航失败：{url} → 响应片段：{open_text[:120]!r}")
            return ""
        if not tools.observe_signature:
            logger.info(f"浏览器已导航到 {url}，但无 browser-observe 工具可读取正文")
            return ""

        try:
            success, result = await execute_tool(
                tools.observe_signature,
                plugin=self.plugin,
                message=self.message,
            )
        except Exception:
            logger.debug(f"browser-observe 读取正文异常：{url}", exc_info=True)
            return ""
        body_text = self._extract_observed_body(str(result or ""))
        if body_text:
            return body_text
        logger.warning(f"browser-observe 未读取到正文：{url} → 响应片段：{str(result or '')[:120]!r}")
        return ""

    @staticmethod
    def _extract_observed_body(observe_result: str) -> str:
        """从 browser-observe 的 JSON 响应中提取页面可见正文。"""

        import json as _json

        try:
            payload = _json.loads(observe_result)
        except (ValueError, TypeError):
            return ""
        data = payload.get("data") if isinstance(payload, dict) else None
        body_text = str((data or {}).get("body_text") or "")
        return body_text if len(body_text.strip()) > 200 else ""
