"""海龟汤题目校验。"""

from __future__ import annotations

from urllib.parse import urlparse

from .models import TurtleSoupPuzzle


class TurtleSoupPuzzleValidator:
    """校验题目完整性与来源。"""

    def __init__(self, allowed_domains: list[str]) -> None:
        """初始化校验器。"""

        self.allowed_domains = [domain.lower() for domain in allowed_domains if domain]

    def is_url_allowed(self, url: str) -> bool:
        """判断 URL 是否在允许域名内。"""

        if not self.allowed_domains:
            return False
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        host = parsed.hostname.lower() if parsed.hostname else ""
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

    def is_valid(self, puzzle: TurtleSoupPuzzle) -> bool:
        """判断题目是否可用于开局。"""

        surface = puzzle.surface.strip()
        answer = puzzle.answer.strip()
        if len(surface) < 10 or len(answer) < 10:
            return False
        if surface == answer:
            return False
        return True
