"""海龟汤 Tool 组件。"""

from __future__ import annotations

from typing import cast

from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseTool

from ..service import TurtleSoupService


_SERVICE_SIGNATURE = "turtle_soup:service:turtle_soup"


def _get_service() -> TurtleSoupService | None:
    """获取海龟汤服务。"""

    service = get_service(_SERVICE_SIGNATURE)
    if service is None:
        return None
    return cast(TurtleSoupService, service)


class GetTurtleSoupStateTool(BaseTool):
    """获取海龟汤公开状态。"""

    tool_name: str = "get_turtle_soup_state"
    tool_description: str = "只读查询当前会话海龟汤游戏状态，不包含汤底。"

    async def execute(self, stream_key: str) -> tuple[bool, str | dict[str, object]]:
        """执行状态查询。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        return True, service.get_state(stream_key)


class GetTurtleSoupQuestionTool(BaseTool):
    """获取当前海龟汤汤面。"""

    tool_name: str = "get_turtle_soup_question"
    tool_description: str = "只读查询当前会话海龟汤汤面，不包含汤底。"

    async def execute(self, stream_key: str) -> tuple[bool, str | dict[str, object]]:
        """执行汤面查询。"""

        service = _get_service()
        if service is None:
            return False, "turtle_soup service 未加载"
        ok, question = service.get_question(stream_key)
        return ok, question
