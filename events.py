"""海龟汤事件处理器。

``TurtleSoupIdleTimeoutHandler``：在每次 LLM 请求前检查该聊天流的
海龟汤游戏是否闲置超时，超时则结束本局并移除主持人 reminder，
防止玩家散场后汤底机密上下文残留在后续无关对话的模型请求里。

处理器必须快速返回且绝不抛异常——它在 LLM 请求热路径上。
"""

from __future__ import annotations

from typing import Any

from src.app.plugin_system.api.service_api import get_service
from src.app.plugin_system.base import BaseEventHandler
from src.core.components.types import EventType
from src.kernel.event import EventDecision
from src.kernel.logger import get_logger

logger = get_logger("turtle_soup")

_SERVICE_SIGNATURE = "turtle_soup:service:turtle_soup"


class TurtleSoupIdleTimeoutHandler(BaseEventHandler):
    """BEFORE_LLM_REQUEST 处理器：闲置超时自动结束海龟汤。"""

    name: str = "turtle_soup_idle_timeout"
    description: str = "在每次 LLM 请求前检查海龟汤游戏是否闲置超时，超时则结束本局并移除主持人 reminder"

    init_subscribe = [EventType.BEFORE_LLM_REQUEST]

    weight = 10

    async def execute(
        self, event_name: str, params: dict[str, Any]
    ) -> tuple[EventDecision, dict[str, Any]]:
        """检查该流的海龟汤是否闲置超时。"""

        try:
            meta_data = params.get("meta_data") or {}
            stream_id = str(meta_data.get("stream_id") or "")
            if not stream_id:
                return EventDecision.SUCCESS, params

            service = get_service(_SERVICE_SIGNATURE)
            if service is None:
                return EventDecision.SUCCESS, params
            service.expire_if_idle(stream_id)
        except Exception:
            # 过期检查失败绝不影响 LLM 请求
            logger.debug("海龟汤闲置超时检查异常", exc_info=True)
        return EventDecision.SUCCESS, params
