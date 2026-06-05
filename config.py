"""海龟汤插件配置。"""

from __future__ import annotations

from typing import ClassVar

from src.app.plugin_system.base import BaseConfig, Field, SectionBase, config_section


class TurtleSoupConfig(BaseConfig):
    """海龟汤插件配置。"""

    config_name: ClassVar[str] = "config"
    config_description: ClassVar[str] = "海龟汤自然语言游戏插件配置"

    @config_section("plugin")
    class PluginSection(SectionBase):
        """插件启用配置。"""

        enabled: bool = Field(default=True, description="是否启用海龟汤插件")

    @config_section("game")
    class GameSection(SectionBase):
        """游戏规则配置。"""

        max_hints: int = Field(default=3, description="每局最多提示次数")
        max_history_items: int = Field(default=30, description="最多保留的历史交互条数")

    @config_section("puzzle")
    class PuzzleSection(SectionBase):
        """汤题来源配置。"""

        min_cache_items: int = Field(default=100, description="缓存低于该数量时尝试补充题库")
        max_fetch_pages: int = Field(default=20, description="单次补库最多拉取题库页面数")
        max_search_pages: int = Field(default=5, description="单次补库最多拉取搜索结果页数")
        cache_path: str = Field(default="data/turtle_soup/puzzle_cache.json", description="题库缓存文件路径")
        fallback_bank_path: str = Field(default="plugins/turtle_soup/puzzles.json", description="本地兜底题库路径")
        search_query: str = Field(default="海龟汤 汤面 汤底 题库", description="网络题库搜索关键词")
        search_urls: list[str] = Field(default_factory=list, description="固定候选题库页面 URL 列表")
        enable_web_search: bool = Field(default=True, description="是否自动通过搜索引擎搜索公开题库")
        allowed_domains: list[str] = Field(
            default_factory=lambda: [
                "zhihu.com",
                "bilibili.com",
                "douban.com",
                "jianshu.com",
                "lofter.com",
                "weibo.com",
                "baidu.com",
                "bing.com",
            ],
            description="允许访问的题库域名白名单",
        )
        request_timeout_seconds: float = Field(default=10.0, description="网页请求超时时间")
        max_page_bytes: int = Field(default=1_000_000, description="单页最大读取字节数")

    @config_section("llm")
    class LLMSection(SectionBase):
        """LLM 互动配置。"""

        model_task: str = Field(default="utils_small", description="用于问答、提示、判断的模型任务名")
        temperature: float = Field(default=0.3, description="互动判断生成温度")
        max_tokens: int = Field(default=500, description="单次最大输出 token 数")

    plugin: PluginSection = Field(default_factory=PluginSection)
    game: GameSection = Field(default_factory=GameSection)
    puzzle: PuzzleSection = Field(default_factory=PuzzleSection)
    llm: LLMSection = Field(default_factory=LLMSection)
