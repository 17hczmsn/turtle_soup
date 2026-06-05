"""海龟汤插件入口。"""

from __future__ import annotations

from src.app.plugin_system.base import BasePlugin, register_plugin

from .actions import (
    AskTurtleSoupQuestionAction,
    ExitTurtleSoupGameAction,
    GuessTurtleSoupAnswerAction,
    RequestTurtleSoupHintAction,
    RevealTurtleSoupAnswerAction,
    StartTurtleSoupGameAction,
    SummarizeTurtleSoupCluesAction,
)
from .config import TurtleSoupConfig
from .service import TurtleSoupService
from .tools import GetTurtleSoupQuestionTool, GetTurtleSoupStateTool


@register_plugin
class TurtleSoupPlugin(BasePlugin):
    """自然语言海龟汤游戏插件。"""

    plugin_name: str = "turtle_soup"
    enable_plugin: bool = True
    dependencies: list[str] = []
    python_dependencies: list[str] = []
    configs: list[type] = [TurtleSoupConfig]

    def get_components(self) -> list[type]:
        """返回插件组件列表。"""

        return [
            TurtleSoupService,
            StartTurtleSoupGameAction,
            AskTurtleSoupQuestionAction,
            RequestTurtleSoupHintAction,
            SummarizeTurtleSoupCluesAction,
            GuessTurtleSoupAnswerAction,
            RevealTurtleSoupAnswerAction,
            ExitTurtleSoupGameAction,
            GetTurtleSoupStateTool,
            GetTurtleSoupQuestionTool,
        ]
