"""海龟汤题库页面解析。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone

from .models import TurtleSoupPuzzle


class TurtleSoupPageParser:
    """从网页正文中解析汤面与汤底。"""

    _PAIR_PATTERN = re.compile(
        r"(?:标题|题名|名称)[:：]?\s*(?P<title>[^\n\r]{0,80})?\s*"
        r"(?:汤面|题面|谜面|题目)[:：]\s*(?P<surface>.*?)"
        r"(?:汤底|答案|解析|真相)[:：]\s*(?P<answer>.*?)(?=\n\s*(?:标题|题名|名称|汤面|题面|谜面|题目)[:：]|\Z)",
        re.S,
    )

    def parse(self, content: str, source_url: str = "") -> list[TurtleSoupPuzzle]:
        """解析页面内容并返回题目列表。"""

        text = self._normalize(content)
        puzzles: list[TurtleSoupPuzzle] = []
        fetched_at = datetime.now(timezone.utc).isoformat()
        for match in self._PAIR_PATTERN.finditer(text):
            title = self._clean(match.group("title") or "海龟汤")
            surface = self._clean(match.group("surface"))
            answer = self._clean(match.group("answer"))
            if surface and answer:
                puzzles.append(
                    TurtleSoupPuzzle(
                        title=title[:80] or "海龟汤",
                        surface=surface,
                        answer=answer,
                        source="web",
                        source_url=source_url,
                        fetched_at=fetched_at,
                    )
                )
        return puzzles

    def _normalize(self, content: str) -> str:
        """将 HTML 或纯文本规范化为可解析文本。"""

        text = html.unescape(content)
        text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
        text = re.sub(r"</\s*(?:p|div|li|h\d|tr)\s*>", "\n", text, flags=re.I)
        text = re.sub(r"<script\b.*?</script>", "", text, flags=re.I | re.S)
        text = re.sub(r"<style\b.*?</style>", "", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("\r", "\n")
        text = re.sub(r"[ \t\u3000]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _clean(self, value: str) -> str:
        """清理字段文本。"""

        text = value.strip(" \t\n\r：:")
        text = re.sub(r"\n\s*", "\n", text)
        return text.strip()
