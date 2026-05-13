# Agent 核心框架设计文档

## 概述

本文档描述 Agent 模块三个核心子系统的框架设计：**记忆系统**、**工具系统**、**LLM 交互层**。

所有新代码位于 `src/features/agent/core/` 下的独立子目录，现有代码不做任何修改，新框架并行存在，后续逐步迁移。

---

## 目录结构

```
src/features/agent/core/
├── memory/                     # 记忆系统
│   ├── __init__.py
│   ├── interfaces.py           # 抽象接口 + 数据类
│   ├── token_budget.py         # Token 预算管理
│   ├── working.py              # 工作记忆（内存级）
│   ├── compress.py             # 压缩策略
│   ├── short_term.py           # 短期记忆（对话上下文）
│   └── long_term.py            # 长期记忆（跨会话知识）
├── tool/                       # 工具系统
│   ├── __init__.py
│   ├── definition.py           # 统一工具定义
│   ├── result.py               # 结构化工具结果
│   ├── hooks.py                # 生命周期钩子
│   └── executor.py             # 增强版执行器
└── llm/                        # LLM 交互层
    ├── __init__.py
    ├── agent_llm.py            # AgentLLM 封装
    └── stream_handler.py       # 流式响应处理器

# 配套
src/features/agent/
├── models/memory.py            # 长期记忆 ORM 模型
└── repository/memory_repository.py  # 长期记忆仓储
```

---

## 一、记忆系统

### 1.1 架构设计

三层记忆架构，每层有独立的接口和生命周期：

```
┌─────────────────────────────────────────────────┐
│                  AgentEngine                     │
│                     ▲                            │
│                     │ MemorySnapshot              │
│          ┌──────────┴──────────┐                 │
│          │   短期记忆 (STM)     │                 │
│          │  当前对话上下文       │                 │
│          │  Token 预算管理      │                 │
│          │  自动压缩触发        │                 │
│          └──┬───────┬───────┬──┘                 │
│             │       │       │                    │
│    ┌────────┴──┐ ┌──┴────┐ ┌┴──────────┐        │
│    │长期记忆(LTM)│ │工作记忆│ │Token 预算 │        │
│    │跨会话知识   │ │任务状态│ │Token 计数 │        │
│    │偏好/事实    │ │内存TTL │ │预算计算   │        │
│    └───────────┘ └───────┘ └───────────┘        │
└─────────────────────────────────────────────────┘
```

| 层级 | 接口 | 实现 | 存储 | 生命周期 |
|------|------|------|------|---------|
| 短期记忆 | `IShortTermMemory` | `ShortTermMemory` | 数据库 | 每次请求构建 |
| 长期记忆 | `ILongTermMemory` | `LongTermMemory` | 数据库 `agent_memories` 表 | 永久，对话结束时巩固 |
| 工作记忆 | `IWorkingMemory` | `WorkingMemory` | 进程内存 | TTL 自动过期（默认 1 小时） |

### 1.2 数据模型

#### MemoryMessage — 统一内部消息模型

```python
@dataclass
class MemoryMessage:
    role: str                                  # user / assistant / system / tool
    content: str
    tool_call_id: Optional[str] = None         # tool 消息关联的调用 ID
    tool_name: Optional[str] = None            # 产生此消息的工具名
    tool_calls: Optional[List[Dict]] = None    # assistant 消息携带的工具调用
    token_count: Optional[int] = None
    metadata: Dict[str, Any]                   # 扩展字段
```

所有内部消息流转使用此模型，避免直接依赖 ORM 对象。

#### MemorySnapshot — 记忆快照

```python
@dataclass
class MemorySnapshot:
    messages: List[Dict[str, Any]]    # OpenAI 格式消息列表
    total_tokens: int                 # 预估 token 总数
    compressed: bool = False          # 是否经过压缩
    compression_ratio: float = 1.0    # 压缩比率
```

`ShortTermMemory.build_context()` 的输出，`AgentEngine` 只消费这个快照。

