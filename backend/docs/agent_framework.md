# Agent 核心框架设计文档

## 概述

本文档描述 Agent 模块的核心框架实现，包含三个子系统：**记忆系统**、**工具系统**、**LLM 交互层**，以及 **ReAct 引擎**。

核心代码位于 `src/features/agent/core/`，分为 `memory/`、`tool/`、`llm/` 三个子目录和 `engine.py` 引擎入口。

---

## 目录结构

```
src/features/agent/core/
├── engine.py                    # AgentEngine — ReAct 循环引擎
├── prompt_builder.py            # SystemPromptBuilder — 分层 prompt 组装
├── retry.py                     # LLM 调用重试逻辑
│
├── memory/                      # 记忆系统（两层：短期 + 长期）
│   ├── __init__.py              # 仅导出 MemoryManager
│   ├── interfaces.py            # 抽象接口 + 数据类（MemoryMessage、MemorySnapshot 等）
│   ├── token_budget.py          # Token 预算管理
│   ├── memory_manager.py        # MemoryManager — 统一门面（冻结快照 + 预取 + 上下文构建）
│   ├── short_term.py            # ShortTermMemory — 对话上下文管理
│   ├── long_term.py             # LongTermMemory — 跨会话知识（ES 混合搜索 + MySQL 回退）
│   ├── compress.py              # ICompressionStrategy 接口
│   ├── context_compressor.py    # ContextCompressor — 五阶段结构化压缩
│   ├── context_scrubber.py      # StreamingContextScrubber — SSE 输出标签清理
│   ├── security.py              # 记忆安全扫描（注入/泄露/Unicode 检测）
│   ├── todo_store.py            # TodoStore — 跨压缩任务状态追踪
│   └── DESIGN.md                # 记忆系统设计说明
│
├── tool/                        # 工具系统
│   ├── __init__.py
│   ├── definition.py            # ToolDefinition — 统一工具定义
│   ├── result.py                # ToolResult + ToolResultStatus（SUCCESS/ERROR/TIMEOUT）
│   ├── hooks.py                 # 生命周期钩子（Logging / Truncation / ResultBudget）
│   ├── executor.py              # ToolExecutor — 路由 + 钩子 + 超时
│   ├── registry.py              # ToolRegistry — 工具注册中心
│   ├── base.py                  # BaseTool — 工具基类
│   └── builtins/                # 内置工具
│       ├── knowledge_search.py  # 知识库搜索
│       ├── web_search.py        # 网络搜索
│       ├── code_execution.py    # Docker 沙盒代码执行
│       ├── memory.py            # 记忆管理（add/replace/remove）
│       ├── todo.py              # 任务追踪
│       └── read_tool_result.py  # 工具结果读取
│
└── llm/                         # LLM 交互层
    ├── __init__.py
    └── agent_llm.py             # AgentLLM — 组合 BaseLLM，流式/非流式 + 工具调用

# 配套文件
src/features/agent/
├── agent_prompts.py             # Prompt 模板常量
├── models/
│   ├── memory.py                # AgentMemory ORM
│   ├── context_summary.py       # AgentContextSummary ORM（追加写入压缩摘要）
│   └── session.py               # AgentSession ORM
├── repository/
│   ├── memory_repository.py     # 长期记忆 CRUD
│   ├── memory_search_repository.py  # ES 混合搜索记忆
│   └── context_summary_repository.py  # 压缩摘要仓储
├── mcp/                         # MCP 协议支持
│   ├── client.py                # McpClientManager
│   └── config.py                # MCP 连接配置
└── sandbox/                     # 代码沙盒
    ├── docker_sandbox.py        # Docker 隔离执行
    └── config.py                # 沙盒配置
```

---

## 一、记忆系统

### 1.1 架构设计

两层记忆架构，通过 `MemoryManager` 统一管理：

