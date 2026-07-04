# 智能问答模块 API 文档

## 概述

智能问答模块提供会话消息管理、AI 对话（流式/非流式）、会话配置等功能。模块包含三个子路由：

| 子模块 | 路由前缀 | 说明 |
|-------|---------|------|
| 智能问答 | `/api/v1/qa` | 会话与消息的 CRUD 管理 |
| AI 聊天 | `/api/v1/ai-chat` | AI 对话（流式/非流式）、聊天历史、模型查询 |
| 会话配置 | `/api/v1/sessions/{session_id}/config` | 会话压缩配置管理 |

### 认证方式

所有接口（除健康检查外）均需要 JWT 认证，在请求头中携带：

```
Authorization: Bearer <token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. Token 有效期 30 分钟，过期需通过 `POST /api/v1/user/users/refresh` 刷新
3. 如指定 `space_id`，需要是该空间的成员

### 通用响应格式

**成功响应**：各接口独立定义，见具体接口说明。

**错误响应**（统一格式）：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-15T10:30:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

---

## 一、智能问答接口（`/api/v1/qa`）

### 1. 添加消息

**请求**
- 方法：POST
- URL：`/api/v1/qa/message`
- Content-Type：application/json

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| content | string | 是 | body | 消息内容（1-10000 字符） |
| role | string | 否 | body | 消息角色，可选值：`user`、`assistant`、`system`，默认 `user` |
| session_id | string | 否 | body | 会话ID（字母、数字、下划线、连字符，最大128字符）。为空时自动创建新会话 |
| kb_id | integer | 否 | body | 知识库ID（正整数） |
| space_id | integer | 否 | body | 知识空间ID。若指定则会验证用户是否为该空间成员 |

**请求示例**

```json
{
  "content": "请帮我解释一下机器学习的基本概念",
  "role": "user",
  "session_id": "chat_abc123",
  "space_id": 1,
  "kb_id": 5
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 消息唯一ID |
| content | string | 消息内容 |
| role | string | 消息角色（`user` / `assistant` / `system`） |
| user_id | integer | 所属用户ID |
| session_id | string | 所属会话ID |
| space_id | integer\|null | 关联的知识空间ID |
| kb_id | integer\|null | 关联的知识库ID |
| extra | object\|null | 扩展信息 |
| created_at | string | 创建时间（ISO 8601 格式） |

**响应示例**

```json
{
  "id": 42,
  "content": "请帮我解释一下机器学习的基本概念",
  "role": "user",
  "user_id": 1,
  "session_id": "chat_abc123",
  "space_id": 1,
  "kb_id": 5,
  "extra": null,
  "created_at": "2026-04-15T10:30:00+08:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败（如 content 为空） |
| `UNAUTHORIZED_ACCESS` | 403 | 无权访问指定知识空间 |

---

### 2. 获取会话消息列表

**请求**
- 方法：GET
- URL：`/api/v1/qa/session/{session_id}`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |

**响应参数**

返回数组，每个元素结构与 [1. 添加消息](#1-添加消息) 的响应参数一致。

**响应示例**

```json
[
  {
    "id": 40,
    "content": "你好，请介绍一下你自己",
    "role": "user",
    "user_id": 1,
    "session_id": "chat_abc123",
    "space_id": null,
    "kb_id": null,
    "extra": null,
    "created_at": "2026-04-15T10:00:00+08:00"
  },
  {
    "id": 41,
    "content": "你好！我是一个 AI 助手。",
    "role": "assistant",
    "user_id": 1,
    "session_id": "chat_abc123",
    "space_id": null,
    "kb_id": null,
    "extra": null,
    "created_at": "2026-04-15T10:00:05+08:00"
  }
]
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |

---

### 3. 获取会话列表

**请求**
- 方法：GET
- URL：`/api/v1/qa/sessions`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| limit | integer | 否 | query | 每页数量（1-100），默认 20 |
| offset | integer | 否 | query | 偏移量（>=0），默认 0 |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 会话列表 |
| items[].session_id | string | 会话唯一标识 |
| items[].preview | string | 会话预览（取第一条用户消息的前30个字符） |
| total | integer | 总会话数 |
| limit | integer | 每页数量 |
| offset | integer | 偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "session_id": "chat_abc123",
      "preview": "你好，请介绍一下你自己"
    },
    {
      "session_id": "chat_def456",
      "preview": "帮我写一个 Python 函数..."
    }
  ],
  "total": 15,
  "limit": 20,
  "offset": 0
}
```

---

### 4. 更新消息

**请求**
- 方法：PUT
- URL：`/api/v1/qa/message/{message_id}`
- Content-Type：application/json

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| message_id | integer | 是 | path | 消息ID（必须大于0） |
| content | string | 否 | body | 新消息内容（非空，传值则更新） |
| role | string | 否 | body | 新消息角色，可选值：`user`、`assistant`（传值则更新） |

> 至少需要传一个字段。

**请求示例**

```json
{
  "content": "修改后的消息内容"
}
```

**响应参数**

与 [1. 添加消息](#1-添加消息) 的响应参数一致。

**响应示例**

```json
{
  "id": 42,
  "content": "修改后的消息内容",
  "role": "user",
  "user_id": 1,
  "session_id": "chat_abc123",
  "space_id": 1,
  "kb_id": 5,
  "extra": null,
  "created_at": "2026-04-15T10:30:00+08:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MESSAGE_NOT_FOUND` | 404 | 消息不存在或不属于当前用户 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

---

### 5. 删除消息

**请求**
- 方法：DELETE
- URL：`/api/v1/qa/message/{message_id}`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| message_id | integer | 是 | path | 消息ID（必须大于0） |

**响应**

成功时返回 HTTP 204 No Content，无响应体。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MESSAGE_NOT_FOUND` | 404 | 消息不存在或不属于当前用户 |

---

### 6. 删除会话

**请求**
- 方法：DELETE
- URL：`/api/v1/qa/session/{session_id}`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |

**响应**

成功时返回 HTTP 204 No Content，无响应体。删除会话将同时删除其中所有消息。

> **注意**：会话删除后，短期内（约 1 小时内）再次查询该会话将返回 `404 SESSION_NOT_FOUND`，而非空列表。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |

---

### 7. 获取对话上下文

**请求**
- 方法：GET
- URL：`/api/v1/qa/context/{session_id}`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |
| limit | integer | 否 | query | 返回消息数量限制（1-100），默认 10 |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| context | array | 对话上下文消息列表，每项包含 role、content 等字段 |

**响应示例**

```json
{
  "context": [
    {
      "role": "user",
      "content": "你好"
    },
    {
      "role": "assistant",
      "content": "你好！有什么可以帮你的吗？"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |

---

## 二、AI 聊天接口（`/api/v1/ai-chat`）

### 8. AI 对话（非流式）

**请求**
- 方法：POST
- URL：`/api/v1/ai-chat/chat`
- Content-Type：application/json

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| content | string | 是 | body | 用户消息内容（1-10000 字符） |
| session_id | string | 否 | body | 会话ID。为空时自动创建新会话 |
| llm_model | string | 否 | body | LLM 模型名称（如 `gpt-4o`），为空使用默认配置 |
| max_tokens | integer | 否 | body | 最大生成 token 数（1-8192），默认 2048 |
| temperature | float | 否 | body | 温度参数（0.0-2.0），默认 0.7 |
| top_p | float | 否 | body | Top-P 采样参数（0.0-1.0），默认 0.8 |
| system_prompt | string | 否 | body | 系统提示词（最大4000字符），默认 `"You are a helpful assistant."` |
| enable_thinking | boolean | 否 | body | 是否开启深度思考模式（Qwen 等模型支持），默认 `false` |
| attachment_ids | array\<integer\> | 否 | body | 附件ID列表（通过上传附件接口获取） |
| enable_web_search | boolean | 否 | body | 是否启用联网搜索（默认 `false`），启用后 LLM 可自主决定搜索互联网 |

**请求示例**

```json
{
  "content": "请用简洁的语言解释什么是深度学习",
  "session_id": "chat_abc123",
  "llm_model": "gpt-4o",
  "max_tokens": 1024,
  "temperature": 0.5,
  "top_p": 0.9,
  "system_prompt": "你是一个专业的技术顾问，请用通俗易懂的语言回答问题。",
  "enable_thinking": false,
  "attachment_ids": [1, 2]
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| session_id | string | 会话ID |
| user_message | object | 用户发送的消息对象 |
| user_message.id | integer | 消息ID |
| user_message.content | string | 消息内容 |
| user_message.role | string | 消息角色（`user`） |
| user_message.created_at | string | 创建时间（ISO 8601） |
| ai_message | object | AI 回复的消息对象 |
| ai_message.id | integer | 消息ID |
| ai_message.content | string | AI 回复内容 |
| ai_message.role | string | 消息角色（`assistant`） |
| ai_message.created_at | string | 创建时间（ISO 8601） |
| conversation_history | array | 完整的对话历史记录列表 |

**响应示例**

```json
{
  "session_id": "chat_abc123",
  "user_message": {
    "id": 50,
    "content": "请用简洁的语言解释什么是深度学习",
    "role": "user",
    "created_at": "2026-04-15T10:30:00+08:00"
  },
  "ai_message": {
    "id": 51,
    "content": "深度学习是机器学习的一个子领域，通过多层神经网络来学习数据的复杂表示...",
    "role": "assistant",
    "created_at": "2026-04-15T10:30:05+08:00"
  },
  "conversation_history": [
    {
      "id": 40,
      "content": "你好",
      "role": "user",
      "created_at": "2026-04-15T10:00:00+08:00"
    },
    {
      "id": 41,
      "content": "你好！有什么可以帮你的吗？",
      "role": "assistant",
      "created_at": "2026-04-15T10:00:05+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `LLM_SERVICE_ERROR` | 500 | LLM 服务调用失败 |
| `INVALID_MESSAGE_CONTENT` | 400 | 消息内容无效 |
| `SESSION_MANAGEMENT_ERROR` | 400 | 会话管理失败 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

---

### 9. AI 对话（流式/SSE）

> **SSE（Server-Sent Events）流式接口**

**请求**
- 方法：POST
- URL：`/api/v1/ai-chat/chat-stream`
- Content-Type：application/json

**请求参数**

与 [8. AI 对话（非流式）](#8-ai-对话非流式) 的请求参数完全一致。

**请求示例**

```json
{
  "content": "请用简洁的语言解释什么是深度学习",
  "session_id": "chat_abc123",
  "llm_model": "gpt-4o",
  "max_tokens": 1024,
  "temperature": 0.5,
  "top_p": 0.9,
  "system_prompt": "你是一个专业的技术顾问。",
  "enable_thinking": false,
  "attachment_ids": [1]
}
```

**响应说明**

返回 `Content-Type: text/event-stream` 的 SSE 流式响应。

响应头：
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

**SSE 事件类型**

| 事件 | 说明 | 数据格式 |
|------|------|---------|
| `user_message` | 用户消息已保存 | `{"id": 50, "content": "...", "role": "user", "session_id": "..."}` |
| `sources` | 检索来源信息（联网搜索时返回） | `{"sources": [{"title": "...", "url": "..."}]}` |
| `reasoning` | 深度思考过程的推理片段（`enable_thinking=true` 时） | `{"content": "思考过程..."}` |
| `content` | AI 生成的文本片段（逐块推送） | `{"content": "文本片段"}` |
| `done` | 对话完成，包含完整 AI 回复 | `{"id": 51, "content": "完整回复", "role": "assistant", "session_id": "..."}` |
| `error` | 错误信息 | `{"code": "ERROR_CODE", "message": "错误描述"}` |

**SSE 数据格式**

每条事件以 `data: ` 开头，以双换行符 `\n\n` 分隔：

```
data: {"type": "user_message", "data": {"id": 50, "content": "...", "role": "user", "session_id": "chat_abc123"}}

data: {"type": "content", "data": {"content": "深度学习"}}

data: {"type": "content", "data": {"content": "是机器学习的"}}

data: {"type": "content", "data": {"content": "一个子领域..."}}

data: {"type": "done", "data": {"id": 51, "content": "深度学习是机器学习的一个子领域...", "role": "assistant", "session_id": "chat_abc123"}}

```

**前端处理示例（JavaScript）**

```javascript
const response = await fetch('/api/v1/ai-chat/chat-stream', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer <token>'
  },
  body: JSON.stringify({
    content: '请解释深度学习',
    session_id: 'chat_abc123'
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = '';

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });
  const lines = buffer.split('\n\n');
  buffer = lines.pop(); // 保留不完整的部分

  for (const line of lines) {
    if (line.startsWith('data: ')) {
      try {
        const event = JSON.parse(line.slice(6));

        switch (event.type) {
          case 'user_message':
            console.log('用户消息已保存:', event.data);
            break;
          case 'content':
            // 将 AI 文本片段追加到聊天界面
            appendToChat(event.data.content);
            break;
          case 'done':
            console.log('对话完成:', event.data);
            break;
          case 'error':
            console.error('流式错误:', event.data);
            break;
        }
      } catch (e) {
        console.error('解析 SSE 数据失败:', e);
      }
    }
  }
}
```

**前端处理示例（EventSource 不可用于 POST 请求，需使用 fetch）**

> 注意：标准 `EventSource` 仅支持 GET 请求，本接口为 POST，因此必须使用 `fetch` + `ReadableStream` 方式处理。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `LLM_SERVICE_ERROR` | 500 | LLM 服务调用失败（在流中通过 error 事件推送） |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败（在请求阶段返回） |

---

### 10. 获取聊天历史

**请求**
- 方法：GET
- URL：`/api/v1/ai-chat/chat-history`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | query | 会话ID（至少1个字符） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| session_id | string | 会话ID |
| messages | array | 消息列表 |
| messages[].id | integer | 消息ID |
| messages[].content | string | 消息内容 |
| messages[].role | string | 消息角色（`user` / `assistant` / `system`） |
| messages[].created_at | string | 创建时间（ISO 8601） |

**响应示例**

```json
{
  "session_id": "chat_abc123",
  "messages": [
    {
      "id": 40,
      "content": "你好",
      "role": "user",
      "created_at": "2026-04-15T10:00:00+08:00"
    },
    {
      "id": 41,
      "content": "你好！有什么可以帮你的吗？",
      "role": "assistant",
      "created_at": "2026-04-15T10:00:05+08:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |
| `VALIDATION_ERROR` | 422 | session_id 参数缺失或无效 |

---

### 11. 清除聊天历史

**请求**
- 方法：DELETE
- URL：`/api/v1/ai-chat/clear-chat`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | query | 会话ID（至少1个字符） |

**响应**

成功时返回 HTTP 204 No Content，无响应体。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_NOT_FOUND` | 404 | 会话不存在或不属于当前用户 |
| `VALIDATION_ERROR` | 422 | session_id 参数缺失或无效 |

---

### 12. 健康检查

> **无需认证**：此接口不需要携带 Token，用于检测服务是否运行。

**请求**
- 方法：GET
- URL：`/api/v1/ai-chat/health`

**请求参数**

无。

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| status | string | 服务状态 |
| message | string | 状态描述 |

**响应示例**

```json
{
  "status": "healthy",
  "message": "AI chat service is running"
}
```

---

### 13. 上传聊天附件

上传文档附件，用于在后续 AI 对话中附带文件。返回附件 ID，供 `chat` / `chat-stream` 接口的 `attachment_ids` 字段引用。

**请求**
- 方法：POST
- URL：`/api/v1/ai-chat/chat-attachments`
- Content-Type：multipart/form-data

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| files | file | 是 | form | 文档文件（支持 pdf/docx/txt/md，最大 20MB） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| attachment_id | integer | 附件唯一ID，用于对话请求中的 `attachment_ids` |
| filename | string | 原始文件名 |
| file_type | string | 文件类型 |
| file_size | integer | 文件大小（字节） |
| message | string | 提示信息 |

**响应示例**

```json
{
  "attachment_id": 10,
  "filename": "report.pdf",
  "file_type": "pdf",
  "file_size": 1048576,
  "message": ""
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败（文件为空、类型不支持等） |
| `INTERNAL_ERROR` | 500 | 文件上传失败 |

---

### 14. 下载聊天附件

根据附件ID下载已上传的文件。仅允许下载属于当前用户的附件。

**请求**
- 方法：GET
- URL：`/api/v1/ai-chat/chat-attachments/{attachment_id}/download`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| attachment_id | integer | 是 | path | 附件ID（必须大于0） |

**响应**

返回 `Content-Type: application/octet-stream` 的文件流（StreamingResponse）。

响应头：
```
Content-Type: application/octet-stream
Content-Disposition: attachment; filename="download"; filename*=UTF-8''<encoded_filename>
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `CHAT_ATTACHMENT_NOT_FOUND` | 404 | 附件不存在或不属于当前用户 |

---

### 15. 获取可用模型列表

**请求**
- 方法：GET
- URL：`/api/v1/ai-chat/models`

**请求参数**

无。

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| models | object | 可用模型字典，key 为模型名称 |
| models.`{model_name}`.max_tokens | integer | 默认最大生成 token 数 |
| models.`{model_name}`.temperature | float | 默认温度参数 |
| models.`{model_name}`.top_p | float | 默认 Top-P 参数 |
| models.`{model_name}`.model_type | string | 模型类型：`llm`（语言模型）或 `vlm`（视觉语言模型） |

> **注意**：响应中可能同时包含 `llm`（语言模型）和 `vlm`（视觉语言模型）类型的模型。`vlm` 模型支持图片输入等多模态能力。

**响应示例**

```json
{
  "models": {
    "gpt-4o": {
      "max_tokens": 2048,
      "temperature": 0.7,
      "top_p": 0.8,
      "model_type": "llm"
    },
    "glm-4": {
      "max_tokens": 2048,
      "temperature": 0.7,
      "top_p": 0.8,
      "model_type": "llm"
    },
    "qwen-vl-max": {
      "max_tokens": 2048,
      "temperature": 0.7,
      "top_p": 0.8,
      "model_type": "vlm"
    }
  }
}
```

---

## 三、会话配置接口（`/api/v1/sessions/{session_id}/config`）

### 16. 创建会话配置

为指定会话创建压缩配置。**压缩配置创建后不可修改，请谨慎设置。**

**请求**
- 方法：POST
- URL：`/api/v1/sessions/{session_id}/config`
- Content-Type：application/json

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |
| compression | object | 否 | body | 压缩配置对象（不传则使用默认值创建） |
| compression.enable_compression | boolean | 否 | body | 是否启用压缩，默认 `true` |
| compression.strategy | string | 否 | body | 压缩策略，可选值：`summary`、`sliding_window`、`keep_recent`、`truncate`，默认 `summary` |
| compression.threshold | integer | 否 | body | 触发压缩的 token 阈值（500-10000），默认 3000 |
| compression.target_tokens | integer | 否 | body | 压缩后的目标 token 数（100-2000），默认 500 |
| compression.keep_recent | integer | 否 | body | 保留的最近消息数（0-10），默认 2 |
| compression.custom_prompt | string\|null | 否 | body | 自定义摘要提示词（最大2000字符），默认 `null` |

**请求示例**

```json
{
  "compression": {
    "enable_compression": true,
    "strategy": "summary",
    "threshold": 3000,
    "target_tokens": 500,
    "keep_recent": 2,
    "custom_prompt": "请对以下对话进行摘要，保留关键信息"
  }
}
```

**响应**

成功时返回 **HTTP 201 Created**。

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 配置记录ID |
| session_id | string | 会话ID |
| user_id | integer | 所属用户ID |
| compression_config | object | 压缩配置详情（完整对象） |
| compression_config.enable_compression | boolean | 是否启用压缩 |
| compression_config.strategy | string | 压缩策略 |
| compression_config.threshold | integer | 触发压缩的 token 阈值 |
| compression_config.target_tokens | integer | 压缩后的目标 token 数 |
| compression_config.keep_recent | integer | 保留的最近消息数 |
| compression_config.custom_prompt | string\|null | 自定义摘要提示词 |
| created_at | string\|null | 创建时间（ISO 8601） |
| updated_at | string\|null | 更新时间（ISO 8601） |

**响应示例**

```json
{
  "id": 1,
  "session_id": "chat_abc123",
  "user_id": 1,
  "compression_config": {
    "enable_compression": true,
    "strategy": "summary",
    "threshold": 3000,
    "target_tokens": 500,
    "keep_recent": 2,
    "custom_prompt": "请对以下对话进行摘要，保留关键信息"
  },
  "created_at": "2026-04-15T10:30:00+08:00",
  "updated_at": null
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_CONFIG_ALREADY_EXISTS` | 409 | 该会话已存在配置（不可重复创建） |
| `UNAUTHORIZED_ACCESS` | 403 | 无权为此会话创建配置（会话属于其他用户） |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

---

### 17. 获取会话配置

**请求**
- 方法：GET
- URL：`/api/v1/sessions/{session_id}/config`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |

**响应参数**

与 [16. 创建会话配置](#16-创建会话配置) 的响应参数一致。

**响应示例**

```json
{
  "id": 1,
  "session_id": "chat_abc123",
  "user_id": 1,
  "compression_config": {
    "enable_compression": true,
    "strategy": "summary",
    "threshold": 3000,
    "target_tokens": 500,
    "keep_recent": 2,
    "custom_prompt": null
  },
  "created_at": "2026-04-15T10:30:00+08:00",
  "updated_at": null
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `SESSION_CONFIG_NOT_FOUND` | 404 | 会话配置不存在 |
| `UNAUTHORIZED_ACCESS` | 403 | 无权访问此会话配置 |

---

### 18. 删除会话配置

**请求**
- 方法：DELETE
- URL：`/api/v1/sessions/{session_id}/config`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| session_id | string | 是 | path | 会话ID（至少1个字符） |

**响应**

成功时返回 HTTP 204 No Content，无响应体。

> 如果配置不存在，也会返回 204（幂等操作）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `UNAUTHORIZED_ACCESS` | 403 | 无权操作此会话配置 |

---

### 18. 更新会话压缩配置

更新指定会话的压缩配置，支持反复修改，不影响知识库绑定等其他配置。

**请求**
- 方法：PATCH
- URL：`/api/v1/sessions/{session_id}/config/compression-config`
- Content-Type：application/json
- 权限：需要登录

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话ID（至少1个字符） |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| compression | object | 否 | -- | 压缩配置对象 |
| compression.enable_compression | boolean | 否 | -- | 是否启用压缩 |
| compression.strategy | string | 否 | -- | 压缩策略：`summary`/`sliding_window`/`keep_recent`/`truncate` |
| compression.threshold | integer | 否 | -- | 触发压缩的 token 阈值 |
| compression.target_tokens | integer | 否 | -- | 压缩后的目标 token 数 |
| compression.keep_recent | integer | 否 | -- | 保留的最近消息数 |
| compression.custom_prompt | string\|null | 否 | -- | 自定义摘要提示词 |

**响应参数**：同 [16. 创建会话配置](#16-创建会话配置) 响应结构。

---

### 19. 更新会话 LLM 生成参数

更新指定会话的模型生成参数（max_tokens/temperature/top_p/system_prompt），支持反复修改，不影响其他配置。

**请求**
- 方法：PATCH
- URL：`/api/v1/sessions/{session_id}/config/llm-config`
- Content-Type：application/json
- 权限：需要登录

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话ID（至少1个字符） |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| llm_config | object | 否 | -- | LLM 配置对象 |
| llm_config.max_tokens | integer | 否 | 2048 | 最大生成 token 数 |
| llm_config.temperature | float | 否 | 0.7 | 温度参数 |
| llm_config.top_p | float | 否 | 0.8 | Top-P 参数 |
| llm_config.system_prompt | string | 否 | -- | 系统提示词 |

**响应参数**：同 [16. 创建会话配置](#16-创建会话配置) 响应结构。

---

### 20. 更新会话知识库绑定（会话级自动 RAG）

绑定或更新指定会话的知识库列表，开启后该会话无需每次手动指定知识库即可自动检索。独立于压缩配置，可反复修改。

**请求**
- 方法：PATCH
- URL：`/api/v1/sessions/{session_id}/config/rag-config`
- Content-Type：application/json
- 权限：需要登录

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话ID（至少1个字符） |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| rag | object | 否 | -- | RAG 配置对象 |
| rag.space_id | integer | 否 | -- | 知识空间 ID |
| rag.kb_ids | integer[] | 否 | -- | 知识库 ID 列表 |
| rag.auto_rag | boolean | 否 | false | 是否启用自动检索 |
| rag.refusal_enabled | boolean | 否 | false | 是否启用拒绝回答 |
| rag.score_threshold | float | 否 | 0.3 | 检索分数阈值 |
| rag.search_mode | string | 否 | "content_hybrid" | 检索模式 |
| rag.top_k | integer | 否 | 5 | 检索返回数量 |

**响应参数**：同 [16. 创建会话配置](#16-创建会话配置) 响应结构。

---

## 四、完整错误码汇总

### QA 模块错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `QA_ERROR` | 400 | QA 模块通用错误 |
| `DATABASE_ERROR` | 400 | 数据库操作失败 |
| `SESSION_NOT_FOUND` | 404 | 会话不存在 |
| `MESSAGE_NOT_FOUND` | 404 | 消息不存在 |
| `LLM_SERVICE_ERROR` | 500 | LLM 服务错误 |
| `INVALID_MESSAGE_CONTENT` | 400 | 消息内容无效 |
| `SESSION_MANAGEMENT_ERROR` | 400 | 会话管理失败 |
| `UNAUTHORIZED_ACCESS` | 403 | 无权访问该资源 |
| `SESSION_CONFIG_NOT_FOUND` | 404 | 会话配置不存在 |
| `SESSION_CONFIG_ALREADY_EXISTS` | 409 | 会话配置已存在 |
| `CHAT_ATTACHMENT_NOT_FOUND` | 404 | 聊天附件不存在或不属于当前用户 |

### 全局错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

---

## 五、接口总览

| 编号 | 方法 | URL | 说明 | 认证 |
|------|------|-----|------|------|
| 1 | POST | `/api/v1/qa/message` | 添加消息 | 是 |
| 2 | GET | `/api/v1/qa/session/{session_id}` | 获取会话消息列表 | 是 |
| 3 | GET | `/api/v1/qa/sessions` | 获取会话列表（分页） | 是 |
| 4 | PUT | `/api/v1/qa/message/{message_id}` | 更新消息 | 是 |
| 5 | DELETE | `/api/v1/qa/message/{message_id}` | 删除消息 | 是 |
| 6 | DELETE | `/api/v1/qa/session/{session_id}` | 删除会话 | 是 |
| 7 | GET | `/api/v1/qa/context/{session_id}` | 获取对话上下文 | 是 |
| 8 | POST | `/api/v1/ai-chat/chat` | AI 对话（非流式） | 是 |
| 9 | POST | `/api/v1/ai-chat/chat-stream` | AI 对话（流式/SSE） | 是 |
| 10 | GET | `/api/v1/ai-chat/chat-history` | 获取聊天历史 | 是 |
| 11 | DELETE | `/api/v1/ai-chat/clear-chat` | 清除聊天历史 | 是 |
| 12 | GET | `/api/v1/ai-chat/health` | 健康检查 | 否 |
| 13 | POST | `/api/v1/ai-chat/chat-attachments` | 上传聊天附件 | 是 |
| 14 | GET | `/api/v1/ai-chat/chat-attachments/{attachment_id}/download` | 下载聊天附件 | 是 |
| 15 | GET | `/api/v1/ai-chat/models` | 获取可用模型列表 | 是 |
| 16 | POST | `/api/v1/sessions/{session_id}/config` | 创建会话配置（201） | 是 |
| 17 | GET | `/api/v1/sessions/{session_id}/config` | 获取会话配置 | 是 |
| 18 | PATCH | `/api/v1/sessions/{session_id}/config/compression-config` | 更新会话压缩配置 | 是 |
| 19 | PATCH | `/api/v1/sessions/{session_id}/config/llm-config` | 更新会话 LLM 生成参数 | 是 |
| 20 | PATCH | `/api/v1/sessions/{session_id}/config/rag-config` | 更新会话知识库绑定（自动 RAG） | 是 |
| 21 | DELETE | `/api/v1/sessions/{session_id}/config` | 删除会话配置 | 是 |