#### LongTermMemoryEntry — 长期记忆条目

```python
@dataclass
class LongTermMemoryEntry:
    id: int
    agent_id: int
    user_id: int
    category: str                      # preference / fact / procedure / insight
    content: str
    relevance_score: float
    access_count: int
    source_conversation_id: Optional[int]
```

四种记忆类别：

| 类别 | 说明 | 示例 |
|------|------|------|
| `preference` | 用户偏好 | "用户喜欢简洁的回答" |
| `fact` | 事实信息 | "用户的项目使用 Python 3.12" |
| `procedure` | 操作流程 | "部署流程：先测试→构建→推送" |
| `insight` | 有价值的洞察 | "用户团队使用 GitFlow 分支策略" |

### 1.3 接口定义

#### IShortTermMemory — 短期记忆

```python
class IShortTermMemory(ABC):
    async def build_context(
        self,
        system_prompt: str,           # 系统提示词
        conversation_id: int,         # 会话 ID
        max_tokens: int,              # 模型上下文窗口上限
        reserve_tokens: int = 1024,   # 为 LLM 生成预留的 token 数
    ) -> MemorySnapshot
    # 核心流程：DB消息 → Token计算 → 超限压缩 → OpenAI格式消息

    async def add_message(self, conversation_id: int, message: MemoryMessage) -> None
    async def get_token_count(self, conversation_id: int) -> int
```

#### ILongTermMemory — 长期记忆

```python
class ILongTermMemory(ABC):
    async def store(
        self, agent_id, user_id, category, content,
        source_conversation_id=None,
    ) -> LongTermMemoryEntry
    # 存储一条长期记忆

    async def search(
        self, agent_id, user_id, query, top_k=5, categories=None,
    ) -> List[LongTermMemoryEntry]
    # 根据查询搜索相关的长期记忆

    async def consolidate(
        self, agent_id, user_id, conversation_id, messages: List[MemoryMessage],
    ) -> int
    # 对话结束时从消息中提取有价值信息并存储，返回新存储条目数
```

#### IWorkingMemory — 工作记忆

```python
class IWorkingMemory(ABC):
    async def get_state(self, conversation_id: int, key: str) -> Optional[Any]
    async def set_state(self, conversation_id: int, key: str, value: Any, ttl=None) -> None
    async def get_all_states(self, conversation_id: int) -> Dict[str, Any]
    async def clear(self, conversation_id: int) -> None
```

### 1.4 组件实现

#### TokenBudget — Token 预算管理器

```python
class TokenBudget:
    def __init__(self, model_name: str = "gpt-4")

    def count_text_tokens(self, text: str) -> int
    # 底层复用 src/shared/utils/text_processing/token_counter.py

    def count_messages_tokens(self, messages: List[MemoryMessage]) -> int
    # 每条消息额外加 4 token 的角色标记开销
    # tool_calls 的 JSON 额外计入

    def get_available_budget(
        self, model_context_window, system_prompt_tokens, tools_tokens, reserve_for_generation=1024,
    ) -> int
    # 公式：context_window - system_prompt - tools - reserve
```

#### WorkingMemory — 工作记忆（已完整实现）

```python
class WorkingMemory(IWorkingMemory):
    def __init__(self, default_ttl: int = 3600)

    # 存储结构：{conversation_id: {key: (value, expires_at)}}
    # 过期策略：惰性清理（get_state 时检查过期）
    # 典型用途：
    #   - 多步骤任务的中间结果：set_state(conv_id, "step_1_result", data)
    #   - 工具调用链上下文：set_state(conv_id, "tool_result_xxx", result)
    #   - Agent 当前意图：set_state(conv_id, "current_plan", plan_text)
```

#### ICompressionStrategy — 压缩策略

```python
class ICompressionStrategy(ABC):
    async def compress(
        self, messages: List[MemoryMessage], available_tokens: int, token_budget: TokenBudget,
    ) -> Tuple[List[MemoryMessage], bool, float]
    # 返回：(压缩后消息, 是否压缩了, 压缩比率)
```