```
┌─────────────────────────────────────────────────┐
│                  AgentEngine                     │
│                     ▲                            │
│                     │ MemorySnapshot              │
│          ┌──────────┴──────────┐                 │
│          │   MemoryManager      │                 │
│          │   统一门面            │                 │
│          └──┬───────┬───────┬──┘                 │
│             │       │       │                    │
│    ┌────────┴──┐ ┌──┴────┐ ┌┴──────────┐        │
│    │短期记忆(STM)│ │长期记忆│ │ContextCompressor│   │
│    │对话上下文   │ │LTM    │ │五阶段压缩    │    │
│    │Token 预算  │ │ES搜索 │ │摘要持久化    │    │
│    └───────────┘ └───────┘ └───────────┘        │
│                                                   │
│    TodoStore ── 跨压缩任务状态（内存）              │
│    Security  ── 记忆安全扫描                       │
└─────────────────────────────────────────────────┘
```

| 层级 | 接口 | 实现 | 存储 | 生命周期 |
|------|------|------|------|---------|
| 短期记忆 | `IShortTermMemory` | `ShortTermMemory` | 数据库 | 每次请求构建 |
| 长期记忆 | `ILongTermMemory` | `LongTermMemory` | MySQL + ES | 永久，对话结束时巩固 |

> **设计变更说明**：原设计中的第三层"工作记忆"（WorkingMemory）未实现。跨压缩的任务状态由 `TodoStore`（进程内存）承担。

### 1.2 核心组件

#### MemoryManager — 统一门面

```python
class MemoryManager:
    """记忆系统统一入口"""

    @classmethod
    def create(cls, message_repository, tool_call_repository, session_repository,
               memory_repository, model, llm_client_factory, ...) -> "MemoryManager"
    # 工厂方法，初始化所有子组件

    async def build_frozen_snapshot(self, agent_id, user_id) -> str
    # 构建冻结快照：首次从 MySQL 加载长期记忆后缓存到内存，会话期间不再变动。

    async def prefetch(self, query, agent_id, user_id, top_k=3) -> List[LongTermMemoryEntry]
    # 根据用户消息动态预取相关长期记忆（ES 混合搜索 → MySQL LIKE 回退）

    async def build_context(self, system_prompt, conversation_id, max_tokens) -> MemorySnapshot
    # 完整上下文构建：DB消息 → Token计算 → 超限压缩 → OpenAI格式
```

#### ContextCompressor — 五阶段结构化压缩

当对话历史超出 Token 预算时触发：

```
Phase 1: 工具结果信息性剪枝 — 按工具类型生成摘要、去重、参数截断
Phase 2: Token 预算尾部保护 — 确保最近用户消息在保护区内
Phase 3: 结构化 LLM 摘要 — 使用辅助模型生成 13 章节模板摘要（敏感数据脱敏）
Phase 4: 迭代更新 — 融合旧摘要 + 新内容
Phase 5: 工具对清理 — 移除已失去上下文的工具调用/结果对
```

特性：
- **防抖动**：cooldown 机制避免频繁压缩
- **摘要持久化**：压缩结果写入 `agent_context_summaries` 表（追加写入）
- **降级策略**：辅助模型不可用时降级到主模型
- **脱敏**：压缩前通过 `src/shared/utils/redact.py` 清理敏感信息

#### LongTermMemory — 长期记忆

```python
class LongTermMemory(ILongTermMemory):
    async def store(agent_id, user_id, category, content, ...)  # 存储（MySQL + ES 索引）
    async def search(agent_id, user_id, query, top_k=5, ...)    # ES 混合搜索 → MySQL LIKE 回退
    async def consolidate(agent_id, user_id, conversation_id, messages)  # 对话结束时提取
    async def replace(agent_id, user_id, category, old_content, new_content)  # 替换记忆内容（子串匹配）
    async def remove(agent_id, user_id, old_content)            # 删除记忆（子串匹配）
```

> `replace` 和 `remove` 是 `LongTermMemory` 实现类的方法，不在 `ILongTermMemory` 接口中定义。

搜索策略：ES 混合搜索（BM25 + 向量）→ MySQL LIKE 回退。

