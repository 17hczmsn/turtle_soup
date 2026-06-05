"""海龟汤题目搜索。"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse


class TurtleSoupSearchClient:
    """构造并解析候选题库页面。"""

    def __init__(self, fixed_urls: list[str], allowed_domains: list[str], enable_web_search: bool = True) -> None:
        """初始化搜索客户端。"""

        self.fixed_urls = fixed_urls
        self.allowed_domains = [domain.lower() for domain in allowed_domains if domain]
        self.enable_web_search = enable_web_search

    async def search(self, query: str, max_results: int) -> list[str]:
        """返回候选题库 URL 或搜索结果页 URL。"""

        urls = list(dict.fromkeys(url for url in self.fixed_urls if url))
        if self.enable_web_search and len(urls) < max_results:
            escaped_query = quote_plus(query)
            urls.extend(
                [
                    f"https://www.bing.com/search?q={escaped_query}",
                    f"https://www.baidu.com/s?wd={escaped_query}",
                ]
            )
        return urls[:max_results]

    def extract_result_urls(self, search_page_url: str, content: str, max_results: int) -> list[str]:
        """从搜索页或普通网页中提取候选结果链接。"""

        urls: list[str] = []
        for raw_url in re.findall(r"href=[\"']([^\"'#]+)[\"']", content, flags=re.I):
            resolved = self._resolve_url(search_page_url, html.unescape(raw_url))
            if resolved and self._is_allowed_result_url(resolved):
                urls.append(resolved)
        return list(dict.fromkeys(urls))[:max_results]

    def _resolve_url(self, base_url: str, raw_url: str) -> str:
        """解析搜索结果链接。"""

        url = raw_url.strip()
        if not url or url.startswith(("javascript:", "mailto:")):
            return ""
        if url.startswith("/link?") or url.startswith("/url?"):
            query = parse_qs(urlparse(url).query)
            target = query.get("url") or query.get("u") or query.get("wd")
            if target:
                url = target[0]
        if url.startswith("http://") or url.startswith("https://"):
            return unquote(url)
        return urljoin(base_url, url)

    def _is_allowed_result_url(self, url: str) -> bool:
        """判断链接是否可作为题库候选页。"""

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.hostname.lower() if parsed.hostname else ""
        if host in {"www.baidu.com", "www.bing.com", "cn.bing.com"}:
            return False
        if not self.allowed_domains:
            return True
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

