# Agent 能力可插拔化优化方案（MCP / 搜索 / 工具）

## 1. 背景与目标

### 1.1 用户愿景

Agent 的能力（工具 / MCP / 搜索）应当全部**可配置、可插拔**：

1. **创建 Agent 页面**：可以选中需要的能力 —— 内置工具、MCP 服务器、搜索能力（含默认搜索供应商）。
2. **聊天页面**：对已选中的能力可以**按次决定是否开启**（开关），并可以**选择供应商**（如搜索走 tavily / serpapi / duckduckgo）。
3. 能力可插拔：新增能力不需要改 Agent 主流程代码，注册即用。

### 1.2 本文档定位

- 现状盘点（当前 agent 模块已具备什么）
- 与愿景的差距
- 目标设计（后端 API 契约、数据模型、前端 UI）
- 分阶段实施步骤、涉及文件、验证方式

> 本方案仅作为实施底稿，不涉及代码改动。实施时以当前工作区（含未提交改动）为基线叠加。

---

## 1.3 设计变更记录（2026-08，用户决策）

以下决策**推翻**了本文档后续部分的部分设计（G2 / G3），已在代码中落地：

| 决策 | 内容 | 落地情况 |
|---|---|---|
| D1：移除聊天页「联网搜索」开关 | 工具能力只在创建智能体时选择，聊天页不干涉工具可用性；`enable_web_search` 从 `AgentChatRequest` / chat 链路整体移除 | ✅ 已完成（后端 schema/routes/chat_service + 前端 AgentChatView/stores/api 同步移除；OpenAPI baseline 已重新生成） |
| D2：搜索供应商不做聊天页选择 | 不实现 G3 的供应商下拉；Agent 搜索一律按**用户首选搜索引擎配置**（`ModelConfigView`「设为首选」）→ YAML 兜底 | ✅ 已完成：`_resolve_web_search_port` 去掉「请求显式指定 provider」层，保留用户首选 → YAML 兜底；Agent 勾选 `web_search` 工具即自动启用 |

**当前最终行为**：`web_search` 工具可用性 = 创建 Agent 时是否勾选；供应商 = 用户首选（`is_primary`）→ YAML 兜底。聊天页仅保留「深度思考 / 流式输出」开关。

因此，本文档中 G2（per-request 工具/MCP 覆盖）、G3（聊天页供应商选择）、4.2.1/4.2.2 的请求覆盖设计、4.3.2 的聊天页升级设计、阶段 4 均**作废**，仅保留参考价值，不再实施。

---

## 2. 现状盘点

### 2.1 后端

**引擎层 `backend/src/engines/agent/`（纯逻辑，不碰 ORM/DB）**

| 模块 | 职责 | 现状 |
|---|---|---|
| `agent_engine.py` | ReAct 循环 + SSE 事件流（tool_call / tool_result / reasoning / content / sources / done / error） | 完整 |
| `tool/registry.py` | `ToolRegistry`：内置工具注册表，`register()` 即插拔，暴露 `/agent/tools` | 完整 |
| `tool/executor.py` | `ToolExecutor`：内置工具 / MCP 工具路由（`mcp__{server}__{tool}`），hooks 链，超时保护 | 完整 |
| `tool/builtins/` | `knowledge_search` / `web_search` / `memory` / `todo` / `code_execution` | 完整 |
| `mcp/client.py` | `McpClientManager`：stdio / streamable_http 连接、工具发现、调用自动重连 | 完整 |
| `memory/` | 三层记忆（短期 / 长期 / todo） | 完整 |

**宿主层 `backend/src/features/agent/`**