两个实现方向：

| 策略 | 说明 |
|------|------|
| `SlidingWindowCompression` | 保留最近 N 条消息 + 摘要替换早期消息。需要 LLM 生成摘要。 |
| `PriorityBasedCompression` | 按优先级裁剪：工具结果 < 旧对话 < 新对话。不需要 LLM 调用。 |

#### ShortTermMemory — 短期记忆管理器

```
build_context() 核心流程：

1. 从数据库加载消息 + 工具调用记录
   ├─ msg_repo.list_by_conversation(conversation_id, limit=200)
   └─ tc_repo.list_by_conversation(conversation_id)

2. 转换为 MemoryMessage 列表
   └─ _convert_db_messages(db_messages, db_tool_calls)

3. 计算 Token 预算
   ├─ available_tokens = max_tokens - reserve_tokens
   ├─ system_tokens = token_budget.count_text_tokens(system_prompt)
   └─ messages_tokens = token_budget.count_messages_tokens(messages)

4. 超出预算？→ compression_strategy.compress()
   └─ 摘要写入 AgentSession.summary 字段

5. 组装 OpenAI 格式消息
   └─ _build_openai_messages(system_prompt, memory_messages)

6. 返回 MemorySnapshot
```

#### LongTermMemory — 长期记忆管理器

```
consolidate() 巩固流程（对话结束时调用）：

1. 筛选有价值的对话消息
2. 构建 extraction prompt，要求 LLM 提取结构化记忆
3. 调用 LLM 返回 JSON 数组 [{category, content}, ...]
4. 解析提取结果
5. 逐条去重（与已有记忆比对）
6. 存入 agent_memories 表

search() 检索流程（对话开始时调用）：

1. 根据用户当前消息搜索相关记忆
2. 返回 top_k 条最相关记忆
3. 递增访问计数
```

### 1.5 数据库表

```sql
-- agent_memories: 长期记忆表
CREATE TABLE agent_memories (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    agent_id    BIGINT NOT NULL,          -- 关联 Agent
    user_id     BIGINT NOT NULL,          -- 关联用户
    category    VARCHAR(50) NOT NULL,     -- preference/fact/procedure/insight
    content     TEXT NOT NULL,            -- 记忆内容
    source_conversation_id BIGINT,        -- 来源会话
    access_count INT DEFAULT 0,           -- 访问次数
    relevance_score FLOAT DEFAULT 0.0,    -- 相关性分数
    extra_data  JSON,                     -- 扩展元数据
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,

    INDEX idx_agent_user (agent_id, user_id),
    INDEX idx_category (category)
);
```

### 1.6 数据流

```
用户消息进入
      │
      ▼
ShortTermMemory.build_context()
      ├─ DB 加载消息 + 工具调用记录
      ├─ TokenBudget 计算 token 数
      ├─ 超限？→ CompressionStrategy.compress()
      ├─ WorkingMemory.get_all_states() → 附加当前任务状态
      └─ LongTermMemory.search() → 注入相关的长期记忆片段
      │
      ▼
MemorySnapshot { messages, total_tokens, compressed }
      │
      ▼
AgentEngine.run(snapshot.messages, ...)
      │
      ▼
对话结束 → LongTermMemory.consolidate()
              └─ LLM 提取 → agent_memories 表
```

---

## 二、工具系统

### 2.1 架构设计

```
┌────────────────────────────────────────────────────┐
│                    AgentEngine                      │
│                        │                            │
│                        ▼                            │
│               ToolExecutorV2                        │
│              ┌────┴────┐                            │
│              │ 钩子链   │                            │
│              │ Logging  │                            │
│              │ Truncate │                            │
│              │ Timeout  │                            │
│              └────┬────┘                            │
│           ┌───────┼───────┐                         │
│           ▼       ▼       ▼                         │
│      内置技能   MCP工具  自定义工具                  │
│      (BaseSkill) (MCP)    (待扩展)                  │
└────────────────────────────────────────────────────┘
```

