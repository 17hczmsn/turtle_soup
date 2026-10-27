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

默认模式（`llm.answer_in_actor_model = true`）：开局时插件把汤底与主持规则写入当前聊天流的私有 system reminder（`actor` bucket），default_chatter 的主回复模型会自动拾取。玩家提问时由主模型依据汤底直接判定，**并在同一轮调用序列里完成"记录 + 回复"**：先调 `ask_turtle_soup_question`（questions 与 answers 一一对应）记录历史，随后紧接着调用 `action-send_text` 回复玩家，最后 `action-pass_and_wait`——工具只是记录通道，不需要等它返回再另起一轮组织回复。若模型未提供判定或数量不匹配，自动逐条退回小模型判定兜底，此时工具返回中转指令。

关闭该模式后退回旧行为：只传 `questions`，由配置的小模型任务判定后返回标准答案。聊天核心可以调整语气，但不能擅自改写判定。

群聊中多名玩家同时提问时，把所有未回答的问题放进同一次调用，插件会逐条记录与回答，避免漏答（单次调用最多 5 条，超出部分会被丢弃）。

### 请求提示

当用户想要提示、线索或方向时触发 `request_turtle_soup_hint`。

默认模式下由主模型依据 reminder 中的汤底与"玩家已知信息归纳"自行生成一条不泄底的短线索，通过 `hint` 参数传入本工具记录；插件仍会做归一化（去掉前缀、35 字截断、汤底泄露检测）。未传 `hint` 时退回小模型生成（带专用的已知信息提示词）。

提示次数由配置项 `game.max_hints` 控制，默认每局最多 3 次。提示生成失败（如模型返回空内容或网络异常）时不消耗本局提示额度。每次问答、提示、猜错之后，插件会用最新的玩家已知信息刷新 reminder，帮助主模型避免重复提示或自相矛盾。

### 整理线索

当用户要求“复盘”“整理线索”“总结已知信息”时触发 `summarize_turtle_soup_clues`。

插件会返回当前公开汤面、已公开问答、提示使用次数等信息，方便继续推理，同时不会把汤底混入公开线索。

### 猜测汤底

当用户明确给出真相、答案或汤底猜测时触发 `guess_turtle_soup_answer`。

默认模式下由主模型依据 reminder 中的汤底自行判断是否基本命中（只有覆盖汤底核心因果与关键事实才算命中），通过 `is_correct` 参数传入本工具记录；未传时退回小模型判定。

- 猜中：结束本局，并允许公布完整汤底
- 未猜中：只返回判定，反馈话术由主模型按语境组织，不泄露答案

### 揭秘或退出

- `reveal_turtle_soup_answer`：用户要求看答案、揭秘或结束并公布汤底时触发，会返回完整汤面和汤底并结束本局
- `exit_turtle_soup_game`：用户只想退出当前游戏但不看答案时触发，只确认结束，不透露汤底

## 对外组件

### Tools

所有互动组件都注册为 Tool（查询类）：调用后把结构化事实返回给聊天核心，由聊天核心按角色语气组织回复。

| Tool | 作用 |
| --- | --- |
| `start_turtle_soup_game` | 开始或更换一局海龟汤 |
| `ask_turtle_soup_question` | 逐一回答玩家提问，支持一次传入多个问题 |
| `request_turtle_soup_hint` | 生成当前汤题提示 |
| `summarize_turtle_soup_clues` | 整理当前公开线索与历史问答 |
| `guess_turtle_soup_answer` | 判断玩家对汤底的猜测是否正确 |
| `reveal_turtle_soup_answer` | 公布汤底并结束本局 |
| `exit_turtle_soup_game` | 不揭秘，直接退出当前游戏 |
| `get_turtle_soup_state` | 查询当前会话海龟汤公开状态，不包含汤底 |
| `get_turtle_soup_question` | 查询当前会话汤面，不包含汤底 |

> 互动组件刻意不注册为 Action：default_chatter 在 `enable_action_suspend = true` 时会在纯 Action 回合直接挂起会话、不再生成后续回复，而这些互动恰恰依赖“工具返回事实 → 模型组织回复”的后续回合。注册为 Tool 后，无论 `enable_action_suspend` 开或关，海龟汤都能正常回复玩家。

### Service

`TurtleSoupService` 提供程序化接口，覆盖开局、提问、提示、线索整理、猜测、揭秘、退出、状态查询和汤面查询。