| 模块 | 职责 | 现状 |
|---|---|---|
| `models/agent.py` | `AgentDefinition`：`enabled_tools`（JSON 工具名列表）、`enabled_mcp_servers`（JSON ID 列表） | 已支持按 Agent 选中能力 |
| `models/mcp_server.py` | `AgentMcpServer`：`transport_type` / `connection_config` / `enabled` / `status` / `available_tools` | 已支持 MCP 服务器配置 |
| `services/agent_service.py` | Agent / 会话 / 消息 / 记忆 CRUD | 完整 |
| `services/chat_service.py` | 编排：会话 → 三层记忆 → ReAct → SSE；Agent 勾选 `web_search` 即启用联网搜索，按用户首选搜索引擎配置 → YAML 兜底解析端口 | 搜索已接入 |
| `services/mcp_server_service.py` | MCP CRUD / 连接 / 断开 / 刷新工具 / 测试连接 | 完整 |
| `api/routes.py` | `/agent/agents`、`/agent/agents/{id}/chat-stream`、`/agent/mcp-servers`、`/agent/tools` 等 | 完整 |
| `api/startup.py` | 注册内置工具、创建 MCP 管理器 / 工具执行器 / Agent 引擎、启动时连接系统级 MCP | 完整 |

**搜索供应商链路（已存在）**

- `shared/search_config_ports.py`：`SearchConfigPort` Protocol + `SearchCredentials`
- `features/user` 的 `SearchConfigService`：用户可配置 tavily / serpapi / duckduckgo 凭证并设首选（前端入口在「设置 → 模型配置」）
- `engines/search_ports.py`：`build_web_search_port_from_provider()` 按 provider 构造端口
- `chat_service._resolve_web_search_port()`：三层择优，均失败返回 None（工具内提示未配置）

### 2.2 前端

| 页面 | 现状 |
|---|---|
| `views/agent/AgentView.vue` | 创建/编辑弹窗可多选「启用工具」（来自 `/agent/tools`）+「MCP 服务器」（来自 `/agent/mcp-servers`）；详情页展示已选工具 / MCP |
| `views/agent/AgentChatView.vue` | 设置栏仅「深度思考 / 流式输出」两个开关（联网搜索开关已按决策 D1 移除）；搜索能力由 Agent 配置决定 |
| `stores/agent.ts` | Agent CRUD、会话、SSE 流式、MCP 管理、工具列表 |
| `api/agent.ts` | chat-stream 请求体已移除 `enable_web_search` / `search_provider`（决策 D1/D2） |

---

## 3. 差距分析

> 状态说明：G2 / G3 已按用户决策（见 1.3）**否决**，不再实施；G4 / G5 / G6 / G7 仍为待办。

| # | 用户愿景 | 现状 | 差距 | 影响 |
|---|---|---|---|---|
| G1 | 创建页可选工具 / MCP / 搜索 | 工具、MCP 可选；搜索供应商按用户首选（`ModelConfigView`「设为首选」）| ~~Agent 级默认搜索供应商~~（已否决，搜索供应商全局统一按用户首选） | 已收敛 |
| G2 | ~~聊天页可开关已选能力~~ | 已移除「联网搜索」开关 | **已否决（决策 D1）**：工具只在创建时选择，聊天页不干涉 | 不再实施 |
| G3 | ~~聊天页可选择供应商~~ | `search_provider` 已从 Agent 链路移除 | **已否决（决策 D2）**：按用户首选搜索引擎 → YAML 兜底 | 不再实施 |
| G4 | MCP 可配置可插拔（UI 可达） | 后端 API 完整，前端 **MCP 管理 UI 是死代码**（`openMcpCreateDialog` / `handleConnectServer` / `handleRefreshTools` / `handleDeleteServer` / `mcpStatusLabel` 均已定义但模板无任何触发入口） | 界面上无法添加 / 管理 MCP 服务器 | 创建页「选 MCP」实际断链（待办） |
| G5 | 可插拔健壮性 | 无 | chat 时若启用 MCP 未连接（如后端重启），`get_tools_for_servers` 静默返回空，工具缺失无提示 | 体验/可用性问题（待办） |
| G6 | 展示体验 | 无 | 详情页 MCP 显示 "Server #id"（无名称）；工具无分组；创建页能力无分类 | 体验问题（待办） |
| G7 | 能力目录统一 | `/agent/tools` + `/agent/mcp-servers` 分散 | 无统一目录端点，创建页需多次请求拼装 | 结构性问题（待办） |

---

## 4. 目标设计

### 4.1 设计原则

