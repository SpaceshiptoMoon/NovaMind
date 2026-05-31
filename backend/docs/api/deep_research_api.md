# 深度研究模块 API 文档

## 概述

深度研究模块提供基于知识空间的智能研究能力，支持内部 RAG 检索、外部 Web 搜索及混合检索策略，通过 LLM 自动完成查询分析、任务分解、多轮检索和报告生成。

- **路由前缀**：`/api/v1/spaces/{space_id}/deep-research`
- **认证方式**：所有接口均需 JWT 认证，请求头携带 `Authorization: Bearer <token>`
- **使用前提**：
  1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
  2. `space_id` 为知识空间 ID，用户必须是该空间的成员
- **通用 Header**：

| Header | 值 | 必填 | 说明 |
|--------|------|------|------|
| Authorization | `Bearer <token>` | 是 | JWT 访问令牌（登录接口返回的 access_token） |
| Content-Type | `application/json` | 是（POST 请求） | 请求体格式 |

### 通用响应格式

**成功响应**：各接口独立定义。

**错误响应**：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-15T10:00:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## 枚举值定义

### ResearchMode（研究模式）

| 值 | 说明 |
|----|------|
| `quick` | 快速模式：depth=2，iterations=3 |
| `standard` | 标准模式：depth=3，iterations=5 |
| `deep` | 深度模式：depth=5，iterations=7 |

### SearchSource（搜索来源）

| 值 | 说明 |
|----|------|
| `internal` | 仅使用内部知识库检索 |
| `external` | 仅使用外部 Web 搜索 |
| `hybrid` | 混合检索（默认），首轮优先内部 RAG，后续迭代交替使用 |

### ExternalSearchProvider（外部搜索提供商）

| 值 | 说明 |
|----|------|
| `tavily` | Tavily 搜索服务（需 API Key） |
| `serpapi` | SerpAPI 搜索服务（需 API Key） |
| `duckduckgo` | DuckDuckGo 搜索服务（免费，默认） |

### ResearchStatus（研究状态）

| 值 | 说明 |
|----|------|
| `pending` | 待开始 |
| `running` | 运行中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

### SearchMode（内部检索模式）

| 值 | 说明 |
|----|------|
| `content_bm25` | 内容全文检索 |
| `content_vector` | 内容向量检索 |
| `content_hybrid` | 内容混合检索（默认） |
| `question_bm25` | 问题全文检索 |
| `question_vector` | 问题向量检索 |
| `question_hybrid` | 问题混合检索 |
| `all_bm25` | 全字段全文检索 |
| `all_vector` | 全字段向量检索 |
| `all_hybrid` | 全字段全算法融合 |

---

## 1. 执行深度研究（非流式）

基于知识空间执行深度研究，同步返回完整研究报告。适用于不需要实时展示进度的场景。

**请求**
- 方法：POST
- URL：`/api/v1/spaces/{space_id}/deep-research`
- Content-Type：application/json

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 知识空间 ID（需要是该空间成员） |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| query | string | 是 | - | 研究查询/问题，长度 5-2000 字符 |
| research_mode | string | 否 | `standard` | 研究模式：`quick`/`standard`/`deep` |
| search_source | string | 否 | `hybrid` | 搜索来源：`internal`/`external`/`hybrid` |
| internal_search | object | 否 | 见下方 | 内部知识库检索配置 |
| external_search | object | 否 | 见下方 | 外部 Web 搜索配置 |
| llm | object | 否 | 见下方 | LLM 模型配置 |

#### internal_search 对象

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| kb_ids | int[] \| null | 否 | `null`（全部知识库） | 指定知识库 ID 列表，为空则搜索空间下所有知识库 |
| search_mode | string | 否 | `content_hybrid` | 检索模式，见上方 SearchMode 枚举 |
| top_k | int | 否 | `10` | 每次检索返回的结果数量（1-100） |
| vector_weight | float | 否 | `0.7` | 向量检索权重（hybrid 模式，0.0-1.0） |
| bm25_weight | float | 否 | `0.3` | BM25 检索权重（hybrid 模式，0.0-1.0） |
| score_threshold | float | 否 | `0.0` | 最低分数阈值（0.0-1.0），低于此值的结果被过滤 |
| rerank_enabled | bool | 否 | `false` | 是否启用 Rerank 重排序 |
| rerank_top_k | int | 否 | `5` | Rerank 后返回的结果数量（1-20） |
| rerank_model | string \| null | 否 | `null`（用户默认） | Rerank 模型名称，为空使用用户默认 |
| query_rewrite_enabled | bool | 否 | `false` | 是否启用查询改写（HyDE 或子问题拆分） |
| query_rewrite_strategy | string | 否 | `hyde` | 查询改写策略：`hyde`（假设性文档嵌入）/`sub_query`（子问题拆分） |
| sub_query_count | int | 否 | `3` | 子问题拆分数量（2-5，strategy=sub_query 时生效） |
| query_rewrite_llm_model | string \| null | 否 | `null`（用户默认） | 查询改写使用的 LLM 模型名称，为空使用用户默认 |

