"""海龟汤题库缓存。"""

from __future__ import annotations

import json
from pathlib import Path

from .models import TurtleSoupPuzzle


class TurtleSoupPuzzleCache:
    """JSON 文件题库缓存。"""

    def __init__(self, cache_path: str) -> None:
        """初始化缓存。"""

        self.cache_path = Path(cache_path)

    def load(self) -> list[TurtleSoupPuzzle]:
        """读取缓存题库。"""

        if not self.cache_path.exists():
            return []
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(raw, list):
            return []
        puzzles: list[TurtleSoupPuzzle] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                puzzles.append(TurtleSoupPuzzle.from_dict(item))
            except (TypeError, ValueError):
                continue
        return puzzles

    def save(self, puzzles: list[TurtleSoupPuzzle]) -> None:
        """写入缓存题库。"""

        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [puzzle.to_dict() for puzzle in puzzles]
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def append_unique(self, puzzles: list[TurtleSoupPuzzle]) -> list[TurtleSoupPuzzle]:
        """追加去重后的题目并返回完整缓存。"""

        current = self.load()
        seen = {(item.surface.strip(), item.answer.strip()) for item in current}
        for puzzle in puzzles:
            key = (puzzle.surface.strip(), puzzle.answer.strip())
            if key not in seen:
                current.append(puzzle)
                seen.add(key)
        self.save(current)
        return current