1. **向后兼容**：所有新增字段均为可选（`Optional` / 默认值），旧请求、旧 Agent 配置行为不变。
2. ~~**per-request 覆盖，不持久化**：聊天页开关仅影响本次请求（已与用户确认「仅当前请求生效」），不新增会话级存储。~~ **已作废（决策 D1）**：聊天页不做能力开关。
3. **宿主层负责连接保障**：MCP 懒连接在 `features/agent`（宿主）做，不违反 `features → engines → shared` 单向依赖铁律（engines 不得访问 ORM/DB）。
4. **能力即注册表项**：内置工具仍走 `ToolRegistry`；MCP 走 `McpClientManager` + `agent_mcp_servers` 表；搜索供应商走 `SearchConfigPort`。三者统一由「能力目录」端点暴露给前端。

### 4.2 后端设计

#### 4.2.1 ~~`AgentChatRequest` 扩展~~（已作废 · 决策 D1/D2）

> 原设计：为聊天页 per-request 覆盖工具/MCP、选择供应商扩展请求字段。已确认不做，`AgentChatRequest` 不新增字段（`enable_web_search` / `search_provider` 已从 Agent 链路移除）。

```python
class AgentChatRequest(BaseModel):
    # ... 现有字段不变 ...
    enable_web_search: bool = False            # 已移除（2026-08）
    search_provider: Optional[Literal["tavily", "serpapi", "duckduckgo"]] = None  # 已移除（2026-08）

    # （原设计新增项，未实施）
    enabled_tools: Optional[List[str]] = None
    enabled_mcp_servers: Optional[List[int]] = None
```

> ~~说明：`enabled_tools` 为空列表表示「本次不用任何工具」；`None` 表示跟随 Agent 配置。~~（不再适用）

#### 4.2.2 ~~`chat_service.chat_stream` 改造~~（已作废 · 决策 D1）

> 原设计的 per-request 能力覆盖已不做。**保留仍有效的部分**：`web_search_port` 的解析改为「Agent 勾选 `web_search` 即启用 → 用户首选 → YAML 兜底」（已实现，`_resolve_web_search_port` 已去掉请求级 provider 参数）。以下原设计仅存档：

1. 签名增加 `enabled_tools: Optional[List[str]]`、`enabled_mcp_servers: Optional[List[int]]`，透传自路由。
2. `_build_context` 中解析有效能力集：

```python
enabled_tools = request_enabled_tools if request_enabled_tools is not None else (agent.enabled_tools or [])
enabled_mcp_ids = request_mcp_ids if request_mcp_ids is not None else (agent.enabled_mcp_servers or [])
```

3. **MCP 懒连接保障**（宿主层，`_ensure_mcp_connected`）：

```python
async def _ensure_mcp_connected(self, user_id: int, mcp_ids: List[int]) -> None:
    """对启用的 MCP 服务器逐个检查连接，未连接则用 DB 配置重连（宿主层做，避免引擎依赖 ORM）。"""
    for sid in mcp_ids:
        if self._mcp_manager.is_connected(sid):
            continue
        server = await self._mcp_repo.get_by_id(sid)   # McpServerRepository(self.db)
        if not server or not server.enabled:
            logger.warning("启用的 MCP 服务器不存在或已禁用", server_id=sid)
            continue
        if server.user_id is not None and server.user_id != user_id:
            continue   # 越权不连接（列表由 Agent 配置产生，仍做防御）
        try:
            config = McpConnectionConfig.from_db_config(server.transport_type, server.connection_config)
            await self._mcp_manager.connect_server(sid, server.name, config)
        except Exception as e:
            logger.warning("MCP 懒连接失败", server_id=sid, error=str(e))
```

   - `AgentChatService` 构造时注入 `McpClientManager` 与 `McpServerRepository`（依赖注入在 `api/dependencies.py` 的 `get_agent_chat_service` 装配点完成）。
   - 懒连接失败不阻断对话：该服务器工具缺失，但其余能力正常。

#### 4.2.3 Agent 级搜索默认（可选增强，与 G1 对齐）

**方案 A（推荐，零迁移）**：复用 `AgentDefinition.extra_config`（JSON），约定键：

```json
{ "default_search_provider": "tavily", "default_enable_web_search": true }
```