## 题库来源

题目提供顺序：

1. 读取缓存题库：`data/turtle_soup/puzzle_cache.json`
2. 缓存数量低于阈值时触发网络补库（受冷却时间约束，默认 30 分钟内最多一次），按优先级依次尝试：
   - **专用搜索 MCP（优先）**：自动挑选当前注册表中带网络搜索能力的 MCP 工具（如 tavily、brave 等），按其参数 schema 自适应调用，对返回文本直接解析抽题，并把结果中的 URL 作为候选页
   - **浏览器 MCP 全链路**：没有专用搜索工具或调用失败时，通过浏览器类 MCP（web-open + web-request）抓取 bing、百度搜索结果页提取候选链接，**候选页正文也用浏览器会话抓取**（真实 UA 与 Cookie，可绕过知乎、B 站等站点的反爬）
   - **内置抓取（最终兜底）**：浏览器 MCP 不可用时，用裸 HTTP 抓搜索引擎/固定 URL 种子页 → 链接提取 → 候选页并发抓取解析（反爬站点成功率低，仅作兜底）
3. 将有效题目追加进缓存，并按使用次数较少的题目优先抽取
4. 如果缓存和网络都不可用，则读取本地兜底题库：`plugins/turtle_soup/puzzles.json`

网络抓取受域名白名单、请求超时和页面大小限制约束，避免无限制访问外部页面。补库各环节（触发、各路调用、抓取结果）都会输出 `turtle_soup` 日志；找不到可用的 MCP 工具时也会在日志中明确提示，便于排查。

## 配置项

配置文件：`config/plugins/turtle_soup/config.toml`

`[plugin]`：

- `enabled: bool = true` 是否启用插件

`[game]`：

- `max_hints: int = 3` 每局最多提示次数
- `max_history_items: int = 30` 每局最多保留的历史交互条数
- `idle_timeout_minutes: int = 30` 闲置超时分钟数：超过该时长没有任何游戏互动则自动结束本局并移除主持人 reminder；0 表示不启用

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
- `supplement_cooldown_minutes: int = 30` 两次网络补库之间的冷却分钟数，冷却期内开局直接使用缓存或本地题库
- `use_mcp_search: bool = true` 补库时是否优先调用 MCP 搜索工具（自动挑选网络搜索类工具，不可用时退回内置抓取）
- `mcp_tool_signature: str = ""` 固定使用的 MCP 搜索工具组件签名；留空时自动挑选带网络搜索能力的 MCP 工具

`[llm]`：

- `model_task: str = "utils_small"` 用于提示、判断兜底的模型任务名
- `answer_in_actor_model: bool = true` 开局时把汤底与主持规则注入主回复模型（actor）的流私有 system reminder，问答判定、提示生成、猜测判断由主模型直接完成；关闭后退回小模型
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
- `answer_in_actor_model` 开启时，汤底会进入主回复模型的上下文（流私有 system reminder，玩家不可见）；游戏结束（猜中、揭秘、退出）时插件会自动移除该 reminder，问答/提示/猜错后会自动刷新其中的玩家已知信息。若主模型出现泄露汤底倾向，可关闭该模式退回小模型判定。
- 游戏闲置超过 `game.idle_timeout_minutes` 分钟（默认 30，0 为不启用）会自动结束本局并移除主持人 reminder：每次主模型请求前事件处理器都会检查一次，玩家散场后汤底机密不会残留在后续无关对话的模型上下文里；游戏互动（问答、提示、猜测、整理线索）会重置计时。
- 线索整理只使用已经公开的问答和提示，不会主动补充汤底信息。
- 当前状态按聊天流区分，不同群聊或私聊互不影响。
- 若上下文被压缩导致聊天核心忘记当前汤面，可通过 `get_turtle_soup_question` 重新查询当前汤面。
- 自动网络补库只访问配置白名单内的公开页面；如需固定题库来源，可关闭 `enable_web_search` 并维护本地兜底题库。
- MCP 路径会从已连接的 MCP 服务器里自动挑选网络搜索工具（要求工具同时具备"搜索"与"网络"信号，排除本地文件搜索等）；也可以用 `mcp_tool_signature` 固定指定。想要启用该路径，推荐在 `config/mcp.toml` 中接入仓库自带的 tavily 搜索服务器：
  1. 安装依赖：`pip install tavily-python`
  2. 在 `config/mcp.toml` 中注册 `mcp_servers/mcp_tavily.py`，并把 `TAVILY_API_KEY` 环境变量替换为你自己的 Key（https://tavily.com 可免费注册）
  3. 未配置专用搜索 MCP 时，插件会自动尝试用浏览器类 MCP（web-open + web-request）抓取搜索引擎结果页作为替代；两者都没有时才退回内置抓取
  4. Key 未填写时 tavily 服务器会连接失败并记录在日志中，不影响其他 MCP 服务器和插件运行