### 2.2 数据模型

#### ToolDefinition — 统一工具定义

```python
class ToolSource(str, Enum):
    BUILTIN = "builtin"    # 内置技能
    MCP = "mcp"            # MCP 远程工具
    CUSTOM = "custom"      # 用户自定义工具（预留）

class ToolParameter(BaseModel):
    type: str = "string"
    description: str = ""
    enum: Optional[List[str]] = None
    default: Optional[Any] = None

class ToolDefinition(BaseModel):
    name: str                              # 工具全局唯一名称
    description: str
    parameters: Dict[str, ToolParameter]   # 参数定义
    required: List[str]                    # 必填参数
    source: ToolSource                     # 来源
    source_ref: Optional[str]              # 来源标识（如 MCP server_name）
    timeout_ms: int = 30000                # 执行超时
    dangerous: bool = False                # 是否需要用户确认

    def to_openai_format(self) -> Dict[str, Any]
    # 转换为 OpenAI function calling 格式
```

所有工具（内置/MCP/自定义）统一为 `ToolDefinition`，通过 `to_openai_format()` 输出 LLM 需要的格式。

#### ToolResult — 结构化执行结果

```python
class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denized"

class ToolResult(BaseModel):
    status: ToolResultStatus = SUCCESS
    content: str = ""                      # 文本结果
    data: Optional[Dict] = None            # 结构化数据（如搜索结果）
    duration_ms: int = 0                   # 执行耗时
    error_message: Optional[str] = None    # 错误信息
    metadata: Dict[str, Any] = {}          # 扩展元数据（如截断标记）

    def to_llm_content(self) -> str
    # 转换为 LLM 可消费的文本
    #   ERROR → "工具执行失败：{error}"
    #   有 data → JSON 格式化输出
    #   否则 → content 原文
```

替代现有 `execute_tool()` 返回裸 `str` 的模式，支持状态码、结构化数据和元数据。

### 2.3 生命周期钩子

```python
class ToolHook(ABC):
    async def before_execute(
        self, tool: ToolDefinition, arguments: Dict, context: Dict,
    ) -> Optional[Dict]
    # 返回修改后的 arguments，或 None 不修改。抛异常可阻止执行。

    async def after_execute(
        self, tool: ToolDefinition, arguments: Dict, result: ToolResult, context: Dict,
    ) -> ToolResult
    # 可修改结果后返回（如脱敏、截断等）
```

内置钩子：

| 钩子 | before | after | 说明 |
|------|--------|-------|------|
| `LoggingHook` | 记录工具名和来源 | 记录状态和耗时 | 结构化日志输出 |
| `ResultTruncationHook` | — | 截断超长 content | 默认上限 8000 字符 |
| `TimeoutHook` | 注入 timeout_ms 到 context | — | 由执行器读取设置超时 |

### 2.4 ToolExecutorV2 — 增强版执行器

```
execute(tool_name, arguments, context) → ToolResult

执行流程：

1. 查找工具定义 → ToolDefinition
2. 运行 before_hooks（可修改参数或阻止执行）
3. 路由到实际执行器：
   ├─ mcp__ 前缀 → _execute_mcp_tool()
   │   解析 mcp__{server_name}__{tool_name}
   │   → McpClientManager.call_tool()
   └─ 其他 → _execute_skill_tool()
       → SkillRegistry.find_skill_for_tool()
       → skill.execute_tool()（适配现有 BaseSkill 接口）
4. 包装为 ToolResult
5. 运行 after_hooks（可修改结果）
6. 返回最终 ToolResult
```

与现有 BaseSkill 的兼容方式：`_execute_skill_tool()` 内部调用 `skill.execute_tool()`，现有技能代码无需修改。

```
resolve_tools(enabled_skills, enabled_mcp_ids) → List[ToolDefinition]
resolve_tools_openai_format(...) → List[Dict]  # 向后兼容
```

---

## 三、LLM 交互层

### 3.1 设计决策