`chat_service` 解析顺序：**请求显式参数 > Agent.extra_config 默认 > 用户首选 > YAML 兜底**。

**方案 B（显式列）**：`agent_definitions` 增加 `default_search_provider VARCHAR(20) NULL`、`default_enable_web_search BOOLEAN DEFAULT FALSE` 两列，需要迁移脚本。

> 推荐方案 A：无需 DB 迁移，`AgentCreate/Update` 透传 `extra_config` 即可；schema 上可加可选字段 `default_search_provider` 直接映射进 `extra_config` 便于前端表单绑定。

#### 4.2.4 能力目录端点（G7）

新增 `GET /agent/capabilities`（`api/routes.py`），一次返回创建页所需全部数据：

```python
class CapabilityCatalogResponse(BaseModel):
    tools: List[ToolProviderResponse]                    # 内置工具（含分组信息）
    mcp_servers: List[McpServerResponse]                 # 用户 + 系统级 MCP（含 status/available_tools 数）
    search_providers: List[SearchProviderInfo]           # 用户已配置的搜索供应商
    default_search_provider: Optional[str]              # 用户首选（供"自动"兜底展示）

class SearchProviderInfo(BaseModel):
    provider: Literal["tavily", "serpapi", "duckduckgo"]
    is_primary: bool
    # 不返回 api_key（脱敏）
```

- 数据来源：`ToolRegistry`（app.state）+ `McpServerService.list_servers` + `SearchConfigService`（经 `SearchConfigPort`）。
- 前端创建页由「3 个请求」收敛为「1 个请求」；旧端点保留兼容。

#### 4.2.5 工具分组（G6，后端只补元数据）

`ToolRegistry` 的 `BaseTool` 增加可选属性 `category`（如 `knowledge` / `search` / `memory` / `todo` / `code` / `misc`），`ToolProviderResponse` 增加 `category` 字段；MCP 服务器工具的 `category="mcp"`（由前端按来源归类，无需后端字段）。

### 4.3 前端设计

#### 4.3.1 创建页升级（`views/agent/AgentView.vue` + `stores/agent.ts` + `api/agent.ts`）

1. **能力目录接入**：新增 `agentApi.getCapabilities()`，创建页 `onMounted` 改为一次拉取目录（保留 `fetchTools/fetchMcpServers` 兼容）。
2. **工具选择分组**：`el-select` 分组（`el-option-group`），按 `category` 分组，label 带 emoji 前缀：
   - 📚 知识库（knowledge_search）
   - 🌐 搜索（web_search）
   - 🧠 记忆 / 📋 待办 / 💻 代码执行 / 🛠 其他
3. **MCP 选项增强**：显示名称 + 状态徽标（已连接/未连接/错误）+ 工具数量（`available_tools.length`）；禁用不可达（error 状态）的服务器。
4. **新增表单项**：
   - 「默认联网搜索」`el-switch` → `extra_config.default_enable_web_search`
   - 「默认搜索供应商」`el-select`（自动（用户首选）/ tavily / serpapi / duckduckgo，仅展示已配置项 + 自动）→ `extra_config.default_search_provider`
   - 编辑回显：从 `agent.extra_config` 读取。
5. **修复 MCP 管理断链（G4，必须）**：
   - 在 Agent 侧栏底部 / 详情页操作区增加「管理 MCP 服务器」按钮 → 展开/弹窗列出服务器（名称 / 传输类型 / 状态 / 工具数 / 最近错误）。
   - 每行操作：连接 / 断开 / 刷新工具 / 编辑 / 删除；顶部「新建服务器」按钮。
   - **直接复用已存在的死代码**：`openMcpCreateDialog` / `handleConnectServer` / `handleDisconnectServer` / `handleRefreshTools` / `handleDeleteServer` / `mcpStatusLabel`。
   - MCP 表单增强：stdio 时支持 `command` + `args`（数组）输入；streamable_http 时支持 `url` + 可选 `headers`；增加「测试连接」按钮（后端 `testMcpConnection` 已存在）。

#### 4.3.2 ~~聊天页升级~~（已作废 · 决策 D1/D2）

