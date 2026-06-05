"""海龟汤网页抓取。"""

from __future__ import annotations

import asyncio
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TurtleSoupPageFetcher:
    """使用标准库抓取题库页面。"""

    def __init__(self, timeout_seconds: float, max_page_bytes: int) -> None:
        """初始化抓取器。"""

        self.timeout_seconds = timeout_seconds
        self.max_page_bytes = max_page_bytes

    async def fetch_text(self, url: str) -> str:
        """异步抓取网页文本。"""

        return await asyncio.to_thread(self._fetch_text_sync, url)

    def _fetch_text_sync(self, url: str) -> str:
        """同步抓取网页文本。"""

        request = Request(url, headers={"User-Agent": "Neo-MoFox TurtleSoup/1.0"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                data = response.read(self.max_page_bytes + 1)
        except (HTTPError, URLError, TimeoutError, OSError):
            return ""
        if len(data) > self.max_page_bytes:
            data = data[: self.max_page_bytes]
        return data.decode("utf-8", errors="ignore")