**组合优于继承**：`AgentLLM` 持有 `BaseLLM` 实例，不继承它。

```
AgentLLM (新类，feature 层)
  ├── 持有 BaseLLM 实例（shared 层）
  ├── 增加流式工具调用处理
  ├── 增加 token 统计聚合
  └── 增加降级策略

BaseLLM (不变)
  ├── OpenAICompatibleLLM
  ├── AnthropicLLM
  ├── OllamaLLM
  └── TransformersLLM
```

理由：
- `BaseLLM` 被 QA、深度研究等多个 feature 使用，修改接口影响面大
- Agent 的流式工具调用是 Agent 领域特有的需求，不应泄漏到 shared 层

### 3.2 数据模型

#### StreamChunk — 流式输出块

```python
@dataclass
class StreamChunk:
    type: str  # 流式块类型
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments_delta: str = ""
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
```

流式块类型说明：

| type | 含义 | 携带数据 |
|------|------|---------|
| `content` | 文本内容增量 | `content` |
| `tool_call_start` | 工具调用开始 | `tool_call_id`, `tool_name` |
| `tool_call_args` | 工具参数增量 | `tool_call_id`, `tool_arguments_delta` |
| `tool_call_end` | 工具调用完成 | `tool_call_id`, `tool_name`, `tool_arguments_delta`(完整参数) |
| `done` | 全部完成 | `usage`, `finish_reason` |

#### CollectedToolCall — 完整的工具调用

```python
@dataclass
class CollectedToolCall:
    id: str
    name: str
    arguments: str    # 完整的 JSON 字符串
```

#### AgentLLMResponse — 非流式完整响应

```python
@dataclass
class AgentLLMResponse:
    content: str = ""
    tool_calls: List[CollectedToolCall] = []
    finish_reason: str = "stop"
    usage: Optional[Dict[str, int]] = None
```

### 3.3 AgentLLM

```python
class AgentLLM:
    def __init__(self, base_llm: BaseLLM)

    async def generate(
        self, messages, tools=None, max_tokens=4096,
        temperature=0.7, top_p=0.8, tool_choice="auto",
    ) -> AgentLLMResponse
    # 非流式生成，委托给 base_llm.generate_with_tools()

    async def generate_stream(
        self, messages, tools=None, max_tokens=4096,
        temperature=0.7, top_p=0.8, tool_choice="auto",
    ) -> AsyncGenerator[StreamChunk, None]
    # 流式生成
    # OpenAI SDK → stream=True + tools，逐 chunk 解析
    # 其他 LLM → 降级为非流式
```

流式降级策略：

```
generate_stream() 内部：

if isinstance(base_llm, OpenAICompatibleLLM) and tools:
    → 原生流式：stream=True + tools 参数
    → 逐 chunk 解析 content 和 tool_calls 增量
    → yield StreamChunk
else:
    → 降级非流式：调用 generate() 一次性返回
    → yield 完整的 content + tool_call_end + done
```

### 3.4 StreamEventHandler — SSE 转换器

```python
class StreamEventHandler:
    def __init__(self, conversation_id: int)

    async def handle_chunk(
        self, chunk: StreamChunk, user_msg: AgentMessage,
        tc_repo: ToolCallRepository, context: Dict,
    ) -> Optional[str]
    # 将 StreamChunk 转换为 SSE 格式字符串
    # 同时创建/更新工具调用记录（DB 持久化）

    def get_full_content(self) -> str       # 拼接后的完整文本
    def get_total_tokens(self) -> int       # 总 token 使用量
    def get_tool_call_db_id(call_id) -> int # call_id → DB 记录 ID
```

SSE 事件映射：

| StreamChunk.type | SSE event | 说明 |
|------------------|-----------|------|
| `content` | `event: content` | 文本增量 `{"content": "..."}` |
| `tool_call_start` | `event: tool_call` | 工具开始 `{"tool_name", "call_id", "status": "running"}` |
| `tool_call_args` | `event: tool_call_args` | 参数增量 `{"call_id", "delta"}` |
| `tool_call_end` | 由引擎层处理 | 工具执行后发送 `tool_result` |
| `done` | 由引擎层处理 | 发送 `done` |