> 原设计的聊天页「联网搜索开关 + 供应商下拉 + 工具/MCP chips」全部不做。聊天页设置栏最终只保留「深度思考 / 流式输出」两个开关（已实现：`AgentChatView.vue` 移除联网搜索项）。以下原设计仅存档：

设置栏（`settings-bar`）扩展为：

```
[深度思考] [流式输出]
[联网搜索] [供应商 ▾]            ← G3：供应商下拉
[工具]   knowledge_search ✓  web_search ✓  ...   ← G2：已启用工具 chips（默认按 Agent 配置）
[MCP]    ServerA ✓  ServerB ✓                    ← G2：已启用 MCP chips
```

1. **供应商下拉**：选项 = 「自动（用户首选）」+ 用户已配置的 provider（来自能力目录）；选中值映射到 `search_provider` 请求字段；仅当「联网搜索」开启时生效并显示。
2. **工具 / MCP chips**：初始化自 `agent.enabled_tools` / `agent.enabled_mcp_servers`，点击 toggle；发送时作为 `enabled_tools` / `enabled_mcp_servers` 传入（**不传 = 跟随 Agent 配置**，与后端语义一致；注意「全部关掉」需传空数组而非不传）。
3. `handleSend` 组装：

```ts
const opts = {
  enable_thinking: enableThinking.value,
  enable_web_search: enableWebSearch.value,
  search_provider: enableWebSearch.value ? selectedSearchProvider.value : undefined,
  enabled_tools: toolToggles.value,          // 与 agent 配置不一致时才传
  enabled_mcp_servers: mcpToggles.value,     // 与 agent 配置不一致时才传
  attachmentIds: ...,
}
```

4. `stores/agent.ts` 的 `sendMessageStream` / `sendMessage` 签名与 `agentApi.chatStream` 请求体增加 `enabled_tools` / `enabled_mcp_servers` 透传。

### 4.4 关键流程

**聊天请求处理流程（改造后）**

```
AgentChatRequest
  ├─ enabled_tools? ──────────────► 覆盖 agent.enabled_tools（否则用 Agent 配置）
  ├─ enabled_mcp_servers? ────────► 覆盖 agent.enabled_mcp_servers（否则用 Agent 配置）
  ├─ enable_web_search=true ──────► _resolve_web_search_port(user_id, search_provider)
  │                                  （请求 provider → agent.extra_config 默认 → 用户首选 → YAML 兜底）
  └─ _ensure_mcp_connected(mcp_ids)（懒连接未连接的服务器，失败不阻断）
        ↓
  _build_context: resolve_tools_openai_format(enabled_tools, enabled_mcp_ids)
        ↓
  AgentEngine.run(...)  →  SSE 事件流
```

---

## 5. 实施步骤

> 顺序建议：先后端契约，再前端消费；每步可独立提交。

### 阶段 1：后端 per-request 能力覆盖（G2 后端部分）

- [ ] `schemas/agent_schema.py`：`AgentChatRequest` 增加 `enabled_tools` / `enabled_mcp_servers`（Optional，None=跟随 Agent）
- [ ] `api/routes.py`：`chat_stream` 透传两个新字段
- [ ] `services/chat_service.py`：
  - 签名 + 存储新字段
  - `_build_context` 解析「请求覆盖 or Agent 配置」
  - 新增 `_ensure_mcp_connected`（注入 `McpClientManager` + `McpServerRepository`）
- [ ] `api/dependencies.py`：`get_agent_chat_service` 装配点注入 `McpClientManager`（取自 `request.app.state.agent_mcp_manager`）
- [ ] 测试：`backend/tests/` 新增 `test_agent_chat_request_override.py` —— 覆盖不传（用 Agent 配置）/ 传列表 / 传空数组 / MCP 懒连接成功与失败不阻断

### 阶段 2：后端能力目录 + Agent 搜索默认（G1 / G7 后端部分）