> **约束**：hybrid 模式下 `vector_weight` + `bm25_weight` 应等于 1.0

#### external_search 对象

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| provider | string | 否 | `duckduckgo` | 外部搜索服务商：`tavily`/`serpapi`/`duckduckgo` |
| max_results | int | 否 | `10` | 每次搜索返回的最大结果数量（1-50） |
| search_depth | string | 否 | `basic` | 搜索深度：`basic`（快速）/`advanced`（深度，仅 Tavily 支持） |
| time_range | string \| null | 否 | `null` | 时间范围过滤：`day`/`week`/`month`/`year` |
| region | string | 否 | `us-en` | 搜索区域/语言设置 |

#### llm 对象

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| llm_model | string \| null | 否 | `null`（用户默认） | LLM 模型名称（如 gpt-4o），为空使用默认配置 |
| temperature | float | 否 | `0.7` | 温度参数（0.0-2.0） |
| top_p | float | 否 | `0.9` | Top-p 采样参数（0.0-1.0） |
| max_tokens | int | 否 | `4096` | 最大生成 Token 数（1024-16384） |

**请求示例**

```json
{
  "query": "什么是 RAG 技术？有哪些最佳实践？",
  "research_mode": "standard",
  "search_source": "hybrid",
  "internal_search": {
    "kb_ids": [1, 2],
    "search_mode": "content_hybrid",
    "top_k": 10,
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "rerank_enabled": true,
    "rerank_top_k": 5
  },
  "external_search": {
    "provider": "duckduckgo",
    "max_results": 10
  },
  "llm": {
    "llm_model": "gpt-4o",
    "temperature": 0.7,
    "max_tokens": 4096
  }
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| session_id | string | 研究会话唯一标识（32 字符 hex） |
| query | string | 原始查询 |
| research_mode | string | 研究模式 |
| search_source | string | 搜索来源 |
| external_provider | string \| null | 实际使用的外部搜索提供商 |
| status | string | 研究状态 |
| research_topic | string \| null | AI 提取的研究主题 |
| research_tasks | array \| null | 子任务列表 |
| research_tasks[].task_id | string | 任务 ID |
| research_tasks[].description | string | 任务描述 |
| research_tasks[].priority | int | 优先级 |
| research_tasks[].dependencies | string[] | 依赖的任务 ID 列表 |
| final_report | string \| null | 最终研究报告（Markdown 格式） |
| search_summary | object \| null | 搜索摘要信息 |
| search_summary.search_results | array | 搜索结果列表 |
| search_summary.search_results[].source_type | string | 来源类型：`internal`/`external` |
| search_summary.search_results[].content | string | 内容摘要 |
| search_summary.search_results[].url | string \| null | URL（外部搜索） |
| search_summary.search_results[].score | float | 相关性分数 |
| search_summary.search_results[].document_id | int \| null | 文档 ID（内部搜索） |
| search_summary.search_results[].chunk_id | int \| null | 分块 ID（内部搜索） |
| search_summary.search_results[].document_name | string \| null | 文档名称 |
| search_summary.search_results[].kb_id | int \| null | 知识库 ID（内部搜索） |
| search_summary.search_results[].kb_name | string \| null | 知识库名称 |
| search_summary.sources | string[] | 来源列表 |
| stats | object | 统计信息（动态键值对） |
| created_at | datetime | 创建时间（ISO 8601） |
| completed_at | datetime \| null | 完成时间（ISO 8601） |

**响应示例**

```json
{
  "session_id": "***REMOVED***",
  "query": "什么是 RAG 技术？有哪些最佳实践？",
  "research_mode": "standard",
  "search_source": "hybrid",
  "external_provider": "duckduckgo",
  "status": "completed",
  "research_topic": "RAG 检索增强生成技术的原理与最佳实践研究",
  "research_tasks": [
    {
      "task_id": "task_1",
      "description": "研究 RAG 技术的基本原理和核心架构",
      "priority": 1,
      "dependencies": []
    },
    {
      "task_id": "task_2",
      "description": "分析 RAG 技术的检索策略和优化方法",
      "priority": 2,
      "dependencies": []
    },
    {
      "task_id": "task_3",
      "description": "总结 RAG 技术的最佳实践和应用案例",
      "priority": 3,
      "dependencies": []
    }
  ],
  "final_report": "# RAG 检索增强生成技术研究报告\n\n## 执行摘要\n...",
  "search_summary": {
    "search_results": [
      {
        "source_type": "internal",
        "content": "RAG 技术通过将外部知识库与语言模型结合...",
        "url": null,
        "score": 0.92,
        "document_id": 5,
        "chunk_id": 12,
        "document_name": "RAG技术白皮书.pdf",
        "kb_id": 1,
        "kb_name": "AI技术文档库"
      },
      {
        "source_type": "external",
        "content": "Retrieval-Augmented Generation (RAG) combines retrieval and generation...",
        "url": "https://example.com/rag-guide",
        "score": 0.85,
        "document_id": null,
        "chunk_id": null,
        "document_name": null,
        "kb_id": null,
        "kb_name": null
      }
    ],
    "sources": [
      "https://example.com/rag-guide",
      "文档: RAG技术白皮书.pdf"
    ]
  },
  "stats": {
    "elapsed_seconds": 45,
    "internal_searches": 5,
    "external_searches": 3,
    "total_results": 25,
    "tasks_completed": 3,
    "report_length": 2850,
    "sources_count": 5
  },
  "created_at": "2026-04-15T10:00:00+08:00",
  "completed_at": "2026-04-15T10:00:45+08:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败（如 query 为空或过短） |
| INVALID_RESEARCH_QUERY | 400 | 研究查询无效（清理后内容为空或过短） |
| RESEARCH_MODE_NOT_SUPPORTED | 400 | 不支持的研究模式 |
| RESEARCH_FAILED | 500 | 研究执行失败 |
| SEARCH_PROVIDER_NOT_CONFIGURED | 400 | 外部搜索服务商未配置 API Key |
| SEARCH_PROVIDER_UNAVAILABLE | 503 | 外部搜索服务商不可用 |
| RESEARCH_SPACE_ACCESS_DENIED | 403 | 无权访问知识空间 |

---

## 2. 执行深度研究（流式 SSE）

基于知识空间执行深度研究，以 Server-Sent Events（SSE）流式返回进度和报告内容。适用于需要实时展示研究进度和报告生成过程的场景。

**请求**
- 方法：POST
- URL：`/api/v1/spaces/{space_id}/deep-research/stream`
- Content-Type：application/json

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 知识空间 ID |

**请求参数**

请求参数与 [1. 执行深度研究（非流式）](#1-执行深度研究非流式) 完全一致，参考上方请求参数表。

**响应格式**

返回 `text/event-stream` 类型的流式响应。

**响应 Header**

| Header | 值 | 说明 |
|--------|------|------|
| Content-Type | `text/event-stream` | SSE 流式响应 |
| Cache-Control | `no-cache` | 禁用缓存 |
| Connection | `keep-alive` | 保持连接 |
| X-Accel-Buffering | `no` | 禁用 Nginx 缓冲 |

### SSE 事件格式

每个事件以 `data: ` 开头，以两个换行符结尾：

```
data: {"event_type": "...", "data": {...}, "timestamp": 1713158400.0}

```

### 事件类型

#### progress（进度更新）

研究过程中各阶段的进度通知。

```json
{
  "event_type": "progress",
  "data": {
    "status": "analyzing",
    "current_step": "分析查询，提取研究主题",
    "progress_percent": 10.0,
    "completed_tasks": 0,
    "total_tasks": 0
  },
  "timestamp": 1713158400.0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.status | string | 当前阶段：`analyzing`（分析中）/`searching`（检索中）/`synthesizing`（生成报告中） |
| data.current_step | string | 当前步骤描述 |
| data.progress_percent | float | 总体进度百分比（0-100） |
| data.completed_tasks | int | 已完成任务数 |
| data.total_tasks | int | 总任务数 |

#### content（报告内容片段）

报告生成阶段，逐片段返回报告文本。

```json
{
  "event_type": "content",
  "data": {
    "chunk": "# RAG 检索增强生成技术研究报告\n\n## 执行摘要\n"
  },
  "timestamp": 1713158410.0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.chunk | string | 报告内容片段（需前端拼接为完整报告） |

#### heartbeat（心跳保活）

间隔性发送的 SSE 注释，用于保持连接活跃。

```
: heartbeat
```

> 心跳为 SSE 标准注释格式（以 `: ` 开头），不会被 EventSource 的 onmessage 回调接收，前端无需处理。

#### error（错误信息）

研究过程中发生错误时发送。

```json
{
  "event_type": "error",
  "data": {
    "message": "研究执行失败，请稍后重试",
    "session_id": "***REMOVED***"
  },
  "timestamp": 1713158420.0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.message | string | 错误描述 |
| data.session_id | string | 研究会话 ID |

#### done（研究完成）

研究成功完成后发送，包含完整报告和统计信息。

```json
{
  "event_type": "done",
  "data": {
    "session_id": "***REMOVED***",
    "final_report": "# RAG 检索增强生成技术研究报告\n\n## 执行摘要\n...",
    "stats": {
      "elapsed_seconds": 45,
      "internal_searches": 5,
      "external_searches": 3,
      "total_results": 25
    }
  },
  "timestamp": 1713158430.0
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data.session_id | string | 研究会话 ID |
| data.final_report | string | 完整的研究报告（Markdown 格式） |
| data.stats | object | 统计信息 |
| data.stats.elapsed_seconds | int | 总耗时（秒） |
| data.stats.internal_searches | int | 内部检索次数 |
| data.stats.external_searches | int | 外部搜索次数 |
| data.stats.total_results | int | 检索结果总数 |

### 前端处理示例（JavaScript）

```javascript
// 注意：POST 请求的 SSE 需使用 fetch API 手动处理
// EventSource 仅支持 GET 请求，不可用于本接口

async function streamResearch(spaceId, requestBody) {
  const response = await fetch(`/api/v1/spaces/${spaceId}/deep-research/stream`, {
    method: 'POST',
    headers: {
      'Authorization': 'Bearer <token>',
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(requestBody)
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const event = JSON.parse(line.slice(6));

        switch (event.event_type) {
          case 'progress':
            console.log(`进度: ${event.data.progress_percent}% - ${event.data.current_step}`);
            break;
          case 'content':
            // 追加报告片段到页面
            document.getElementById('report').innerHTML += event.data.chunk;
            break;
          case 'done':
            console.log('研究完成', event.data.session_id);
            break;
          case 'error':
            console.error('研究失败', event.data.message);
            break;
        }
      } else if (line.startsWith(': ')) {
        // 心跳，忽略
      }
    }
  }
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| INVALID_RESEARCH_QUERY | 400 | 研究查询无效（清理后内容为空或过短） |
| RESEARCH_MODE_NOT_SUPPORTED | 400 | 不支持的研究模式 |
| SEARCH_PROVIDER_NOT_CONFIGURED | 400 | 外部搜索服务商未配置 API Key |
| SEARCH_PROVIDER_UNAVAILABLE | 503 | 外部搜索服务商不可用 |

> **注意**：流式接口的运行时错误通过 SSE `error` 事件推送，而非 HTTP 错误响应。HTTP 层面的错误（如认证失败、参数校验失败）仍以标准 JSON 错误格式返回。

---

## 3. 获取研究历史列表

获取知识空间的研究历史记录列表。普通用户只能查看自己的研究记录，空间管理员可查看空间内所有研究记录。

**请求**
- 方法：GET
- URL：`/api/v1/spaces/{space_id}/deep-research`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 知识空间 ID（需要是该空间成员） |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| limit | int | 否 | `10` | 1-100 | 返回数量 |
| offset | int | 否 | `0` | >= 0 | 偏移量 |
| status | string | 否 | `null`（全部） | 见 ResearchStatus 枚举 | 按状态过滤：`pending`/`running`/`completed`/`failed`/`cancelled` |

> **说明**：系统通过 JWT token 识别当前用户，自动按用户角色过滤数据（管理员可看全部，普通用户仅看自己的）。

**请求示例**

```
GET /api/v1/spaces/1/deep-research?limit=10&offset=0&status=completed
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 研究列表 |
| items[].session_id | string | 研究会话 ID |
| items[].query | string | 研究查询 |
| items[].research_topic | string \| null | 研究主题 |
| items[].status | string | 研究状态 |
| items[].research_mode | string | 研究模式 |
| items[].created_at | datetime | 创建时间（ISO 8601） |
| items[].completed_at | datetime \| null | 完成时间（ISO 8601） |
| total | int | 符合条件的总记录数 |
| limit | int | 当前分页每页数量 |
| offset | int | 当前分页偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "session_id": "***REMOVED***",
      "query": "什么是 RAG 技术？有哪些最佳实践？",
      "research_topic": "RAG 检索增强生成技术的原理与最佳实践研究",
      "status": "completed",
      "research_mode": "standard",
      "created_at": "2026-04-15T10:00:00+08:00",
      "completed_at": "2026-04-15T10:00:45+08:00"
    },
    {
      "session_id": "f1e2d3c4b5a6978869504132a1b2c3d4",
      "query": "对比分析主流向量数据库的性能差异",
      "research_topic": "主流向量数据库性能对比分析",
      "status": "completed",
      "research_mode": "deep",
      "created_at": "2026-04-14T15:30:00+08:00",
      "completed_at": "2026-04-14T15:32:30+08:00"
    }
  ],
  "total": 2,
  "limit": 10,
  "offset": 0
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| SPACE_NOT_FOUND | 404 | 知识空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 无权访问该知识空间 |

---

## 4. 获取研究详情

获取指定研究会话的详细信息，包括研究主题、子任务列表、最终报告和搜索摘要。

**请求**
- 方法：GET
- URL：`/api/v1/spaces/{space_id}/deep-research/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 知识空间 ID |
| session_id | string | 是 | 研究会话 ID |

**请求示例**

```
GET /api/v1/spaces/1/deep-research/***REMOVED***
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| session_id | string | 研究会话唯一标识 |
| query | string | 原始查询 |
| research_mode | string | 研究模式 |
| search_source | string | 搜索来源 |
| external_provider | string \| null | 外部搜索提供商 |
| status | string | 研究状态 |
| research_topic | string \| null | 研究主题 |
| research_tasks | array \| null | 子任务列表 |
| research_tasks[].task_id | string | 任务 ID |
| research_tasks[].description | string | 任务描述 |
| research_tasks[].priority | int | 优先级 |
| research_tasks[].dependencies | string[] | 依赖的任务 ID 列表 |
| final_report | string \| null | 最终研究报告（Markdown 格式） |
| search_summary | object \| null | 搜索摘要信息 |
| search_summary.search_results | array | 搜索结果列表 |
| search_summary.search_results[].source_type | string | 来源类型：`internal`/`external` |
| search_summary.search_results[].content | string | 内容摘要 |
| search_summary.search_results[].url | string \| null | URL（外部搜索） |
| search_summary.search_results[].score | float | 相关性分数 |
| search_summary.search_results[].document_id | int \| null | 文档 ID（内部搜索） |
| search_summary.search_results[].chunk_id | int \| null | 分块 ID（内部搜索） |
| search_summary.search_results[].document_name | string \| null | 文档名称 |
| search_summary.search_results[].kb_id | int \| null | 知识库 ID |
| search_summary.search_results[].kb_name | string \| null | 知识库名称 |
| search_summary.sources | string[] | 来源列表 |
| stats | object | 统计信息（动态键值对） |
| created_at | datetime | 创建时间（ISO 8601） |
| completed_at | datetime \| null | 完成时间（ISO 8601） |

**响应示例**

```json
{
  "session_id": "***REMOVED***",
  "query": "什么是 RAG 技术？有哪些最佳实践？",
  "research_mode": "standard",
  "search_source": "hybrid",
  "external_provider": "duckduckgo",
  "status": "completed",
  "research_topic": "RAG 检索增强生成技术的原理与最佳实践研究",
  "research_tasks": [
    {
      "task_id": "task_1",
      "description": "研究 RAG 技术的基本原理和核心架构",
      "priority": 1,
      "dependencies": []
    },
    {
      "task_id": "task_2",
      "description": "分析 RAG 技术的检索策略和优化方法",
      "priority": 2,
      "dependencies": []
    },
    {
      "task_id": "task_3",
      "description": "总结 RAG 技术的最佳实践和应用案例",
      "priority": 3,
      "dependencies": []
    }
  ],
  "final_report": "# RAG 检索增强生成技术研究报告\n\n## 执行摘要\n\nRAG（Retrieval-Augmented Generation）是一种将信息检索与文本生成相结合的技术框架...",
  "search_summary": {
    "search_results": [
      {
        "source_type": "internal",
        "content": "RAG 技术通过将外部知识库与语言模型结合...",
        "url": null,
        "score": 0.92,
        "document_id": 5,
        "chunk_id": 12,
        "document_name": "RAG技术白皮书.pdf",
        "kb_id": 1,
        "kb_name": "AI技术文档库"
      },
      {
        "source_type": "external",
        "content": "Retrieval-Augmented Generation (RAG) combines retrieval and generation...",
        "url": "https://example.com/rag-guide",
        "score": 0.85,
        "document_id": null,
        "chunk_id": null,
        "document_name": null,
        "kb_id": null,
        "kb_name": null
      }
    ],
    "sources": [
      "https://example.com/rag-guide",
      "文档: RAG技术白皮书.pdf",
      "https://example.com/rag-best-practices"
    ]
  },
  "stats": {
    "elapsed_seconds": 45,
    "internal_searches": 5,
    "external_searches": 3,
    "total_results": 25,
    "tasks_completed": 3,
    "report_length": 2850,
    "sources_count": 5
  },
  "created_at": "2026-04-15T10:00:00+08:00",
  "completed_at": "2026-04-15T10:00:45+08:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| RESEARCH_NOT_FOUND | 404 | 研究会话不存在 |
| RESEARCH_SPACE_ACCESS_DENIED | 403 | 无权访问该知识空间（研究会话不属于当前空间） |
| RESEARCH_ACCESS_DENIED | 403 | 无权访问该研究记录（非本人且非管理员） |
| SPACE_NOT_FOUND | 404 | 知识空间不存在 |

---

## 5. 删除研究记录

删除指定研究会话记录。普通用户只能删除自己的研究，空间管理员可删除空间内任意研究。运行中的研究不允许删除。

**请求**
- 方法：DELETE
- URL：`/api/v1/spaces/{space_id}/deep-research/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 知识空间 ID |
| session_id | string | 是 | 研究会话 ID |

**请求示例**

```
DELETE /api/v1/spaces/1/deep-research/***REMOVED***
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 操作结果消息 |

**响应示例**

```json
{
  "message": "研究已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| RESEARCH_NOT_FOUND | 404 | 研究会话不存在或无权访问 |
| RESEARCH_ACCESS_DENIED | 403 | 无权删除此研究记录（非本人且非管理员） |
| RESEARCH_RUNNING | 409 | 研究正在运行中，无法删除 |
| RESEARCH_SPACE_ACCESS_DENIED | 403 | 无权访问知识空间 |
| SPACE_NOT_FOUND | 404 | 知识空间不存在 |

---

## 权限说明

| 角色 | 查看研究列表 | 查看研究详情 | 删除研究 |
|------|-------------|-------------|---------|
| 系统管理员 | 所有空间所有研究 | 所有空间所有研究 | 所有空间所有研究 |
| 空间管理员 | 当前空间所有研究 | 当前空间所有研究 | 当前空间所有研究 |
| 普通成员 | 仅自己的研究 | 仅自己的研究 | 仅自己的研究 |
| 公开空间访客 | 仅自己的研究 | 仅自己的研究 | 仅自己的研究 |

---

## 研究流程说明

深度研究的工作流程如下：

1. **创建会话**：创建研究会话记录，初始状态为 `pending`
2. **分析查询**：LLM 分析用户查询，提取研究主题，状态变为 `running`
3. **分解任务**：根据研究模式（quick/standard/deep）将主题分解为多个子任务
4. **多轮检索**：对每个子任务执行多轮迭代检索
   - 首轮优先使用内部 RAG 检索
   - 后续迭代交替使用内部/外部搜索（hybrid 模式）
   - 结果充分时提前结束迭代
5. **生成报告**：LLM 综合检索结果生成结构化研究报告
6. **完成存储**：持久化报告和统计信息，状态变为 `completed`

> **耗时说明**：快速模式通常 10-30 秒，标准模式 30-60 秒，深度模式 1-3 分钟。实际耗时取决于查询复杂度和 LLM 响应速度。