---

## 四、组件交互总图

```
                    API Route (POST /agents/{id}/chat-stream)
                              │
                              ▼
                       AgentChatService
                        ┌─────┼─────┐
                        ▼     ▼     ▼
                    [准备] [构建] [循环]
                        │     │     │
                        ▼     ▼     ▼
                  AgentService  │  AgentEngine
                                │     │
                   ┌────────────┘     │
                   ▼                  ▼
            ┌──────────────┐   ┌──────────────┐
            │  记忆系统     │   │  AgentLLM    │──→ BaseLLM (shared)
            │  STM + LTM   │   │  流式/非流式  │     │
            │  + WM        │   │  工具调用收集  │     │
            └──────┬───────┘   └──────┬───────┘     │
                   │                  │              ▼
                   ▼                  ▼         StreamChunk 流
            MemorySnapshot    ToolExecutorV2         │
                   │          ┌────┼────┐            ▼
                   │          ▼    ▼    ▼     StreamEventHandler
                   │       [钩子] [路由] [结果]       │
                   │          │    │    │             ▼
                   │          ▼    ▼    ▼          SSE 事件
                   │       Logging Skill ToolResult  │
                   │       Truncate MCP              ▼
                   │       Timeout              前端 EventSource
                   ▼
            DB: agent_messages
                agent_tool_calls
                agent_memories
```

---

## 五、与现有代码的关系

| 现有文件 | 状态 | 新文件对应 | 关系 |
|---------|------|-----------|------|
| `core/memory.py` (ConversationMemory) | 保留不动 | `core/memory/short_term.py` | 新版短期记忆替代 |
| `core/executor.py` (ToolExecutor) | 保留不动 | `core/tool/executor.py` | V2 增强版替代 |
| `core/engine.py` (AgentEngine) | 保留不动 | 后续重构 | 将使用新组件 |
| `services/chat_service.py` | 保留不动 | 后续适配 | 注入新依赖 |
| `skills/base.py` (BaseSkill) | **完全兼容** | — | V2 执行器通过适配层调用 |
| `skills/builtins/*` | **完全兼容** | — | 无需修改 |
| `mcp/client.py` (McpClientManager) | **完全兼容** | — | V2 执行器直接使用 |

迁移策略：新框架并行存在，后续逐个 API 端点迁移到新组件，不破坏现有功能。

---

## 六、开发进度

| 组件 | 状态 | 说明 |
|------|------|------|
| 记忆系统接口 (`interfaces.py`) | ✅ 完成 | 全部抽象接口和数据类 |
| Token 预算 (`token_budget.py`) | ✅ 完成 | 已集成 TokenCounter |
| 工作记忆 (`working.py`) | ✅ 完成 | 已完整实现 |
| 压缩策略 (`compress.py`) | 🔨 骨架 | 接口已定义，两种策略待实现 |
| 短期记忆 (`short_term.py`) | 🔨 骨架 | 核心流程已编写，消息转换待完善 |
| 长期记忆 ORM + 仓储 | ✅ 完成 | 表结构和完整 CRUD |
| 长期记忆 (`long_term.py`) | 🔨 骨架 | 提取/存储/搜索流程已编写，prompt 模板待完善 |
| 工具定义 (`definition.py`) | ✅ 完成 | ToolDefinition + to_openai_format() |
| 工具结果 (`result.py`) | ✅ 完成 | ToolResult + to_llm_content() |
| 工具钩子 (`hooks.py`) | ✅ 完成 | 三个内置钩子已实现 |
| 增强版执行器 (`executor.py`) | 🔨 骨架 | 路由和钩子流程已编写 |
| AgentLLM (`agent_llm.py`) | 🔨 骨架 | 非流式已完成，原生流式待实现 |
| 流式处理器 (`stream_handler.py`) | ✅ 完成 | SSE 转换和状态持久化 |
