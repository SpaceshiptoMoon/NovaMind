# Agent 智能体模块 API 文档

## 概述

Agent 智能体模块提供可配置的智能体能力，支持自定义系统提示词、内置工具和外部 MCP 服务器工具集成。Agent 通过 ReAct 循环（Think → Act → Observe → Respond）执行多步推理和工具调用，以 SSE 流式返回对话过程。

模块包含五个子模块：

| 子模块 | 路由前缀 | 说明 |
|-------|---------|------|
| Agent 管理 | `/api/v1/agent/agents` | Agent 定义的 CRUD |
| Agent 对话 | `/api/v1/agent/agents/{agent_id}/chat-stream` 等 | SSE 流式对话、会话管理、消息查询 |
| MCP 服务器 | `/api/v1/agent/mcp-servers` | MCP 服务器配置管理、连接控制 |
| 工具管理 | `/api/v1/agent/tools` | 查看内置工具及其函数定义 |
| 记忆管理 | `/api/v1/agent/agents/{agent_id}/memories` | Agent 长期记忆的查看、删除与统计 |

- **认证方式**：所有接口均需 JWT 认证，请求头携带 `Authorization: Bearer <token>`
- **使用前提**：
  1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
  2. 用户只能操作自己创建的 Agent 和 MCP 服务器
- **通用 Header**：

| Header | 值 | 必填 | 说明 |
|--------|------|------|------|
| Authorization | `Bearer <token>` | 是 | JWT 访问令牌 |
| Content-Type | `application/json` | 是（POST/PUT 请求） | 请求体格式 |

### 通用响应格式

**成功响应**：各接口独立定义。

**错误响应**：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-23T10:00:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## 枚举值定义

### MCP 传输类型（transport_type）

| 值 | 说明 |
|----|------|
| `stdio` | 标准输入输出，Agent 本机启动子进程连接 MCP 服务器 |
| `streamable_http` | HTTP 流式传输，连接远程 MCP 服务器 |

### MCP 连接状态（status）

| 值 | 说明 |
|----|------|
| `disconnected` | 未连接 |
| `connecting` | 连接中 |
| `connected` | 已连接 |
| `error` | 连接失败 |

### 会话状态（status）

| 值 | 说明 |
|----|------|
| `active` | 活跃 |
| `archived` | 已归档 |
| `deleted` | 已删除 |

### 消息角色（role）

| 值 | 说明 |
|----|------|
| `user` | 用户消息 |
| `assistant` | Agent 回复 |
| `system` | 系统消息 |
| `tool` | 工具返回结果 |

### 工具调用状态（status）

| 值 | 说明 |
|----|------|
| `pending` | 待执行 |
| `running` | 执行中 |
| `completed` | 已完成 |
| `failed` | 执行失败 |

---

## 一、Agent 管理

路由前缀：`/api/v1/agent/agents`

### 1.1 创建 Agent