- 补库过程的失败原因（未找到可用 MCP 工具、搜索调用失败、抓取为 0 等）都会记录在 `turtle_soup` 日志名下，补库不生效时先看日志。

## 版本

- Plugin: `1.2.0`
- Manifest: `plugins/turtle_soup/manifest.json`

## 变更记录

- 1.2.0
  - 互动组件从 Action 迁移为 Tool，`enable_action_suspend` 开启时也能正常回复。
  - `ask_turtle_soup_question` 支持一次调用回答多个玩家问题，缓解群聊多人同时提问漏答。
  - 提示生成失败不再消耗本局提示次数；修复模型返回空内容时提示接口崩溃（IndexError）。
  - 提示词改为基于“玩家已知信息”归纳（已确认 / 已排除 / 已提示）生成递进提示，减少泄露未知信息。
  - 问答判定标准收紧：只有汤底直接成立或必然可推出的内容才答“是”，拿不准优先“否/不重要”；修复“不是”被误归一化为“是”的问题。
  - 新增 `llm.answer_in_actor_model`（默认开启）：开局把汤底与主持规则注入主回复模型的流私有 system reminder，问答判定、提示生成、猜测判断均由主模型直接完成并经对应工具记录，省去小模型一跳；参数缺失或无法解析时自动回退小模型。游戏结束时自动移除 reminder，问答/提示/猜错后用最新玩家已知信息刷新 reminder。
  - MCP 补库增加浏览器类 MCP 搜索回退（web-open + web-request 抓取搜索结果页）。
  - 修复 tavily 等搜索工具被误排除的问题：负向信号（文件/数据库/视频等）只对工具名生效，不再因描述里的使用示例（如“数据库连接问题”）连坐排除整个工具。
  - 浏览器 MCP 补库升级为全链路：候选题库页正文也通过浏览器会话抓取（真实 UA 与 Cookie），不再用裸 HTTP 抓知乎等反爬站点；只有浏览器 MCP 不可用时才退回内置裸 HTTP 抓取。
  - 浏览器抓取单页改为两级链路：`web-request` 直接请求（快），失败时自动 `web-open` 真实导航 + `browser-observe` 读取页面可见正文（执行 JS、完整浏览器指纹，反爬通过率高）；各环节失败都会记录响应片段日志。
  - 专用搜索工具（如 tavily）已返回题目时，跳过浏览器与内置抓取链路，避免每次补库都弹出浏览器窗口。
  - 新增闲置超时机制（`game.idle_timeout_minutes`，默认 30 分钟）：每次主模型请求前检查，超时自动结束本局并移除主持人 reminder，防止玩家散场后汤底残留模型上下文。
  - 调整等待时机：记录/提示/猜测轮内不再调用 `action-pass_and_wait`，改为下一轮收到记录回执后再等待——`pass_and_wait` 在待消化工具结果的回合被 chatter 的跨轮去重吞掉会导致会话空转，延后一轮可彻底规避（该调用在下一轮是首次出现，正常生效）。
  - 多条细节修复：猜错后立即把该猜测纳入"已排除方向"刷新 reminder；无游戏状态时的残留 reminder 自愈清理；单次问答达到 5 条上限时输出日志；浏览器补库候选页抓取上限 8 个（防止拖垮 chatter 单步超时）；主持规则引导对不同玩家携带 reply_to 回复，避免内容相同的回复被去重跳过。
  - 二次自查修复：换汤/重开时无条件先移除旧 reminder（防止关闭 actor 模式时旧汤底残留泄露）；reminder 增加本局提示额度信息（模型生成提示前可知剩余机会）；空问题输入直接拒绝并记日志；manifest `api_version` 补齐实际使用的 `prompt_api` 与 `event_api` 声明。
  - 补库链路（MCP 搜索、浏览器回退、内置抓取）增加日志，失败原因可在日志中直接定位。