#### Security — 记忆安全扫描

```python
def scan_memory_content(content: str) -> MemorySecurityScanResult
# 检测：注入攻击、数据泄露、Unicode 欺骗、系统前缀注入、外泄网络等
```

### 1.3 数据模型

#### MemoryMessage — 统一内部消息模型

```python
@dataclass
class MemoryMessage:
    role: str                                  # user / assistant / system / tool
    content: Union[str, List[Dict[str, Any]]]
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    token_count: Optional[int] = None
    metadata: Dict[str, Any]
```

#### MemorySnapshot — 记忆快照

```python
@dataclass
class MemorySnapshot:
    messages: List[Dict[str, Any]]    # OpenAI 格式消息列表
    total_tokens: int
    compressed: bool = False
    compression_ratio: float = 1.0
```

#### LongTermMemoryEntry — 长期记忆条目

```python
@dataclass
class LongTermMemoryEntry:
    id: int
    agent_id: int
    user_id: int
    category: str          # preference / fact / procedure / insight
    content: str
    source_type: str = "consolidate"   # 来源类型（consolidate / manual）
    relevance_score: float
    access_count: int
    source_conversation_id: Optional[int]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
```

### 1.4 数据库表

```sql
-- agent_memories: 长期记忆
CREATE TABLE agent_memories (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    agent_id    BIGINT NOT NULL,
    user_id     BIGINT NOT NULL,
    category    VARCHAR(50) NOT NULL,     -- preference/fact/procedure/insight
    content     TEXT NOT NULL,
    source_conversation_id BIGINT,
    access_count INT DEFAULT 0,
    relevance_score FLOAT DEFAULT 0.0,
    extra_data  JSON,
    created_at  DATETIME NOT NULL,
    updated_at  DATETIME NOT NULL,
    INDEX idx_agent_user (agent_id, user_id),
    INDEX idx_category (category)
);

-- agent_context_summaries: 压缩摘要（追加写入）
CREATE TABLE agent_context_summaries (
    id                 BIGINT PRIMARY KEY AUTO_INCREMENT,
    conversation_id    BIGINT NOT NULL,
    summary_text       TEXT NOT NULL,
    compressed_count   INT DEFAULT 0,
    compression_ratio  FLOAT DEFAULT 0.0,
    token_count        INT DEFAULT 0,
    created_at         DATETIME NOT NULL,
    INDEX idx_conversation (conversation_id)
);
```

### 1.5 数据流

```
用户消息进入
      │
      ▼
MemoryManager.build_context()
      ├─ MemoryManager.prefetch() → ES 搜索相关长期记忆
      ├─ ShortTermMemory: DB 加载消息 + 工具调用
      ├─ TokenBudget 计算 token 数
      ├─ 超限？→ ContextCompressor 五阶段压缩
      │         ├─ Phase 1: 工具结果裁剪
      │         ├─ Phase 2: 尾部保护
      │         ├─ Phase 3: LLM 结构化摘要 → agent_context_summaries
      │         ├─ Phase 4: 迭代合并
      │         └─ Phase 5: 工具配对清理
      ├─ 长期记忆片段注入到 user message
      └─ StreamingContextScrubber 清理内部标签
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
              └─ Security.scan_memory_content() → 安全检查
```

---

## 二、工具系统

### 2.1 架构设计

```
┌────────────────────────────────────────────────────┐
│                    AgentEngine                      │
│                        │                            │
│                        ▼                            │
│                 ToolExecutor                        │
│              ┌────┴────┐                            │
│              │ 钩子链   │                            │
│              │ Logging  │                            │
│              │ Truncate │                            │
│              │ Budget   │                            │
│              └────┬────┘                            │
│           ┌───────┼───────┐                         │
│           ▼       ▼       ▼                         │
│      内置工具   MCP工具   记忆工具                    │
│      BaseTool   MCPClient MemoryTool               │
└────────────────────────────────────────────────────┘
```

### 2.2 数据模型

#### ToolDefinition — 统一工具定义