创建一个新的 Agent 定义。用户可自定义系统提示词、LLM 参数、启用的工具和 MCP 服务器。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/agents`
- Content-Type：`application/json`

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| name | string | 是 | - | Agent 名称（1-100字符） |
| description | string | 否 | `null` | Agent 描述 |
| system_prompt | string | 是 | - | 系统提示词（至少1字符） |
| llm_model | string | 否 | `null` | LLM 模型名称，null 则使用用户默认 |
| max_tokens | int | 否 | `4096` | 最大生成 token 数（1-32768） |
| temperature | float | 否 | `0.7` | 温度参数（0-2） |
| top_p | float | 否 | `0.8` | Top-p 采样参数（0-1） |
| max_tool_calls_per_turn | int | 否 | `10` | 每轮最大工具调用次数（1-50） |
| enabled_tools | string[] | 否 | `null` | 启用的工具名称列表，如 `["knowledge_search", "web_search"]` |
| enabled_mcp_servers | int[] | 否 | `null` | 启用的 MCP 服务器 ID 列表，如 `[1, 3]` |

**请求示例**

```json
{
  "name": "知识库助手",
  "description": "基于知识库内容回答用户问题的智能助手",
  "system_prompt": "你是一个专业的知识库助手，请根据搜索结果准确回答用户的问题。",
  "llm_model": "glm-4-flash",
  "max_tokens": 4096,
  "temperature": 0.7,
  "top_p": 0.8,
  "max_tool_calls_per_turn": 10,
  "enabled_tools": ["knowledge_search", "web_search"],
  "enabled_mcp_servers": [1]
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | Agent ID |
| user_id | int | null | 创建者用户 ID |
| name | string | Agent 名称 |
| description | string | null | Agent 描述 |
| system_prompt | string | 系统提示词 |
| llm_model | string | null | LLM 模型名称 |
| max_tokens | int | 最大 token 数 |
| temperature | float | 温度参数 |
| top_p | float | Top-p 参数 |
| max_tool_calls_per_turn | int | 每轮最大工具调用次数 |
| enabled_tools | string[] | null | 启用的工具列表 |
| enabled_mcp_servers | int[] | null | 启用的 MCP 服务器 ID |
| created_at | datetime | null | 创建时间 |
| updated_at | datetime | null | 更新时间 |

**响应示例**

```json
{
  "id": 1,
  "user_id": 1,
  "name": "知识库助手",
  "description": "基于知识库内容回答用户问题的智能助手",
  "system_prompt": "你是一个专业的知识库助手，请根据搜索结果准确回答用户的问题。",
  "llm_model": "glm-4-flash",
  "max_tokens": 4096,
  "temperature": 0.7,
  "top_p": 0.8,
  "max_tool_calls_per_turn": 10,
  "enabled_tools": ["knowledge_search", "web_search"],
  "enabled_mcp_servers": [1],
  "created_at": "2026-04-23T10:00:00",
  "updated_at": "2026-04-23T10:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |

---

### 1.2 列出 Agent

获取当前用户创建的 Agent 列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/agents`

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `20` | 返回数量（1-100） |
| offset | int | 否 | `0` | 偏移量（>=0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | Agent 列表（结构同 1.1 响应） |
| total | int | 总数 |
| limit | int | 每页数量 |
| offset | int | 偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "user_id": 1,
      "name": "知识库助手",
      "description": "基于知识库内容回答用户问题的智能助手",
      "system_prompt": "...",
      "llm_model": "glm-4-flash",
      "max_tokens": 4096,
      "temperature": 0.7,
      "top_p": 0.8,
      "max_tool_calls_per_turn": 10,
      "enabled_tools": ["knowledge_search"],
      "enabled_mcp_servers": null,
      "created_at": "2026-04-23T10:00:00",
      "updated_at": "2026-04-23T10:00:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 1.3 获取 Agent 详情

获取指定 Agent 的详细配置信息。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/agents/{agent_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**响应参数**

同 1.1 响应参数。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |

---

### 1.4 更新 Agent

更新指定 Agent 的配置。只传需要修改的字段。

**请求**
- 方法：`PUT`
- URL：`/api/v1/agent/agents/{agent_id}`
- Content-Type：`application/json`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**请求参数（Body）**

所有字段均为可选，只传需要修改的字段：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 否 | Agent 名称（1-100字符） |
| description | string | 否 | Agent 描述 |
| system_prompt | string | 否 | 系统提示词 |
| llm_model | string | 否 | LLM 模型名称 |
| max_tokens | int | 否 | 最大 token 数（1-32768） |
| temperature | float | 否 | 温度参数（0-2） |
| top_p | float | 否 | Top-p 参数（0-1） |
| max_tool_calls_per_turn | int | 否 | 每轮最大工具调用次数（1-50） |
| enabled_tools | string[] | 否 | 启用的工具列表 |
| enabled_mcp_servers | int[] | 否 | 启用的 MCP 服务器 ID |

**请求示例**

```json
{
  "name": "高级知识库助手",
  "temperature": 0.5,
  "enabled_tools": ["knowledge_search", "web_search"]
}
```

**响应参数**

同 1.1 响应参数（返回更新后的完整 Agent 信息）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |

---

### 1.5 删除 Agent

删除指定的 Agent，同时**级联删除**该 Agent 关联的所有会话、消息、工具调用记录和长期记忆。此操作不可逆。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/agent/agents/{agent_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**响应示例**

```json
{
  "success": true,
  "message": "Agent 已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |

---

## 二、Agent 对话

### 2.1 Agent 对话（SSE 流式）

向指定 Agent 发送消息，以 Server-Sent Events（SSE）流式返回对话过程。Agent 会通过 ReAct 循环自动调用工具（内置工具和 MCP 工具），逐步产出结果。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/agents/{agent_id}/chat-stream`
- Content-Type：`application/json`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| content | string | 是 | - | 用户消息内容 |
| session_id | string | 否 | `null` | 会话 ID，不传则创建新会话 |
| llm_model | string | 否 | `null` | 覆盖 Agent 配置的 LLM 模型 |
| enable_thinking | bool | 否 | `false` | 是否开启深度思考模式 |
| stream | bool | 否 | `true` | 是否流式输出 |
| attachment_ids | int[] | 否 | `null` | 附件 ID 列表（通过 chat-attachments 上传获取） |

**请求示例**

```json
{
  "content": "请帮我搜索知识库中关于 RAG 技术的内容",
  "session_id": null,
  "llm_model": null,
  "enable_thinking": false,
  "stream": true,
  "attachment_ids": null
}
```

**响应格式**

返回 `text/event-stream` 类型的流式响应。

**响应 Header**

| Header | 值 | 说明 |
|--------|------|------|
| Content-Type | `text/event-stream` | SSE 流式响应 |
| Cache-Control | `no-cache` | 禁用缓存 |
| Connection | `keep-alive` | 保持连接 |
| X-Accel-Buffering | `no` | 禁用 Nginx 缓冲 |

### SSE 事件类型

> 事件按时间顺序产出。当前引擎采用非流式生成，每次 LLM 调用返回完整响应，`content` 事件包含该轮的完整文本。多轮 ReAct 迭代中会产出多个 `content` 事件，前端需拼接。

#### session（会话信息）

对话开始时发送，包含会话标识。

```json
{
  "type": "session",
  "data": {
    "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "agent_id": 1
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.session_id | string | 会话 UUID |
| data.agent_id | int | Agent ID |

#### tool_call（工具调用通知）

Agent 决定调用工具时发送。

```json
{
  "type": "tool_call",
  "data": {
    "tool_name": "knowledge_search",
    "arguments": {"space_id": 1, "query": "RAG 技术", "top_k": 5},
    "call_id": "call_123"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.tool_name | string | 工具名称（内置工具名或 `mcp__服务器名__工具名`） |
| data.arguments | object | 调用参数 |
| data.call_id | string | 调用唯一标识 |

#### tool_result（工具执行结果）

工具执行完成后发送。

```json
{
  "type": "tool_result",
  "data": {
    "tool_name": "knowledge_search",
    "result": "根据检索结果，RAG（检索增强生成）技术是...",
    "duration_ms": 350,
    "status": "completed",
    "call_id": "call_123"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.tool_name | string | 工具名称 |
| data.result | string | 执行结果（截断至 2000 字符） |
| data.duration_ms | int | 执行耗时（毫秒） |
| data.status | string | 执行状态：`completed` / `failed` |
| data.call_id | string | 对应的调用 ID |

#### content（文本内容片段）

Agent 的文本回复。每次 LLM 调用返回该轮完整文本，多轮 ReAct 迭代中会产出多个 `content` 事件。

```json
{
  "type": "content",
  "data": {
    "content": "根据知识库中的内容，"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.content | string | 该轮完整文本（多轮迭代时需前端拼接） |

#### done（对话完成）

Agent 回复完成后发送，包含统计信息。

```json
{
  "type": "done",
  "data": {
    "message_id": 15,
    "tool_calls_count": 1,
    "total_tokens": 2350,
    "iterations": 2,
    "truncated": false
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.message_id | int | 助手消息 ID |
| data.tool_calls_count | int | 本轮工具调用次数 |
| data.total_tokens | int | 本轮消耗的 token 总数 |
| data.iterations | int | ReAct 循环迭代次数 |
| data.truncated | bool | 是否因达到最大迭代次数被截断 |

#### error（错误信息）

发生错误时发送。

```json
{
  "type": "error",
  "data": {
    "content": "工具执行失败：知识库不存在"
  }
}
```

### 前端处理示例（JavaScript）

```javascript
async function chatStream(agentId, content, sessionId = null) {
  const response = await fetch(`/api/v1/agent/agents/${agentId}/chat-stream`, {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer <token>',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ content, session_id: sessionId })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let currentEventType = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEventType = line.slice(7).trim();
      } else if (line.startsWith('data: ') && currentEventType) {
        const data = JSON.parse(line.slice(6));

        switch (currentEventType) {
          case 'session':
            console.log('会话:', data.session_id);
            break;
          case 'tool_call':
            console.log(`调用工具: ${data.tool_name}`, data.arguments);
            break;
          case 'tool_result':
            console.log(`工具结果: ${data.tool_name} (${data.duration_ms}ms)`);
            break;
          case 'content':
            document.getElementById('reply').textContent += data.content;
            break;
          case 'done':
            console.log('完成，token:', data.total_tokens, '截断:', data.truncated);
            break;
          case 'error':
            console.error('错误:', data.content);
            break;
        }
        currentEventType = '';
      }
    }
  }
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在 |
| AGENT_ERROR | 500 | Agent 执行异常 |
| SANDBOX_NOT_AVAILABLE | 503 | 代码执行沙箱不可用（Docker 未启动或未安装） |
| SANDBOX_TIMEOUT | 408 | 代码执行超时 |
| SANDBOX_EXECUTION_ERROR | 500 | 代码执行异常 |
| SANDBOX_UNSUPPORTED_LANGUAGE | 422 | 不支持的编程语言 |
| SANDBOX_ERROR | 500 | 沙箱其他错误 |

> **注意**：运行时错误通过 SSE `error` 事件推送。HTTP 层面的错误（认证失败、参数校验失败）仍以标准 JSON 错误格式返回。沙箱相关错误在 Agent 启用了代码执行工具时可能通过 SSE `error` 事件推送。

---

### 2.2 列出对话

获取指定 Agent 下的对话列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/agents/{agent_id}/sessions`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `20` | 返回数量（1-100） |
| offset | int | 否 | `0` | 偏移量（>=0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 会话列表 |
| items[].id | int | 会话数据库 ID |
| items[].user_id | int | 用户 ID |
| items[].agent_id | int | Agent ID |
| items[].session_id | string | 会话 UUID |
| items[].title | string | null | 会话标题 |
| items[].status | string | 会话状态 |
| items[].message_count | int | 消息数量 |
| items[].total_tokens_used | int | 总 token 消耗 |
| items[].created_at | datetime | null | 创建时间 |
| items[].updated_at | datetime | null | 更新时间 |
| total | int | 总数 |
| limit | int | 每页数量 |
| offset | int | 偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "user_id": 1,
      "agent_id": 1,
      "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "title": "关于 RAG 技术的讨论",
      "status": "active",
      "message_count": 6,
      "total_tokens_used": 4500,
      "created_at": "2026-04-23T10:00:00",
      "updated_at": "2026-04-23T10:05:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 2.3 获取对话详情

获取指定会话的详细信息。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/sessions/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应参数**

同 2.2 中 `items[]` 内的单个会话结构。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

### 2.4 获取对话消息

获取指定会话的消息列表，包含用户消息、Agent 回复和工具结果。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/sessions/{session_id}/messages`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `50` | 返回数量（1-200） |
| offset | int | 否 | `0` | 偏移量（>=0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 消息列表 |
| items[].id | int | 消息 ID |
| items[].conversation_id | int | 会话数据库 ID |
| items[].role | string | 消息角色：`user`/`assistant`/`system`/`tool` |
| items[].content | string | null | 消息内容 |
| items[].tool_call_id | string | null | 工具调用 ID（role=tool 时有值） |
| items[].tool_name | string | null | 工具名称（role=tool 时有值） |
| items[].token_count | int | null | Token 数量 |
| items[].created_at | datetime | null | 创建时间 |
| total | int | 消息总数 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "conversation_id": 1,
      "role": "user",
      "content": "请搜索 RAG 相关内容",
      "tool_call_id": null,
      "tool_name": null,
      "token_count": null,
      "created_at": "2026-04-23T10:00:00"
    },
    {
      "id": 2,
      "conversation_id": 1,
      "role": "assistant",
      "content": null,
      "tool_call_id": null,
      "tool_name": null,
      "token_count": null,
      "created_at": "2026-04-23T10:00:01"
    },
    {
      "id": 3,
      "conversation_id": 1,
      "role": "tool",
      "content": "RAG（检索增强生成）技术是...",
      "tool_call_id": "call_1",
      "tool_name": "knowledge_search",
      "token_count": null,
      "created_at": "2026-04-23T10:00:02"
    },
    {
      "id": 4,
      "conversation_id": 1,
      "role": "assistant",
      "content": "根据知识库的检索结果，RAG 技术是...",
      "tool_call_id": null,
      "tool_name": null,
      "token_count": 500,
      "created_at": "2026-04-23T10:00:03"
    }
  ],
  "total": 4
}
```

---

### 2.5 删除对话

删除指定的对话会话。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/agent/sessions/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应示例**

```json
{
  "success": true,
  "message": "对话已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

## 三、MCP 服务器管理

路由前缀：`/api/v1/agent/mcp-servers`

MCP（Model Context Protocol）服务器是 Agent 获取外部工具能力的通道。通过配置 MCP 服务器，Agent 可以调用外部服务提供的工具。

### 3.1 添加 MCP 服务器

添加一个 MCP 服务器配置。添加后服务器处于 `disconnected` 状态，需调用连接接口建立连接。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/mcp-servers`
- Content-Type：`application/json`

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| name | string | 是 | - | 服务器名称（1-100字符） |
| description | string | 否 | `null` | 服务器描述 |
| transport_type | string | 是 | - | 传输类型：`stdio` / `streamable_http` |
| connection_config | object | 是 | - | 连接配置（见下方说明） |
| enabled | bool | 否 | `true` | 是否启用 |

#### connection_config 结构

**stdio 模式**：

```json
{
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
  "env": {"NODE_OPTIONS": "--max-old-space-size=4096"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| command | string | 是 | 执行命令 |
| args | string[] | 否 | 命令参数 |
| env | object | 否 | 环境变量 |

**streamable_http 模式**：

```json
{
  "url": "http://localhost:3000/mcp",
  "headers": {"Authorization": "Bearer xxx"}
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| url | string | 是 | MCP 服务器 URL |
| headers | object | 否 | 请求头 |

**请求示例**

```json
{
  "name": "文件系统服务器",
  "description": "本地文件系统访问",
  "transport_type": "stdio",
  "connection_config": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  },
  "enabled": true
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 服务器 ID |
| user_id | int | null | 所属用户 ID |
| name | string | 服务器名称 |
| description | string | null | 服务器描述 |
| transport_type | string | 传输类型 |
| connection_config | object | 连接配置（敏感字段已脱敏，如 API Key、Token 等替换为 `***`） |
| enabled | bool | 是否启用 |
| status | string | 连接状态 |
| last_error | string | null | 最近一次错误信息 |
| available_tools | array | null | 缓存的工具列表 |
| created_at | datetime | null | 创建时间 |
| updated_at | datetime | null | 更新时间 |

**响应示例**

```json
{
  "id": 1,
  "user_id": 1,
  "name": "文件系统服务器",
  "description": "本地文件系统访问",
  "transport_type": "stdio",
  "connection_config": {
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
  },
  "enabled": true,
  "status": "disconnected",
  "last_error": null,
  "available_tools": null,
  "created_at": "2026-04-23T10:00:00",
  "updated_at": "2026-04-23T10:00:00"
}
```

---

### 3.2 列出 MCP 服务器

获取当前用户的 MCP 服务器列表（包含系统级服务器）。返回类型化的 `McpServerResponse` 列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/mcp-servers`

**响应参数**

同 3.1 响应参数（返回数组，每个元素为 `McpServerResponse` 结构）。

**响应示例**

```json
[
  {
    "id": 1,
    "user_id": 1,
    "name": "文件系统服务器",
    "description": "本地文件系统访问",
    "transport_type": "stdio",
    "connection_config": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    "enabled": true,
    "status": "connected",
    "last_error": null,
    "available_tools": [
      {"name": "read_file", "description": "读取文件内容", "inputSchema": {...}}
    ],
    "created_at": "2026-04-23T10:00:00",
    "updated_at": "2026-04-23T10:00:00"
  },
  {
    "id": 2,
    "user_id": 1,
    "name": "远程 API 服务器",
    "description": "通过 HTTP 连接的外部服务",
    "transport_type": "streamable_http",
    "connection_config": {
      "url": "http://localhost:3000/mcp",
      "headers": {
        "Authorization": "***",
        "Content-Type": "application/json"
      }
    },
    "enabled": true,
    "status": "connected",
    "last_error": null,
    "available_tools": [...]
  }
]
```

> **安全说明**：`connection_config` 中的敏感字段（包含 `password`、`secret`、`token`、`key`、`auth` 等关键词的字段）会被自动脱敏为 `***`，不会泄露原始值。

---

### 3.3 更新 MCP 服务器配置

更新指定 MCP 服务器的配置。所有字段均为可选。

**请求**
- 方法：`PUT`
- URL：`/api/v1/agent/mcp-servers/{server_id}`
- Content-Type：`application/json`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| server_id | int | 是 | MCP 服务器 ID |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 否 | 服务器名称 |
| description | string | 否 | 服务器描述 |
| transport_type | string | 否 | 传输类型 |
| connection_config | object | 否 | 连接配置 |
| enabled | bool | 否 | 是否启用 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在或无权访问 |

---

### 3.4 删除 MCP 服务器配置

删除指定的 MCP 服务器配置，会自动断开连接。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/agent/mcp-servers/{server_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| server_id | int | 是 | MCP 服务器 ID |

**响应示例**

```json
{
  "success": true,
  "message": "MCP 服务器已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在或无权访问 |

---

### 3.5 连接 MCP 服务器

连接指定的 MCP 服务器，连接成功后自动发现并缓存工具列表。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/mcp-servers/{server_id}/connect`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| server_id | int | 是 | MCP 服务器 ID |

**响应参数**

返回更新后的 MCP 服务器信息，`status` 变为 `connected`，`available_tools` 包含发现的工具列表。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在 |
| MCP_CONNECTION_ERROR | 500 | 连接失败 |

---

### 3.6 断开 MCP 服务器

断开指定 MCP 服务器的连接，清理资源。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/mcp-servers/{server_id}/disconnect`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| server_id | int | 是 | MCP 服务器 ID |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在 |

---

### 3.7 刷新 MCP 服务器工具列表

重新连接 MCP 服务器并刷新缓存的工具列表。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/mcp-servers/{server_id}/refresh-tools`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| server_id | int | 是 | MCP 服务器 ID |

**响应示例**

```json
{
  "success": true,
  "tools": [
    {"name": "read_file", "description": "读取文件内容", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
    {"name": "write_file", "description": "写入文件", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}}
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在 |
| MCP_CONNECTION_ERROR | 500 | 连接失败 |

---

### 3.8 测试 MCP 服务器连接

测试 MCP 服务器连接是否可用。不保存配置，仅测试连通性和工具发现。

**请求**
- 方法：`POST`
- URL：`/api/v1/agent/mcp-servers/test-connection`
- Content-Type：`application/json`

**请求参数（Body）**

同 3.1 的请求参数（`McpServerCreate` 结构）。

**响应示例**

```json
{
  "success": true,
  "tools_count": 2,
  "tools": ["read_file", "write_file"]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| MCP_CONNECTION_ERROR | 500 | 连接测试失败 |

---

## 四、工具管理

路由前缀：`/api/v1/agent/tools`

工具是 Agent 的内置能力模块。系统预置了以下工具，无需创建，通过 Agent 配置的 `enabled_tools` 字段启用。

### 4.1 列出可用工具

获取系统中所有注册的工具提供者及其函数定义。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/tools`

**响应参数**

返回工具提供者数组（`ToolProviderResponse`）：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| [].name | string | 工具提供者名称 |
| [].description | string | 工具提供者描述 |
| [].tools | array | 提供的函数列表（`ToolFunctionResponse`） |
| [].tools[].name | string | 函数名称 |
| [].tools[].description | string | 函数描述 |
| [].tools[].parameters | object | 函数参数 JSON Schema |
| [].system_prompt_fragment | string | 注入到系统提示词的说明片段 |

**响应示例**

```json
[
  {
    "name": "knowledge_search",
    "description": "知识库搜索工具，支持在指定知识空间中搜索文档",
    "tools": [
      {
        "name": "knowledge_search",
        "description": "搜索知识库，返回相关文档片段",
        "parameters": {
          "type": "object",
          "properties": {
            "space_id": {"type": "integer", "description": "知识空间 ID"},
            "query": {"type": "string", "description": "搜索查询"},
            "kb_id": {"type": "integer", "description": "限定知识库 ID，不传则搜索空间下所有知识库（最多3个）"},
            "top_k": {"type": "integer", "description": "返回结果数量（默认5）"},
            "search_mode": {"type": "string", "description": "搜索模式（默认 content_hybrid）"}
          },
          "required": ["space_id", "query"]
        }
      },
      {
        "name": "document_list",
        "description": "列出知识库中的文档",
        "parameters": {
          "type": "object",
          "properties": {
            "space_id": {"type": "integer", "description": "知识空间 ID"},
            "kb_id": {"type": "integer", "description": "知识库 ID"},
            "page": {"type": "integer", "description": "页码（默认1）"},
            "page_size": {"type": "integer", "description": "每页数量（默认20）"}
          },
          "required": ["space_id", "kb_id"]
        }
      }
    ],
    "system_prompt_fragment": "## 知识库搜索\n你可以使用 knowledge_search 工具搜索知识库..."
  },
  {
    "name": "web_search",
    "description": "网页搜索工具，使用 DuckDuckGo 搜索互联网信息",
    "tools": [
      {
        "name": "web_search",
        "description": "使用 DuckDuckGo 搜索网页",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "max_results": {"type": "integer", "description": "最大返回数量（默认5）"}
          },
          "required": ["query"]
        }
      }
    ],
    "system_prompt_fragment": "## 网页搜索\n你可以使用 web_search 工具搜索互联网..."
  }
]
```

---

### 4.2 获取工具详情

获取指定工具提供者的详细信息和函数定义。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/tools/{tool_name}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| tool_name | string | 是 | 工具提供者名称（如 `knowledge_search`） |

**响应参数**

同 4.1 中单个工具提供者的结构（`ToolProviderResponse`）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| TOOL_NOT_FOUND | 404 | 工具不存在 |

---

## 五、记忆管理

路由前缀：`/api/v1/agent/agents/{agent_id}/memories`

Agent 在对话过程中会自动将重要信息整合为长期记忆（如用户偏好、关键事实等），用于跨会话保持上下文。记忆管理接口提供查看、删除和统计功能。

### 5.1 列出记忆

获取指定 Agent 的长期记忆列表，支持按类别过滤和分页。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/agents/{agent_id}/memories`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| category | string | 否 | `null` | 按类别过滤记忆 |
| limit | int | 否 | `20` | 返回数量（1-100） |
| offset | int | 否 | `0` | 偏移量（>=0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 记忆列表 |
| items[].id | int | 记忆 ID |
| items[].agent_id | int | 所属 Agent ID |
| items[].user_id | int | 所属用户 ID |
| items[].category | string | 记忆类别 |
| items[].content | string | 记忆内容 |
| items[].source_type | string | 来源类型，默认 `consolidate` |
| items[].source_conversation_id | int | null | 来源会话 ID |
| items[].access_count | int | 访问次数 |
| items[].created_at | datetime | null | 创建时间 |
| items[].updated_at | datetime | null | 更新时间 |
| total | int | 总数 |
| limit | int | 每页数量 |
| offset | int | 偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "agent_id": 1,
      "user_id": 1,
      "category": "user_preference",
      "content": "用户偏好使用中文回答问题",
      "source_type": "consolidate",
      "source_conversation_id": 5,
      "access_count": 3,
      "created_at": "2026-04-23T10:00:00",
      "updated_at": "2026-04-23T10:30:00"
    },
    {
      "id": 2,
      "agent_id": 1,
      "user_id": 1,
      "category": "key_fact",
      "content": "用户的项目使用 FastAPI + Vue 3 技术栈",
      "source_type": "consolidate",
      "source_conversation_id": 5,
      "access_count": 1,
      "created_at": "2026-04-23T10:05:00",
      "updated_at": "2026-04-23T10:05:00"
    }
  ],
  "total": 2,
  "limit": 20,
  "offset": 0
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |

---

### 5.2 删除记忆

删除指定的长期记忆。此操作不可逆。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/agent/agents/{agent_id}/memories/{memory_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |
| memory_id | int | 是 | 记忆 ID |

**响应示例**

```json
{
  "success": true,
  "message": "记忆已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |
| MEMORY_NOT_FOUND | 404 | 记忆不存在 |

---

### 5.3 记忆统计

获取指定 Agent 的记忆统计信息，包括总数、按类别分组计数和最近创建的记忆。

**请求**
- 方法：`GET`
- URL：`/api/v1/agent/agents/{agent_id}/memories/stats`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | Agent ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total_memories | int | 记忆总数 |
| by_category | object | 按类别分组的计数，如 `{"user_preference": 3, "key_fact": 5}` |
| recently_created | array | 最近创建的记忆列表（结构同 5.1 中 `items[]` 的 `MemoryResponse`） |

**响应示例**

```json
{
  "total_memories": 8,
  "by_category": {
    "user_preference": 3,
    "key_fact": 5
  },
  "recently_created": [
    {
      "id": 8,
      "agent_id": 1,
      "user_id": 1,
      "category": "key_fact",
      "content": "用户的项目部署在 Docker 环境中",
      "source_type": "consolidate",
      "source_conversation_id": 7,
      "access_count": 0,
      "created_at": "2026-04-23T11:00:00",
      "updated_at": "2026-04-23T11:00:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |

---

## 典型使用流程

```
1. 准备阶段
   ├─ POST /mcp-servers                    → 添加 MCP 服务器配置
   ├─ POST /mcp-servers/{id}/connect       → 连接 MCP 服务器（可选）
   └─ GET /tools                           → 查看可用工具列表

2. 创建 Agent
   ├─ POST /agents                         → 创建 Agent，配置 system_prompt、enabled_tools、enabled_mcp_servers
   └─ PUT /agents/{id}                     → 调整 Agent 配置（可选）

3. 开始对话
   ├─ POST /agents/{id}/chat-stream        → 发送消息，接收 SSE 事件流
   │   ├─ session 事件                      → 获取 session_id
   │   ├─ tool_call 事件                    → 展示工具调用过程
   │   ├─ tool_result 事件                  → 展示工具执行结果
   │   ├─ content 事件                      → 逐步展示 Agent 回复
   │   └─ done 事件                         → 对话完成
   └─ 后续对话传 session_id 继续同一会话

4. 查看历史
   ├─ GET /agents/{id}/sessions       → 列出对话
   └─ GET /sessions/{session_id}/messages → 查看消息记录

5. 记忆管理
   ├─ GET /agents/{id}/memories       → 查看 Agent 的长期记忆
   ├─ GET /agents/{id}/memories/stats → 查看记忆统计信息
   └─ DELETE /agents/{id}/memories/{mid} → 删除不需要的记忆（可选）
```

---

## 模块错误码汇总

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| AGENT_NOT_FOUND | 404 | Agent 不存在或无权访问 |
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| MEMORY_NOT_FOUND | 404 | 记忆不存在 |
| MCP_SERVER_NOT_FOUND | 404 | MCP 服务器不存在或无权访问 |
| MCP_CONNECTION_ERROR | 500 | MCP 服务器连接失败 |
| TOOL_EXECUTION_ERROR | 500 | 工具执行失败 |
| TOOL_NOT_FOUND | 404 | 工具不存在 |
| AGENT_MAX_ITERATIONS | 500 | Agent 达到最大迭代次数 |
| AGENT_ERROR | 500 | Agent 模块内部错误 |
| SANDBOX_NOT_AVAILABLE | 503 | 代码执行沙箱不可用 |
| SANDBOX_TIMEOUT | 408 | 代码执行超时 |
| SANDBOX_EXECUTION_ERROR | 500 | 代码执行异常 |
| SANDBOX_UNSUPPORTED_LANGUAGE | 422 | 不支持的编程语言 |
| SANDBOX_ERROR | 500 | 沙箱其他错误 |

---

## 架构说明

### 核心组件

Agent 模块由三个核心子系统驱动：

| 子系统 | 路径 | 说明 |
|--------|------|------|
| 记忆系统 | `core/memory/` | 包含短期记忆（对话上下文 + Token 预算 + 自动压缩）、长期记忆（跨会话知识整合）、工作记忆（任务中间状态）、上下文压缩等模块 |
| 工具系统 | `core/tool/` | 统一工具定义 + 生命周期钩子（日志/截断/超时） + 结构化结果 + 内置工具与 MCP 工具路由 |
| LLM 交互层 | `core/llm/` | AgentLLM 封装 BaseLLM，支持流式输出处理（StreamHandler） |

### 对话流程

```
用户请求 → AgentChatService
  ├─ 准备：获取 Agent 定义 → 创建/恢复会话 → 保存用户消息
  ├─ 构建上下文：ConversationMemory.build_messages()
  │   ├─ 加载 DB 消息 + 工具调用记录
  │   └─ 组装系统提示词（含工具片段、日期变量）
  ├─ ReAct 循环：AgentEngine.run()
  │   ├─ LLM 生成响应（含工具调用或纯文本）
  │   ├─ ToolExecutor 执行工具（路由至内置工具或 MCP 工具）
  │   └─ 循环直到无工具调用或达到最大迭代
  ├─ SSE 输出：格式化为前端事件（session / tool_call / tool_result / content / done）
  └─ 完成：保存 assistant 消息 → 更新统计 → 设置会话标题
```

### 内置工具

| 工具 | 函数 | 说明 |
|------|------|------|
| `knowledge_search` | `knowledge_search`、`document_list` | 知识库搜索（向量/全文/混合） |
| `web_search` | `web_search` | DuckDuckGo 网页搜索 |
| `code_execution` | `run_code` | Docker 沙箱代码执行（Python/JavaScript/Shell），需启用沙箱配置 |
