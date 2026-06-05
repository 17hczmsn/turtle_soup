# turtle_soup

一个“海龟汤互动游戏”插件：

- 支持在群聊或私聊中自然语言开局，例如“来一局海龟汤”“换一个汤”
- 自动获取完整汤题，包含汤面与汤底：
  - 优先使用 `data/turtle_soup/puzzle_cache.json` 缓存题库
  - 缓存不足时可从公开网页题库补充
  - 网络不可用或无可用新题时使用 `plugins/turtle_soup/puzzles.json` 本地兜底题库
- 维护每个聊天流独立的游戏状态，记录当前汤面、提示次数、公开问答历史与游戏结束状态
- 支持玩家围绕汤面提问，由 LLM 根据汤底判断并给出符合海龟汤规则的回答
- 支持请求提示、整理线索、猜测汤底、公布答案、退出当前游戏
- 对外暴露只读工具，方便其他组件查询当前游戏状态或重新获取汤面

## 主要功能

### 开始一局

当用户表达想玩海龟汤时触发 `start_turtle_soup_game`。

插件会抽取一条题目并返回结构化开局事实，后续由聊天核心按当前角色语气发出汤面。汤面要求完整保留，不会在开局时泄露汤底。

### 玩家提问

当游戏进行中，用户提出是/否类问题或调查细节时触发 `ask_turtle_soup_question`。

插件会把当前汤面、汤底与历史问答交给指定模型判断，返回标准事实答案。聊天核心可以调整语气，但不能擅自改写答案、扩写未确认事实或透露汤底。

### 请求提示

当用户想要提示、线索或方向时触发 `request_turtle_soup_hint`。

提示次数由配置项 `game.max_hints` 控制，默认每局最多 3 次。提示只基于当前汤题生成，不应额外引入新事实。

### 整理线索

当用户要求“复盘”“整理线索”“总结已知信息”时触发 `summarize_turtle_soup_clues`。

插件会返回当前公开汤面、已公开问答、提示使用次数等信息，方便继续推理，同时不会把汤底混入公开线索。

### 猜测汤底

当用户明确给出真相、答案或汤底猜测时触发 `guess_turtle_soup_answer`。

插件会判断猜测是否命中：

- 猜中：结束本局，并允许公布完整汤底
- 未猜中：只返回反馈，不泄露答案

### 揭秘或退出

- `reveal_turtle_soup_answer`：用户要求看答案、揭秘或结束并公布汤底时触发，会返回完整汤面和汤底并结束本局
- `exit_turtle_soup_game`：用户只想退出当前游戏但不看答案时触发，只确认结束，不透露汤底

## 对外组件

### Actions

| Action | 作用 |
| --- | --- |
| `start_turtle_soup_game` | 开始或更换一局海龟汤 |
| `ask_turtle_soup_question` | 回答玩家对当前汤题的提问 |
| `request_turtle_soup_hint` | 生成当前汤题提示 |
| `summarize_turtle_soup_clues` | 整理当前公开线索与历史问答 |
| `guess_turtle_soup_answer` | 判断玩家对汤底的猜测是否正确 |
| `reveal_turtle_soup_answer` | 公布汤底并结束本局 |
| `exit_turtle_soup_game` | 不揭秘，直接退出当前游戏 |

### Tools

| Tool | 作用 |
| --- | --- |
| `get_turtle_soup_state` | 查询当前会话海龟汤公开状态，不包含汤底 |
| `get_turtle_soup_question` | 查询当前会话汤面，不包含汤底 |

### Service

`TurtleSoupService` 提供程序化接口，覆盖开局、提问、提示、线索整理、猜测、揭秘、退出、状态查询和汤面查询。

## 题库来源

题目提供顺序：

1. 读取缓存题库：`data/turtle_soup/puzzle_cache.json`
2. 缓存数量低于阈值时，按配置搜索并抓取公开题库页面
3. 将有效题目追加进缓存，并按使用次数较少的题目优先抽取
4. 如果缓存和网络都不可用，则读取本地兜底题库：`plugins/turtle_soup/puzzles.json`

网络抓取受域名白名单、请求超时和页面大小限制约束，避免无限制访问外部页面。

## 配置项

配置文件：`config/plugins/turtle_soup/config.toml`

`[plugin]`：

- `enabled: bool = true` 是否启用插件

`[game]`：

- `max_hints: int = 3` 每局最多提示次数
- `max_history_items: int = 30` 每局最多保留的历史交互条数

`[puzzle]`：

- `min_cache_items: int = 100` 缓存低于该数量时尝试补充题库
- `max_fetch_pages: int = 20` 单次补库最多拉取题库页面数
- `max_search_pages: int = 5` 单次补库最多拉取搜索结果页数
- `cache_path: str = "data/turtle_soup/puzzle_cache.json"` 题库缓存路径
- `fallback_bank_path: str = "plugins/turtle_soup/puzzles.json"` 本地兜底题库路径
- `search_query: str = "海龟汤 汤面 汤底 题库"` 网络题库搜索关键词
- `search_urls: list[str] = []` 固定候选题库页面 URL 列表
- `enable_web_search: bool = true` 是否自动搜索公开题库
- `allowed_domains: list[str]` 允许访问的题库域名白名单
- `request_timeout_seconds: float = 10.0` 网页请求超时时间
- `max_page_bytes: int = 1000000` 单页最大读取字节数

`[llm]`：

- `model_task: str = "utils_small"` 用于问答、提示和猜测判断的模型任务名
- `temperature: float = 0.3` 互动判断生成温度
- `max_tokens: int = 500` 单次最大输出 token 数

## 使用示例

用户可以直接自然语言互动：

```text
来一局海龟汤
这个人是自己进屋的吗？
门口的鞋有两双吗？
给点提示
整理一下目前线索
我猜屋里还有一个小孩
公布答案吧
```

也可以中途退出：

```text
不玩了，结束这局
```

## 注意事项

- 汤底只在猜中或明确要求揭秘时公布。
- 线索整理只使用已经公开的问答和提示，不会主动补充汤底信息。
- 当前状态按聊天流区分，不同群聊或私聊互不影响。
- 若上下文被压缩导致聊天核心忘记当前汤面，可通过 `get_turtle_soup_question` 重新查询当前汤面。
- 自动网络补库只访问配置白名单内的公开页面；如需固定题库来源，可关闭 `enable_web_search` 并维护本地兜底题库。

## 版本

- Plugin: `1.0.0`
- Manifest: `plugins/turtle_soup/manifest.json`
