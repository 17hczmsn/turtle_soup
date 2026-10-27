"""海龟汤领域模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import monotonic
from typing import Literal


HistoryType = Literal["question", "guess", "hint", "clues", "reveal"]


@dataclass(slots=True)
class TurtleSoupPuzzle:
    """完整海龟汤题目。"""

    title: str
    surface: str
    answer: str
    difficulty: str | None = None
    source: str = "unknown"
    source_url: str = ""
    puzzle_id: str = ""
    fetched_at: str = ""
    used_count: int = 0

    def to_dict(self) -> dict[str, object]:
        """转换为可 JSON 序列化的字典。"""

        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "TurtleSoupPuzzle":
        """从字典构造题目。"""

        return cls(
            title=str(data.get("title") or "海龟汤"),
            surface=str(data.get("surface") or ""),
            answer=str(data.get("answer") or ""),
            difficulty=str(data.get("difficulty") or "") or None,
            source=str(data.get("source") or "unknown"),
            source_url=str(data.get("source_url") or ""),
            puzzle_id=str(data.get("id") or data.get("puzzle_id") or ""),
            fetched_at=str(data.get("fetched_at") or ""),
            used_count=int(data.get("used_count") or 0),
        )


@dataclass(slots=True)
class TurtleSoupHistoryItem:
    """海龟汤交互历史项。"""

    item_type: HistoryType
    content: str
    response: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, str]:
        """转换为可 JSON 序列化的字典。"""

        return asdict(self)


@dataclass(slots=True)
class TurtleSoupState:
    """单个会话的海龟汤游戏状态。"""

    stream_key: str
    current_question: str = ""
    current_answer: str = ""
    title: str = "海龟汤"
    source_url: str = ""
    hints_used: int = 0
    game_active: bool = False
    game_over: bool = False
    history: list[TurtleSoupHistoryItem] = field(default_factory=list)
    # 最近一次游戏交互的单调时间戳，用于闲置超时判定
    last_activity: float = field(default_factory=monotonic)

    def touch(self) -> None:
        """刷新最近交互时间。"""

        self.last_activity = monotonic()

    def is_idle_expired(self, timeout_minutes: int) -> bool:
        """判断是否超过闲置时长（0 或负值表示不启用超时）。"""

        if timeout_minutes <= 0:
            return False
        return (monotonic() - self.last_activity) >= timeout_minutes * 60

    def add_history(self, item: TurtleSoupHistoryItem, max_items: int) -> None:
        """追加历史并按上限裁剪。"""

        self.history.append(item)
        if max_items > 0 and len(self.history) > max_items:
            self.history = self.history[-max_items:]

    def to_public_dict(self) -> dict[str, object]:
        """返回不包含汤底的公开状态。"""

        return {
            "title": self.title,
            "surface": self.current_question,
            "hints_used": self.hints_used,
            "game_active": self.game_active,
            "game_over": self.game_over,
            "source_url": self.source_url,
            "history_count": len(self.history),
        }
