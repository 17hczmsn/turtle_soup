"""海龟汤状态仓库。"""

from __future__ import annotations

from .models import TurtleSoupState


class TurtleSoupStateStore:
    """内存态海龟汤状态仓库。"""

    def __init__(self) -> None:
        """初始化状态仓库。"""

        self._states: dict[str, TurtleSoupState] = {}

    def get_or_create(self, stream_key: str) -> TurtleSoupState:
        """获取或创建指定会话状态。"""

        state = self._states.get(stream_key)
        if state is None:
            state = TurtleSoupState(stream_key=stream_key)
            self._states[stream_key] = state
        return state

    def get(self, stream_key: str) -> TurtleSoupState | None:
        """获取指定会话状态。"""

        return self._states.get(stream_key)

    def set(self, state: TurtleSoupState) -> None:
        """保存指定会话状态。"""

        self._states[state.stream_key] = state

    def clear(self, stream_key: str) -> None:
        """清除指定会话状态。"""

        self._states.pop(stream_key, None)


state_store = TurtleSoupStateStore()