- [ ] `engines/agent/tool/base.py`：`BaseTool` 增加 `category` 属性（默认 `misc`）；各 builtin 标注分类
- [ ] `schemas/agent_schema.py`：`ToolProviderResponse.category`；新增 `CapabilityCatalogResponse` / `SearchProviderInfo`
- [ ] `api/routes.py`：`GET /agent/capabilities`（组合 registry + mcp + search config）
- [ ] `AgentCreate/Update`：增加可选 `default_search_provider` 字段（映射进 `extra_config`）
- [ ] `chat_service._resolve_web_search_port`：把「agent.extra_config 默认」插入择优链（请求 provider 之后、用户首选之前）
- [ ] 测试：目录端点返回结构与脱敏；provider 择优顺序

### 阶段 3：前端创建页升级（G1 / G4 / G6 / G7 前端部分）

- [ ] `api/types.ts`：新增 `CapabilityCatalog` / `SearchProviderInfo` / `ToolProvider.category`；`api/agent.ts`：`getCapabilities()`
- [ ] `stores/agent.ts`：`fetchCapabilities()`（含搜索供应商列表）
- [ ] `views/agent/AgentView.vue`：
  - 创建/编辑弹窗：工具分组、MCP 增强展示、默认搜索供应商 + 默认开联网搜索
  - **MCP 管理面板**：接活死代码函数，新增列表 UI + 测试连接按钮 + stdio args 输入
- [ ] 验证：创建 Agent → 配置 MCP → 聊天页可见 chips

### 阶段 4：~~前端聊天页升级~~（已作废 · 决策 D1/D2）

> 聊天页不做能力开关与供应商选择。已实施的等价变更：移除 `AgentChatView.vue` 的「联网搜索」开关、`stores/agent.ts` / `api/agent.ts` 的 `enable_web_search` / `search_provider` 透传。

- [ ] ~~`stores/agent.ts` / `api/agent.ts`：透传 `enabled_tools` / `enabled_mcp_servers`~~
- [ ] ~~`views/agent/AgentChatView.vue`：设置栏供应商下拉 + 工具/MCP chips 开关~~
- [ ] ~~验证：开关影响工具可见性（工具卡片流）；供应商选择影响 `search_provider` 请求体；全部关掉传空数组~~

### 阶段 5：文档与收尾

- [ ] 更新 `docs/`（本方案结论迁移至正式文档）
- [ ] `npm run type-check && npm run lint && npm run format`（前端）
- [ ] `pytest -m "not slow"`（后端，重点跑 agent 相关）
- [ ] 按 Conventional Commits 拆分提交（`feat(agent): ...`）

---

## 6. 兼容性与风险

| 风险 | 级别 | 缓解 |
|---|---|---|
| 新增字段破坏旧前端 | 低 | 全部 Optional，缺省行为=现状 |
| `enabled_tools=[]` 语义歧义（空=全关 vs 未传=跟随 Agent） | 中 | 文档明确 + 后端用 `is not None` 判定，测试覆盖 |
| MCP 懒连接在并发下重复连接 | 低 | `McpClientManager.connect_server` 已有 `asyncio.Lock`；重复调用先断开旧连接 |
| `extra_config` 承载 Agent 默认搜索字段，编辑回显遗漏 | 中 | 创建/编辑表单统一读写 `extra_config`，阶段 3 测试回显 |
| 未提交工作区改动与本方案叠加 | 低 | 以当前工作区为基线，改动集中在同一批文件时先 review 再合并 |

## 7. 验证清单（验收标准）

> 已按决策 D1/D2 更新：聊天页不做能力开关与供应商选择。

- [ ] 创建页可选中：内置工具（分组）、MCP 服务器（名称/状态/工具数）
- [ ] Agent 勾选 `web_search` → 对话时模型可见 web_search 工具且按用户首选搜索引擎执行（首选失败 → YAML 兜底）
- [ ] Agent 未勾选 `web_search` → 对话时模型不可见该工具，无搜索描述提示词
- [ ] 聊天页设置栏仅「深度思考 / 流式输出」；请求体不含 `enable_web_search` / `search_provider`
- [ ] MCP 服务器未连接时发起对话，自动懒连接成功则工具可用；失败不阻断对话且有日志（G5 待办）
- [ ] MCP 管理面板可用：新建（stdio 含 args）/ 测试连接 / 连接 / 断开 / 刷新工具 / 编辑 / 删除（G4 待办）