```python
class ToolSource(str, Enum):
    BUILTIN = "builtin"
    MCP = "mcp"
    CUSTOM = "custom"

class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, ToolParameter]
    required: List[str]
    source: ToolSource
    source_ref: Optional[str]
    timeout_ms: int = 30000
    dangerous: bool = False

    def to_openai_format(self) -> Dict[str, Any]
```

#### ToolResult — 结构化执行结果

```python
class ToolResultStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"

class ToolResult(BaseModel):
    status: ToolResultStatus = SUCCESS
    content: str = ""
    data: Optional[Dict] = None
    duration_ms: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
```

### 2.3 生命周期钩子

```python
class ToolHook(ABC):
    async def before_execute(self, tool, arguments, context) -> Optional[Dict]
    async def after_execute(self, tool, arguments, result, context) -> ToolResult
```

内置钩子：

| 钩子 | before | after | 说明 |
|------|--------|-------|------|
| `LoggingHook` | 记录工具名和来源 | 记录状态和耗时 | 结构化日志输出 |
| `ResultTruncationHook` | — | 截断超长 content | 默认上限 8000 字符 |
| `ResultBudgetHook` | — | 控制累计工具结果 Token 预算 | 防止单次对话工具结果过大 |

### 2.4 ToolExecutor — 工具执行器

```
execute(tool_name, arguments, context) → ToolResult

执行流程：

1. 查找工具定义 → ToolDefinition（LRU 缓存）
2. 运行 before_hooks
3. 路由到实际执行器：
   ├─ mcp__ 前缀 → McpClientManager.call_tool()
   └─ 其他 → 内置工具 execute()
4. asyncio.wait_for() 超时控制
5. 包装为 ToolResult
6. 运行 after_hooks
7. 返回最终 ToolResult
```

### 2.5 内置工具

| 工具名 | 文件 | 功能 |
|--------|------|------|
| `knowledge_search` | `builtins/knowledge_search.py` | 知识库语义搜索 |
| `web_search` | `builtins/web_search.py` | 网络搜索（Tavily/SerpAPI/DuckDuckGo） |
| `code_execution` | `builtins/code_execution.py` | Docker 沙盒代码执行 |
| `memory` | `builtins/memory.py` | 记忆管理（add/replace/remove），限制 50 条/用户/Agent |
| `todo` | `builtins/todo.py` | 任务追踪（跨压缩持久） |
| `read_tool_result` | `builtins/read_tool_result.py` | 读取之前工具调用的完整结果 |

---

## 三、LLM 交互层

### 3.1 设计决策

**组合优于继承**：`AgentLLM` 持有 `BaseLLM` 实例，不继承它。

```
AgentLLM (feature 层)
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

### 3.2 数据模型

#### StreamChunk — 流式输出块

```python
@dataclass
class StreamChunk:
    type: str  # content / tool_call_start / tool_call_args / tool_call_end / done
    content: str = ""
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_arguments_delta: str = ""
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
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
        self, messages, tools=None, max_tokens=4096, ...
    ) -> AgentLLMResponse
    # 非流式生成

    async def generate_stream(
        self, messages, tools=None, max_tokens=4096, ...
    ) -> AsyncGenerator[StreamChunk, None]
    # 流式生成，支持原生 OpenAI 流式 + 非 OpenAI 降级
```

---

## 四、ReAct 引擎

### 4.1 AgentEngine

```python
class AgentEngine:
    """ReAct 循环引擎"""

    async def run(self, llm_client, messages, tools, context, ...) -> AsyncGenerator[AgentEvent, None]
    # ReAct 循环：LLM 生成 → 工具调用 → 结果注入 → 再次 LLM，直到无工具调用
