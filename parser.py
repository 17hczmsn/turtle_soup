"""海龟汤题库页面解析。"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Protocol

from .models import TurtleSoupPuzzle


def _clean_text(value: str) -> str:
    """清理字段文本。"""

    text = value.strip(" \t\n\r：:")
    text = re.sub(r"\n\s*", "\n", text)
    return text.strip()


class PageParserProto(Protocol):
    """单种页面格式的解析器协议。"""

    def parse(
        self, text: str, *, source_url: str, fetched_at: str
    ) -> list[TurtleSoupPuzzle]:
        """从已规范化的文本中解析题目。"""
        ...


class LabeledPageParser:
    """解析 ``汤面：…/汤底：…`` 标签对格式。"""

    _PAIR_PATTERN = re.compile(
        r"(?:(?:标题|题名|名称)[:：]?\s*(?P<title>[^\n\r]{0,80})?\s*)?"
        r"(?:汤面|题面|谜面|题目)[:：]\s*(?P<surface>.*?)"
        r"(?:汤底|答案|解析|真相|谜底)[:：]\s*(?P<answer>.*?)"
        r"(?=\n\s*(?:标题|题名|名称|汤面|题面|谜面|题目|汤底|答案|解析|真相|谜底)[:：]"
        r"|\n\s*\d{1,3}\s*[\.、．)）]"
        r"|\Z)",
        re.S,
    )
    _SURFACE_LABEL_PATTERN = re.compile(r"^(?:汤面|题面|谜面|题目)[:：]\s*")

    def parse(
        self, text: str, *, source_url: str, fetched_at: str
    ) -> list[TurtleSoupPuzzle]:
        """从标签对文本中解析题目。"""

        puzzles: list[TurtleSoupPuzzle] = []
        for match in self._PAIR_PATTERN.finditer(text):
            title = _clean_text(match.group("title") or "")
            surface = _clean_text(self._SURFACE_LABEL_PATTERN.sub("", match.group("surface")))
            answer = _clean_text(match.group("answer"))
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


class NumberedListParser:
    """解析 ``1、汤面内容 … 汤底：答案`` 编号列表格式。"""

    _ITEM_PATTERN = re.compile(
        r"(?:^|\n)\s*\d{1,3}\s*[\.、．)）]\s*"
        r"(?:(?P<title>【[^】\n]{1,40}】)\s*)?"
        r"(?P<surface>.*?)\s*"
        r"(?:汤底|答案|解析|真相|谜底)[:：]\s*(?P<answer>.*?)"
        r"(?=\n\s*\d{1,3}\s*[\.、．)）]"
        r"|\n\s*(?:标题|题名|名称|汤面|题面|谜面|题目|汤底|答案|解析|真相|谜底)[:：]"
        r"|\Z)",
        re.S,
    )
    _SURFACE_LABEL_PATTERN = re.compile(r"^(?:汤面|题面|谜面|题目)[:：]\s*")

    def parse(
        self, text: str, *, source_url: str, fetched_at: str
    ) -> list[TurtleSoupPuzzle]:
        """从编号列表文本中解析题目。"""

        puzzles: list[TurtleSoupPuzzle] = []
        for match in self._ITEM_PATTERN.finditer(text):
            raw_title = match.group("title") or ""
            title = _clean_text(raw_title).strip("【】")[:80]
            surface = _clean_text(self._SURFACE_LABEL_PATTERN.sub("", match.group("surface")))
            answer = _clean_text(match.group("answer"))
            if surface and answer:
                puzzles.append(
                    TurtleSoupPuzzle(
                        title=title or "海龟汤",
                        surface=surface,
                        answer=answer,
                        source="web",
                        source_url=source_url,
                        fetched_at=fetched_at,
                    )
                )
        return puzzles


class TurtleSoupPageParser:
    """从网页正文中解析汤面与汤底。

    内部按解析器链依次尝试多种页面格式，合并去重结果；
    新格式只需实现 :class:`PageParserProto` 并加入链中。
    """

    def __init__(self, parsers: list[PageParserProto] | None = None) -> None:
        """初始化解析器链。"""

        self._parsers: list[PageParserProto] = (
            parsers if parsers is not None else [LabeledPageParser(), NumberedListParser()]
        )

    def parse(self, content: str, source_url: str = "") -> list[TurtleSoupPuzzle]:
        """解析页面内容并返回去重后的题目列表。"""

        text = self._normalize(content)
        fetched_at = datetime.now(timezone.utc).isoformat()
        puzzles: list[TurtleSoupPuzzle] = []
        seen: set[tuple[str, str]] = set()
        for parser in self._parsers:
            for puzzle in parser.parse(text, source_url=source_url, fetched_at=fetched_at):
                key = (puzzle.surface.strip(), puzzle.answer.strip())
                if key in seen:
                    continue
                seen.add(key)
                puzzles.append(puzzle)
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
