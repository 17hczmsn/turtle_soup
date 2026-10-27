"""海龟汤网页抓取。"""

from __future__ import annotations

import asyncio
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


class TurtleSoupPageFetcher:
    """使用标准库抓取题库页面。"""

    def __init__(self, timeout_seconds: float, max_page_bytes: int) -> None:
        """初始化抓取器。"""

        self.timeout_seconds = timeout_seconds
        self.max_page_bytes = max_page_bytes

    async def fetch_text(self, url: str) -> str:
        """异步抓取网页文本，任何失败都返回空字符串。"""

        return await asyncio.to_thread(self._fetch_text_sync, url)

    def _fetch_text_sync(self, url: str) -> str:
        """同步抓取网页文本。"""

        normalized = self._normalize_url(url)
        if not normalized:
            return ""
        request = Request(normalized, headers={"User-Agent": "Neo-MoFox TurtleSoup/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read(self.max_page_bytes + 1)
        # ValueError 覆盖 UnicodeEncodeError 等非法 URL 情况，避免异常穿透到开局链路
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            return ""
        if len(data) > self.max_page_bytes:
            data = data[: self.max_page_bytes]
        return data.decode("utf-8", errors="ignore")

    @staticmethod
    def _normalize_url(url: str) -> str:
        """把 URL 中未编码的非 ASCII 字符重新百分号编码。

        已是合法编码（%xx）的部分保持不变；无协议的输入视为非法返回空串。
        """

        try:
            parts = urlsplit(url.strip())
        except ValueError:
            return ""
        if not parts.scheme or not parts.netloc:
            return ""
        try:
            path = quote(parts.path, safe="/%")
            query = quote(parts.query, safe="=&%+?")
            return urlunsplit((parts.scheme.lower(), parts.netloc, path, query, parts.fragment))
        except ValueError:
            return ""