```

引擎负责：
1. 组装 system prompt（通过 `SystemPromptBuilder` 分层构建）
2. 将 `MemorySnapshot` 中的消息传给 `AgentLLM`
3. 流式产出 SSE 事件（content / tool_call / tool_result / reasoning / context_overflow / done / error）
4. 工具调用通过 `ToolExecutor` 执行
5. LLM 重试通过 `retry.py` 处理
6. 上下文溢出时通过 `compress_fn` 自动压缩后重试

### 4.2 PromptBuilder

```python
class SystemPromptBuilder:
    """分层 prompt 组装"""
    # 层级：基础指令 → Agent 个性 → 记忆上下文 → 工具说明
```

---

## 五、组件交互总图

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
            │  MemoryManager│   │  AgentLLM    │──→ BaseLLM (shared)
            │  STM + LTM   │   │  流式/非流式  │     │
            │  Compressor   │   │  工具调用收集  │     │
            └──────┬───────┘   └──────┬───────┘     │
                   │                  │              ▼
                   ▼                  ▼         StreamChunk 流
            MemorySnapshot    ToolExecutor            │
                   │          ┌────┼────┐             ▼
                   │          ▼    ▼    ▼      chat_service
                   │       [钩子] [路由] [结果]   直接产出 SSE
                   │          │    │    │              │
                   │       Logging Tool Result         ▼
                   │       Truncate MCP           前端 EventSource
                   │       Budget
                   ▼
            DB: agent_messages
                agent_tool_calls
                agent_memories
                agent_context_summaries
```

---

## 六、开发进度

| 组件 | 状态 | 说明 |
|------|------|------|
| 记忆接口 + 数据类 (`interfaces.py`) | ✅ 完成 | MemoryMessage、MemorySnapshot 等 |
| Token 预算 (`token_budget.py`) | ✅ 完成 | 已集成 TokenCounter |
| MemoryManager (`memory_manager.py`) | ✅ 完成 | 统一门面、冻结快照、预取 |
| 短期记忆 (`short_term.py`) | ✅ 完成 | DB 加载、消息转换、Token 计算 |
| 长期记忆 (`long_term.py`) | ✅ 完成 | ES 混合搜索 + MySQL 回退、巩固/替换/删除 |
| 长期记忆 ORM + 仓储 | ✅ 完成 | agent_memories 表 + MemoryRepository |
| ES 记忆搜索仓储 | ✅ 完成 | memory_search_repository.py |
| 五阶段压缩 (`context_compressor.py`) | ✅ 完成 | 全部 5 阶段 + 防抖动 + 摘要持久化 |
| 压缩摘要 ORM + 仓储 | ✅ 完成 | agent_context_summaries 表 |
| 上下文清理 (`context_scrubber.py`) | ✅ 完成 | SSE 输出内部标签清理 |
| 记忆安全扫描 (`security.py`) | ✅ 完成 | 注入/泄露/Unicode 等多模式检测 |
| TodoStore (`todo_store.py`) | ✅ 完成 | 跨压缩任务状态追踪 |
| 工具定义 (`definition.py`) | ✅ 完成 | ToolDefinition + to_openai_format() |
| 工具结果 (`result.py`) | ✅ 完成 | ToolResult（SUCCESS/ERROR/TIMEOUT） |
| 工具钩子 (`hooks.py`) | ✅ 完成 | Logging + Truncation + ResultBudget |
| 工具执行器 (`executor.py`) | ✅ 完成 | 路由 + 钩子 + 超时 + LRU 缓存 |
| 工具注册 (`registry.py`) | ✅ 完成 | ToolRegistry |
| 工具基类 (`base.py`) | ✅ 完成 | BaseTool |
| 6 个内置工具 (`builtins/`) | ✅ 完成 | knowledge/web/code/memory/todo/read |
| AgentLLM (`agent_llm.py`) | ✅ 完成 | 流式 + 非流式 + 降级 |
| AgentEngine (`engine.py`) | ✅ 完成 | ReAct 循环 |
| PromptBuilder (`prompt_builder.py`) | ✅ 完成 | 分层 prompt 组装 |
| 记忆管理 API | ✅ 完成 | GET/DELETE memories, GET stats |
| 记忆内置工具 (`builtins/memory.py`) | ✅ 完成 | add/replace/remove 操作 |
