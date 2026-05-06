# 知识空间模块 API 文档

## 概述

知识空间模块提供知识空间的创建与管理、知识库管理、文档上传与解析、成员权限管理以及多策略检索功能。

### 认证方式

所有接口均需要 JWT 认证，在请求头中携带：
```
Authorization: Bearer <access_token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. 空间相关操作需要用户是目标空间的成员
3. 部分操作（如删除、邀请）需要管理员（ADMIN）角色

### 通用响应格式

**成功响应**：直接返回数据对象或列表，无额外包裹层。例如创建空间直接返回 `SpaceResponse` 对象。

**错误响应**
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-15T12:00:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| RESOURCE_NOT_FOUND | 404 | 资源不存在 |
| ACCESS_DENIED | 403 | 访问被拒绝 |
| INVALID_PARAMETER | 400 | 参数无效 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## 一、知识空间管理

路由前缀：`/api/v1/spaces`

### 1.1 创建知识空间

> **前提**：需要先登录获取 JWT Token。创建者自动成为空间管理员（ADMIN）。

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces`
- Content-Type：`application/json`

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 空间名称（1-100 字符） |
| visibility | integer | 否 | 可见性：0-私有（默认），1-团队，2-公开 |
| config | object | 否 | 空间配置 |

**config 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| description | string | 否 | 空间描述（最多 2000 字符，默认空字符串） |
| tags | string[] | 否 | 标签列表（最多 20 个） |
| embedding | object | 否 | Embedding 配置（空间级别，所有知识库共享） |
| storage | object | 否 | 存储配置（JSON 序列化后不超过 10KB） |
| ui | object | 否 | UI 配置（JSON 序列化后不超过 10KB） |
| defaults | object | 否 | 默认配置（JSON 序列化后不超过 10KB） |
| limits | object | 否 | 限制配置（JSON 序列化后不超过 10KB） |

**config.embedding 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| model | string | 否 | Embedding 模型名称（填写用户可用的模型名称即可） |
| batch_size | integer | 否 | 批处理大小（1-128，默认 32） |
| normalize | boolean | 否 | 是否归一化（默认 true） |

> **自动填充机制**：
> - 如果未传 `config.embedding`，后端会自动从用户的可用模型列表中选取第一个 Embedding 模型作为默认值，并自动读取其维度
> - 如果传了 `config.embedding.model`，后端会自动从模型配置表读取真实 `dimension` 并写入空间配置，前端无需（也不应）传入 `dimension`

**请求示例**
```json
{
  "name": "技术文档库",
  "visibility": 1,
  "config": {
    "description": "团队共享的技术文档空间",
    "tags": ["技术", "文档"],
    "embedding": {
      "model": "bge-large-zh"
    }
  }
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 空间 ID |
| name | string | 空间名称 |
| owner_id | integer | 创建者 ID |
| visibility | integer | 可见性：0-私有，1-团队，2-公开 |
| config | object | 空间配置 |
| status | integer | 状态：1-活跃，2-归档，3-删除 |
| created_at | string | 创建时间（ISO 8601） |
| updated_at | string | 更新时间（ISO 8601） |

**响应示例**
```json
{
  "id": 1,
  "name": "技术文档库",
  "owner_id": 1,
  "visibility": 1,
  "config": {
    "description": "团队共享的技术文档空间",
    "tags": ["技术", "文档"],
    "embedding": {
      "model": "bge-large-zh",
      "dimension": 1024,
      "batch_size": 32,
      "normalize": true
    }
  },
  "status": 1,
  "created_at": "2026-04-15T10:00:00",
  "updated_at": "2026-04-15T10:00:00"
}
```

> `dimension` 由后端自动填入，前端无需传入。如果请求中未指定 `embedding`，响应中的 `config.embedding` 包含后端自动选择的默认模型及其维度。

---

### 1.2 获取我的空间列表

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces`
- Content-Type：无

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| skip | integer | 否 | query | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | query | 返回的最大记录数（默认 100，1-1000） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 空间列表（同 1.1 响应结构） |
| total | integer | 总数 |
| skip | integer | 跳过数量 |
| limit | integer | 返回数量 |

**响应示例**
```json
{
  "items": [
    {
      "id": 1,
      "name": "技术文档库",
      "owner_id": 1,
      "visibility": 1,
      "config": null,
      "status": 1,
      "created_at": "2026-04-15T10:00:00",
      "updated_at": "2026-04-15T10:00:00"
    }
  ],
  "total": 1,
  "skip": 0,
  "limit": 100
}
```

---

### 1.3 获取公开空间列表

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/public`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| skip | integer | 否 | query | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | query | 返回的最大记录数（默认 100，1-1000） |

**响应参数**：同 1.2 响应结构

---

### 1.4 搜索知识空间

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/search`

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| keyword | string | 是 | query | 搜索关键词（1-100 字符） |
| skip | integer | 否 | query | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | query | 返回的最大记录数（默认 100，1-1000） |

**响应参数**：同 1.2 响应结构

---

### 1.5 获取空间详情

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**响应参数**：同 1.1 响应结构（单个空间对象）

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 无权访问该空间 |

---

### 1.6 更新空间设置

**请求**
- 方法：`PUT`
- URL：`/api/v1/spaces/{space_id}`
- Content-Type：`application/json`
- 权限要求：空间管理员

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 否 | 空间名称（1-100 字符） |
| visibility | integer | 否 | 可见性：0-私有，1-团队，2-公开 |
| config | object | 否 | 空间配置（同 1.1 config 结构） |

**响应参数**：同 1.1 响应结构

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 需要管理员权限 |

---

### 1.7 删除知识空间

> **级联清理**：删除空间时会依次执行以下清理操作：
> 1. 软删除空间及关联的所有知识库、文档（MySQL）
> 2. 硬删除所有成员记录（MySQL）
> 3. 硬删除所有审计日志（MySQL）
> 4. 清理 Redis 检索缓存
> 5. 删除 Elasticsearch 空间索引（含所有向量数据）
> 6. 删除 MinIO 中的所有文件
>
> 其中步骤 1-4 在同一数据库事务中完成，步骤 5-6 为异步操作，失败不会阻塞删除。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}`
- 权限要求：空间管理员

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 响应消息 |

**响应示例**
```json
{
  "success": true,
  "message": "空间已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 需要管理员权限 |

---

### 1.8 获取空间配置

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/config`
- 权限要求：空间成员

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| space_id | integer | 空间 ID |
| name | string | 空间名称 |
| config | object | 空间完整配置 |
| config.description | string | 空间描述 |
| config.tags | string[] | 标签列表 |
| config.embedding | object | Embedding 模型配置（空间级别） |
| config.embedding.model | string | Embedding 模型名称 |
| config.embedding.dimension | integer | 向量维度（后端自动从模型配置表检测并写入，前端不可传入） |
| config.embedding.batch_size | integer | 批处理大小 |
| config.embedding.normalize | boolean | 是否归一化 |
| config.defaults | object | 默认配置 |
| config.limits | object | 限制配置 |
| config.storage | object | 存储配置 |
| config.ui | object | UI 配置 |
| stats | object | 统计信息 |
| stats.kb_count | integer | 知识库数量 |
| stats.document_count | integer | 文档数量 |
| stats.chunk_count | integer | 分块数量 |
| stats.total_size_mb | float | 存储大小（MB） |
| stats.member_count | integer | 成员数量 |

**响应示例**
```json
{
  "space_id": 1,
  "name": "产品部知识库",
  "config": {
    "description": "产品部文档空间",
    "tags": ["产品", "文档"],
    "embedding": {
      "model": "text-embedding-v2",
      "dimension": 1024,
      "batch_size": 32,
      "normalize": true
    },
    "defaults": {},
    "limits": {},
    "storage": {},
    "ui": {}
  },
  "stats": {
    "kb_count": 3,
    "document_count": 15,
    "chunk_count": 230,
    "total_size_mb": 12.5,
    "member_count": 5
  }
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 无权访问该空间 |

---

### 1.9 更新空间配置（部分更新）

**请求**
- 方法：`PATCH`
- URL：`/api/v1/spaces/{space_id}/config`
- Content-Type：`application/json`
- 权限要求：空间管理员（ADMIN）

**说明**：深度合并，只传需要修改的字段，未传的字段保持不变。修改 `embedding.model` 时，后端会自动从模型配置表读取真实维度并回填 `dimension`，前端无需传入。如果空间中存在已处理的文档，修改 embedding 模型会被拒绝。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| description | string | 否 | 空间描述（最多 2000 字符） |
| tags | string[] | 否 | 标签列表（最多 20 个） |
| embedding | object | 否 | Embedding 配置（修改 model 时空间中不能有已处理文档，dimension 由后端自动回填） |
| defaults | object | 否 | 默认配置（JSON 序列化后不超过 10KB） |
| limits | object | 否 | 限制配置（JSON 序列化后不超过 10KB） |

**请求示例 1 — 修改描述和标签**
```json
{
  "description": "新的空间描述",
  "tags": ["新标签"]
}
```

**请求示例 2 — 设置 Embedding 模型**（dimension 自动回填，无需传入）
```json
{
  "embedding": {
    "model": "bge-large-zh"
  }
}
```

**请求示例 3 — 仅修改 batch_size**（深度合并，不会覆盖 model 和 dimension）
```json
{
  "embedding": {
    "batch_size": 64
  }
}
```

**响应参数**：同 1.8 响应结构

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ACCESS_DENIED | 403 | 需要管理员权限 |
| INVALID_PARAMETER | 400 | 存在已处理文档时修改 Embedding 模型 |

---

## 二、知识库管理

路由前缀：`/api/v1/spaces/{space_id}/knowledge-bases`

**权限说明**

| 操作 | 最低角色 |
|------|---------|
| 查看列表/详情/配置 | 成员（VIEWER, 0） |
| 创建/编辑/更新配置 | 编辑者（EDITOR, 1） |
| 删除知识库 | 管理员（ADMIN, 2） |

### 2.1 获取知识库列表

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**查询参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | integer | 否 | 状态过滤：1-活跃，2-已归档 |
| skip | integer | 否 | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | 返回的最大记录数（默认 100，1-1000） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 知识库列表 |
| items[].id | integer | 知识库 ID |
| items[].space_id | integer | 所属空间 ID |
| items[].name | string | 知识库名称 |
| items[].creator_id | integer | 创建者 ID |
| items[].config | object | 知识库配置 |
| items[].storage | object | 存储配置 |
| items[].status | integer | 状态：0-已删除，1-活跃，2-已归档 |
| items[].stats | object | 实时统计信息（从数据库聚合，排除软删除文档） |
| items[].stats.document_count | integer | 文档总数（排除软删除和失败） |
| items[].stats.chunk_count | integer | 分块总数（已解析文档的分块数之和） |
| items[].stats.total_size_mb | float | 存储大小（MB） |
| items[].stats.uploaded_documents | integer | 待处理文档数 |
| items[].stats.completed_documents | integer | 已完成文档数 |
| items[].stats.failed_documents | integer | 失败文档数 |
| items[].created_at | string | 创建时间 |
| items[].updated_at | string | 更新时间 |
| total | integer | 总数 |
| skip | integer | 跳过数量 |
| limit | integer | 返回数量 |

---

### 2.2 获取知识库详情

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**响应参数**：同 2.1 中 `items[]` 的结构（单个知识库对象）

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| KNOWLEDGE_BASE_NOT_FOUND | 404 | 知识库不存在或不属于该空间 |

---

### 2.3 创建知识库

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 是 | 知识库名称（1-100 字符） |
| config | object | 否 | 知识库配置（不传则使用默认值） |

**config 对象**

> **注意**：Embedding 模型由空间级别统一管理（通过 `GET/PATCH /api/v1/spaces/{space_id}/config` 配置），知识库 config 中不包含 embedding 字段。文档向量和检索时自动读取空间的 Embedding 配置。

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| description | string | 否 | 知识库描述（最多 2000 字符，默认空字符串） |
| splitting | object | 否 | 切分配置 |
| parsing | object | 否 | 解析配置 |
| question_generation | object | 否 | 问题生成配置 |

**splitting 对象（切分策略）**

支持 4 种策略，通过 `strategy` 字段区分（判别联合类型）：

**递归字符切分（recursive，默认）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| strategy | string | 是 | 固定值 `"recursive"` |
| chunk_size | integer | 否 | 目标分块大小（50-4000，默认 1000） |
| chunk_overlap | integer | 否 | 相邻分块重叠字符数（0-500，默认 100） |

**固定大小切分（fixed_size）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| strategy | string | 是 | 固定值 `"fixed_size"` |
| chunk_size | integer | 否 | 目标分块大小（50-4000，默认 1000） |
| chunk_overlap | integer | 否 | 相邻分块重叠字符数（0-500，默认 100） |

**Markdown 结构切分（markdown）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| strategy | string | 是 | 固定值 `"markdown"` |
| max_chunk_size | integer | 否 | 最大分块大小（100-8000，默认 2000） |
| min_chunk_size | integer | 否 | 最小分块大小（10-1000，默认 100） |

**语义切分（semantic）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| strategy | string | 是 | 固定值 `"semantic"` |
| max_chunk_size | integer | 否 | 最大分块大小（100-8000，默认 2000） |
| similarity_threshold | float | 否 | 语义相似度阈值（0.0-1.0，默认 0.7） |
| batch_size | integer | 否 | 批处理大小（1-100，默认 20） |

**parsing 对象（解析配置）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| extract_images | boolean | 否 | 是否提取图片（默认 false） |
| extract_tables | boolean | 否 | 是否提取表格（默认 true） |
| ocr_enabled | boolean | 否 | 是否启用 OCR（默认 false） |
| preserve_structure | boolean | 否 | 是否保留文档结构（默认 true） |
| encoding | string | 否 | 文件编码（默认 "utf-8"） |

**question_generation 对象（问题生成配置）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| enabled | boolean | 否 | 是否启用（默认 false） |
| llm | object | 否 | LLM 配置 |
| max_questions_per_chunk | integer | 否 | 每个分块最大问题数（1-20，默认 5） |
| prompt_template | string | 否 | 自定义提示词模板（最多 4000 字符） |

**question_generation.llm 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| model | string | 否 | LLM 模型名称（为空使用系统默认） |
| protocol | string | 否 | 通信协议（为空使用系统默认） |
| temperature | float | 否 | 生成温度（0-2，默认 0.3，问题生成建议低值以确保格式稳定） |
| top_p | float | 否 | 核采样参数（0-1，默认 0.9） |
| max_tokens | integer | 否 | 最大生成 token 数（100-8192，默认 2048） |

**请求示例**
```json
{
  "name": "产品文档库",
  "config": {
    "description": "产品相关文档",
    "splitting": {
      "strategy": "recursive",
      "chunk_size": 1000,
      "chunk_overlap": 100
    },
    "parsing": {
      "extract_tables": true,
      "preserve_structure": true
    },
    "question_generation": {
      "enabled": true,
      "max_questions_per_chunk": 5
    }
  }
}
```

**响应参数**：同 2.1 中 `items[]` 的结构（单个知识库对象）

---

### 2.4 更新知识库

**请求**
- 方法：`PUT`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| name | string | 否 | 知识库名称（1-100 字符） |
| config | object | 否 | 知识库配置（同 2.3 config 结构） |

> 仅传需要修改的字段，未传的字段保持不变。

**响应参数**：同 2.1 中 `items[]` 的结构

---

### 2.5 删除知识库

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}`
- 权限要求：管理员（ADMIN）

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 响应消息 |

**响应示例**
```json
{
  "success": true,
  "message": "知识库 '产品文档库' 已删除"
}
```

---

### 2.6 获取知识库配置

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/config`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| kb_id | integer | 知识库 ID |
| name | string | 知识库名称 |
| config | object | 完整配置（同 2.3 config 结构） |
| stats | object | 实时统计信息（同 2.1 stats 结构） |

---

### 2.7 更新知识库配置（部分更新）

**请求**
- 方法：`PATCH`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/config`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上

**说明**：深度合并，只传需要修改的字段。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**请求参数**

> **注意**：`embedding` 字段由空间级别管理，不可通过此接口修改。

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| splitting | object | 否 | 切分配置 |
| parsing | object | 否 | 解析配置 |
| question_generation | object | 否 | 问题生成配置 |

**响应参数**：同 2.6 响应结构

---

## 三、文档管理

路由前缀：`/api/v1/spaces/{space_id}/knowledge-bases`

**允许上传的文件类型**：`.pdf`, `.docx`, `.doc`, `.txt`, `.md`, `.csv`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.html`, `.json`

**文件大小限制**：最大 100MB

### 3.1 上传文档

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents`
- Content-Type：`multipart/form-data`
- 权限要求：编辑者（EDITOR）及以上

> 仅存储到 MinIO，不触发解析。需要通过 3.7 接口触发解析。
> 支持单文件和多文件批量上传（最多 20 个文件）。
>
> **文档复活**：如果上传的文件与同知识库内某个已删除文档内容完全相同（SHA256 一致），系统会自动"复活"该文档记录，复用原有的文档 ID。复活时会更新上传人、文件名等信息，并重新上传 MinIO 文件。返回的 `document_id` 与之前删除的文档相同。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| files | file[] | 是 | form | 文档文件（支持多个同名字段，最多 20 个） |

**单文件上传响应参数**

当上传 1 个文件时，返回以下格式：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| document_id | integer | 文档 ID |
| filename | string | 文件名 |
| status | string | 处理状态（"uploaded"） |
| message | string | 消息 |

**单文件上传响应示例**
```json
{
  "document_id": 1,
  "filename": "产品手册.pdf",
  "status": "uploaded",
  "message": "文档上传成功，等待拆分解析"
}
```

**批量上传响应参数**

当上传多个文件（2-20 个）时，返回以下格式：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total | integer | 上传文件总数 |
| success | array | 上传成功的文档列表 |
| success[].document_id | integer | 文档 ID |
| success[].filename | string | 文件名 |
| success[].status | string | 处理状态（"uploaded"） |
| success[].message | string | 消息 |
| failed | array | 上传失败的文件列表 |
| failed[].filename | string | 文件名 |
| failed[].error | string | 失败原因 |

**批量上传响应示例**
```json
{
  "total": 3,
  "success": [
    {
      "document_id": 1,
      "filename": "产品手册.pdf",
      "status": "uploaded",
      "message": "文档上传成功，等待拆分解析"
    },
    {
      "document_id": 2,
      "filename": "技术方案.docx",
      "status": "uploaded",
      "message": "文档上传成功，等待拆分解析"
    }
  ],
  "failed": [
    {
      "filename": "说明.exe",
      "error": "不支持的文件类型: .exe"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| DOCUMENT_INVALID_TYPE | 400 | 不支持的文件类型 |
| DOCUMENT_SIZE_EXCEEDED | 400 | 文件大小超限（最大 100MB） |
| DOCUMENT_COUNT_EXCEEDED | 400 | 文件数量超限（最多 20 个） |
| KNOWLEDGE_BASE_NOT_FOUND | 404 | 知识库不存在 |

---

### 3.2 获取文档列表

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**查询参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| status | string | 否 | 状态过滤（uploaded/processing/completed/failed） |
| skip | integer | 否 | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | 返回的最大记录数（默认 100，1-1000） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 文档列表 |
| items[].id | integer | 文档 ID |
| items[].space_id | integer | 所属空间 ID |
| items[].kb_id | integer | 所属知识库 ID |
| items[].uploader_id | integer | 上传者 ID |
| items[].filename | string | 原始文件名 |
| items[].file_type | string | 文件类型 |
| items[].file_size | integer | 文件大小（字节） |
| items[].file_hash | string | 文件哈希 |
| items[].status | integer | 处理状态 |
| items[].doc_metadata | object | 文档元数据 |
| items[].status_info | object | 状态详情（错误信息、重试次数等） |
| items[].retry_count | integer | 重试次数（从 status_info 计算属性提取） |
| items[].error_message | string | 错误信息（从 status_info 计算属性提取） |
| items[].chunk_count | integer | 分块数量（从 doc_metadata 计算属性提取） |
| items[].token_count | integer | Token 总数（从 doc_metadata 计算属性提取） |
| items[].created_at | string | 上传时间 |
| items[].updated_at | string | 更新时间 |
| items[].processing_started_at | string | 处理开始时间 |
| items[].processed_at | string | 处理完成时间 |
| total | integer | 总数 |
| skip | integer | 跳过数量 |
| limit | integer | 返回数量 |

---

### 3.3 获取文档详情

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**响应参数**

文档详情响应继承文档基本信息（同 3.2 items[] 结构）并扩展包含分块列表：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| ... | ... | 继承 3.2 中所有文档字段 |
| chunks | array | 分块列表 |

**chunks[] 对象**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| chunk_id | string | 分块 ID |
| document_id | integer | 所属文档 ID |
| chunk_index | integer | 分块索引 |
| content | string | 分块内容 |
| score | float | 检索得分 |
| has_embedding | boolean | 是否已向量化 |
| metadata | object | 元数据 |
| file_info | object | 文件信息 |
| questions | string[] | 假设性问题列表 |
| created_at | string | 创建时间 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| DOCUMENT_NOT_FOUND | 404 | 文档不存在 |

---

### 3.4 获取文档分块

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}/chunks`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**响应参数**：返回 `ChunkResponse[]` 数组，结构同 3.3 中 `chunks[]` 对象。

---

### 3.5 下载文档

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}/download`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**响应**
- Content-Type：`application/octet-stream`
- Content-Disposition：`attachment; filename="download"; filename*=UTF-8''<encoded_filename>`
- 返回文件二进制流

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| DOCUMENT_NOT_FOUND | 404 | 文档不存在 |

---

### 3.6 删除文档

> **软删除**：文档删除后记录仍保留在数据库中（`deleted_at` 不为空），MinIO 文件和 ES 分块会被清理。之后如果重新上传同一文件，系统会自动复活该记录（见 3.1 文档复活说明）。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}`

**权限说明**
- 管理员（ADMIN）：可删除任意文档
- 编辑者（EDITOR）：只能删除自己上传的文档
- 查看者（VIEWER）：不可删除文档

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 响应消息 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| DOCUMENT_NOT_FOUND | 404 | 文档不存在 |
| SPACE_ACCESS_DENIED | 403 | 需要编辑者或更高权限，或编辑者只能删除自己上传的文档 |

---

### 3.7 触发文档拆分解析

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}/process`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上
- 状态码：`202 Accepted`

> 仅处理 UPLOADED 或 FAILED 状态的文档。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| enable_question_generation | boolean | 否 | 是否为分块生成假设问题（默认 false）。传 `true` 时直接生效，无需知识库配置中额外开启；不传时回退到知识库配置中的 `question_generation.enabled` 设置 |
| question_count | integer | 否 | 每个分块生成的问题数量（1-10，默认 5） |

**请求示例**
```json
{
  "enable_question_generation": true,
  "question_count": 5
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| document_id | integer | 文档 ID |
| status | string | 状态（固定值 "processing"） |
| message | string | 消息（固定值 "文档已开始处理"） |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| DOCUMENT_NOT_FOUND | 404 | 文档不存在 |
| DOCUMENT_ALREADY_PROCESSING | 409 | 文档正在处理中 |

---

### 3.8 批量触发文档拆分解析

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/process`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上
- 状态码：`202 Accepted`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| document_ids | integer[] | 否 | 文档 ID 列表（最多 100 个，为空则处理全部未处理文档） |
| enable_question_generation | boolean | 否 | 是否为分块生成假设问题（默认 false）。传 `true` 时直接生效，无需知识库配置中额外开启；不传时回退到知识库配置中的 `question_generation.enabled` 设置 |
| question_count | integer | 否 | 每个分块生成的问题数量（1-10，默认 5） |

**请求示例**
```json
{
  "document_ids": [1, 2, 3],
  "enable_question_generation": false
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total | integer | 总处理数 |
| success | integer | 成功数 |
| failed | integer | 失败数 |
| skipped | integer | 跳过数 |
| results | array | 各文档处理结果详情 |

---

### 3.9 重新解析文档

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/documents/{document_id}/reprocess`
- Content-Type：`application/json`
- 权限要求：编辑者（EDITOR）及以上
- 状态码：`202 Accepted`

> 清除旧 chunk，按当前知识库配置重新切分。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |
| document_id | integer | 是 | 文档 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| enable_question_generation | boolean | 否 | 是否为分块生成假设问题（默认 false）。传 `true` 时直接生效，无需知识库配置中额外开启；不传时回退到知识库配置中的 `question_generation.enabled` 设置 |
| question_count | integer | 否 | 每个分块生成的问题数量（1-10，默认 5） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| document_id | integer | 文档 ID |
| status | string | 状态（固定值 "processing"） |
| message | string | 消息（固定值 "文档已开始处理"） |

---

## 四、成员管理

路由前缀：`/api/v1/spaces/{space_id}/members`

**角色说明**

| 角色 | 值 | 说明 |
|------|-----|------|
| VIEWER | 0 | 查看者：可查看空间内容 |
| EDITOR | 1 | 编辑者：可上传文档、编辑知识库 |
| ADMIN | 2 | 管理员：可管理成员、删除空间 |

**自定义权限（custom_permissions）**

每个成员可通过 `custom_permissions` 字段覆盖角色默认权限。自定义权限优先级高于角色，未配置的操作仍按角色判断。

`custom_permissions` 数据结构：
```json
{
  "spaces": { "update": true, "delete": false },
  "knowledge_bases": { "manage": true },
  "documents": { "upload": true, "delete": false, "delete_any": false },
  "members": { "invite": true, "manage": false }
}
```

**资源与操作映射**

| 资源（resource） | 操作（action） | 默认所需角色 | 说明 |
|-----------------|---------------|------------|------|
| spaces | update | ADMIN | 更新空间设置 |
| spaces | delete | ADMIN | 删除空间 |
| knowledge_bases | manage | EDITOR | 管理知识库（创建/编辑） |
| documents | upload | EDITOR | 上传文档 |
| documents | delete | EDITOR | 删除自己的文档 |
| documents | delete_any | ADMIN | 删除任意文档 |
| members | invite | ADMIN | 邀请成员 |
| members | manage | ADMIN | 管理成员 |

> 示例：一个 VIEWER 角色的成员，设置 `custom_permissions: {"documents": {"upload": true}}` 后即可上传文档。

### 4.1 获取成员列表

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/members`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**查询参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| skip | integer | 否 | 跳过的记录数（默认 0，>= 0） |
| limit | integer | 否 | 返回的最大记录数（默认 100，1-1000） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 成员列表 |
| items[].id | integer | 成员记录 ID |
| items[].space_id | integer | 空间 ID |
| items[].user_id | integer | 用户 ID |
| items[].role | integer | 角色（0/1/2） |
| items[].custom_permissions | object | 细粒度权限 |
| items[].status | integer | 成员状态 |
| items[].invited_by | integer | 邀请人 ID |
| items[].joined_at | string | 加入时间 |
| items[].created_at | string | 创建时间 |
| items[].username | string | 用户名（关联查询 users 表获取） |
| items[].email | string | 用户邮箱（关联查询 users 表获取） |
| total | integer | 总数 |
| skip | integer | 跳过数量 |
| limit | integer | 返回数量 |

**响应示例**
```json
{
  "items": [
    {
      "id": 1,
      "space_id": 4,
      "user_id": 1,
      "role": 2,
      "custom_permissions": null,
      "status": 1,
      "invited_by": null,
      "joined_at": "2026-04-15T10:00:00",
      "created_at": "2026-04-15T10:00:00",
      "username": "admin",
      "email": "admin@example.com"
    },
    {
      "id": 5,
      "space_id": 4,
      "user_id": 3,
      "role": 0,
      "custom_permissions": null,
      "status": 1,
      "invited_by": 1,
      "joined_at": "2026-04-16T14:30:00",
      "created_at": "2026-04-16T14:00:00",
      "username": "zhangsan",
      "email": "zhangsan@example.com"
    }
  ],
  "total": 2,
  "skip": 0,
  "limit": 20
}
```

---

### 4.2 邀请成员

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/members`
- Content-Type：`application/json`
- 权限要求：管理员（ADMIN）

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| email | string | 是 | 被邀请用户邮箱（合法邮箱格式） |
| role | integer | 否 | 角色（默认 0-VIEWER，0/1/2） |
| expires_hours | integer | 否 | 邀请有效期（小时，1-168，默认 72） |

**请求示例**
```json
{
  "email": "user@example.com",
  "role": 1,
  "expires_hours": 48
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| member_id | integer | 成员记录 ID |
| invite_token | string | 邀请令牌（仅显示前 8 位 + "..."） |
| invite_expires_at | string | 邀请过期时间 |
| message | string | 消息 |

**响应示例**
```json
{
  "member_id": 5,
  "invite_token": "abcd1234...",
  "invite_expires_at": "2026-04-17T10:00:00",
  "message": "邀请已发送"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| USER_NOT_FOUND | 404 | 用户不存在 |
| MEMBER_ALREADY_EXISTS | 409 | 用户已是成员 |
| SPACE_ACCESS_DENIED | 403 | 需要管理员权限 |

---

### 4.3 加入空间

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/members/join`
- Content-Type：`application/json`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| invite_token | string | 是 | 邀请令牌（1-128 字符） |

**请求示例**
```json
{
  "invite_token": "abcdef1234567890"
}
```

**响应参数**：同 4.1 中 `items[]` 的结构（单个成员对象）

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| INVITE_EXPIRED | 410 | 邀请已过期 |
| INVITE_INVALID | 400 | 邀请令牌无效 |

---

### 4.4 获取我的成员信息

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/members/me`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**响应参数**：同 4.1 中 `items[]` 的结构（当前用户的成员信息）

---

### 4.5 更新成员角色

**请求**
- 方法：`PUT`
- URL：`/api/v1/spaces/{space_id}/members/{target_user_id}`
- Content-Type：`application/json`
- 权限要求：管理员（ADMIN）

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| target_user_id | integer | 是 | 目标用户 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| role | integer | 否 | 新角色（0/1/2） |

**请求示例**
```json
{
  "role": 1
}
```

**响应参数**：同 4.1 中 `items[]` 的结构

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| MEMBER_NOT_FOUND | 404 | 成员不存在 |
| CANNOT_MODIFY_SELF_ROLE | 403 | 不能修改自己的角色 |
| CANNOT_REMOVE_LAST_ADMIN | 403 | 不能移除最后一个管理员 |

---

### 4.6 移除成员

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}/members/{target_user_id}`
- 权限要求：管理员（ADMIN）

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| target_user_id | integer | 是 | 目标用户 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 响应消息 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| MEMBER_NOT_FOUND | 404 | 成员不存在 |
| CANNOT_REMOVE_LAST_ADMIN | 403 | 不能移除最后一个管理员 |

---

### 4.7 离开空间

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/members/leave`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 操作是否成功 |
| message | string | 响应消息 |

**响应示例**
```json
{
  "success": true,
  "message": "已离开空间"
}
```

---

## 五、知识检索

路由前缀：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search`

> **注意**：`kb_id` 会校验是否属于当前 `space_id`，且知识库必须为活跃状态（status=1）。

### 5.1 统一检索接口

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search`
- Content-Type：`application/json`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**请求参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| query | string | 是 | 查询文本（1-2000 字符） |
| search_mode | string | 否 | 检索模式（默认 "content_hybrid"） |
| top_k | integer | 否 | 返回结果数量（1-100，默认 10） |
| weights | object | 否 | 权重配置 |
| rerank | object | 否 | Rerank 重排序配置 |
| llm | object | 否 | LLM 回答配置 |
| query_rewrite | object | 否 | 查询改写配置 |
| score_threshold | float | 否 | 最低分数阈值（0.0-1.0，默认 0.0） |
| fallback_on_unavailable | boolean | 否 | 模式不可用时是否自动降级（默认 true） |
| filters | object | 否 | 额外过滤条件 |
| use_cache | boolean | 否 | 是否使用缓存（默认 true） |

**search_mode 可选值**

| 模式 | 说明 | 需要问题生成 |
|------|------|------------|
| content_bm25 | 内容全文检索 | 否 |
| content_vector | 内容向量检索 | 否 |
| content_hybrid | 内容混合检索（默认） | 否 |
| question_bm25 | 问题全文检索 | 是 |
| question_vector | 问题向量检索 | 是 |
| question_hybrid | 问题混合检索 | 是 |
| all_bm25 | 全字段全文检索 | 是 |
| all_vector | 全字段向量检索 | 是 |
| all_hybrid | 全字段全算法融合 | 是 |

**weights 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| vector_weight | float | 否 | 向量检索权重（0-1，默认 0.7） |
| bm25_weight | float | 否 | BM25 检索权重（0-1，默认 0.3） |
| content_weight | float | 否 | 内容字段权重（0-1，默认 0.6） |
| question_weight | float | 否 | 问题字段权重（0-1，默认 0.4） |
| rrf_k | integer | 否 | RRF 平滑参数（>=1，默认 60） |

**rerank 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| enabled | boolean | 否 | 是否启用 Rerank（默认 false） |
| top_k | integer | 否 | Rerank 后返回数量（>=1，默认 3） |
| model | string | 否 | Rerank 模型名称（为空使用系统默认） |

**llm 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| enabled | boolean | 否 | 是否启用 LLM 回答（默认 false） |
| model | string | 否 | LLM 模型名称（为空使用系统默认） |
| temperature | float | 否 | 生成温度（0-2，默认 0.7） |
| top_p | float | 否 | 核采样参数（0-1，默认 0.9） |

**query_rewrite 对象**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| strategy | string | 否 | 改写策略：`hyde`（假设性文档嵌入）/`sub_query`（子问题拆分），默认 `"hyde"` |
| hyde_prompt | string | 否 | HyDE 自定义提示词（最多 2000 字符，为空使用系统默认提示词） |
| sub_query_count | integer | 否 | 子问题拆分数量（2-5，默认 3，strategy=sub_query 时生效） |
| sub_query_merge_mode | string | 否 | 子问题结果合并方式：`rrf`（加权融合，默认）/`score`（分数取最大） |
| llm_model | string | 否 | 查询改写使用的 LLM 模型（为空使用系统默认） |

> **策略说明**：
> - **hyde**：用 LLM 生成一段假设性回答文档，再用该文档的向量进行检索，缩小查询与文档的语义鸿沟
> - **sub_query**：用 LLM 将复杂查询拆分为多个子问题，分别检索后按 `sub_query_merge_mode` 合并结果，提高多维度信息的召回覆盖率

**请求示例**

示例 1：基础检索
```json
{
  "query": "如何使用 FastAPI 构建 REST API",
  "search_mode": "content_hybrid",
  "top_k": 10,
  "weights": {
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "content_weight": 0.6,
    "question_weight": 0.4,
    "rrf_k": 60
  },
  "rerank": {
    "enabled": true,
    "top_k": 5
  },
  "llm": {
    "enabled": true,
    "temperature": 0.7
  },
  "score_threshold": 0.5
}
```

示例 2：启用查询改写（sub_query 子问题拆分）
```json
{
  "query": "FastAPI 如何实现用户认证和权限控制",
  "search_mode": "content_hybrid",
  "top_k": 10,
  "query_rewrite": {
    "strategy": "sub_query",
    "sub_query_count": 3,
    "sub_query_merge_mode": "rrf"
  }
}
```

示例 3：启用查询改写（HyDE 假设性文档嵌入）
```json
{
  "query": "什么是 RAG 检索增强生成技术",
  "search_mode": "content_vector",
  "top_k": 10,
  "query_rewrite": {
    "strategy": "hyde"
  }
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| results | array | 检索结果列表 |
| results[].chunk_id | string | 分块 ID |
| results[].document_id | integer | 文档 ID |
| results[].kb_id | integer | 知识库 ID |
| results[].content | string | 检索到的内容 |
| results[].score | float | 融合分数 |
| results[].chunk_index | integer | 分块索引 |
| results[].questions | string[] \| null | 该分块预生成的假设性问题列表（分块有预生成问题时返回，无问题时为 null，由前端决定是否展示） |
| results[].metadata | object | 分块元数据 |
| results[].file_info | object | 文件信息 |
| total | integer | 结果总数 |
| query | string | 原始查询文本 |
| search_mode | string | 实际使用的检索模式 |
| original_mode | string | 原始请求模式（降级时有值） |
| mode_fallback | boolean | 是否发生了模式降级 |
| top_k | integer | 请求的返回数量 |
| vector_weight | float | 向量检索权重 |
| bm25_weight | float | BM25 检索权重 |
| answer | string | LLM 生成的回答（启用时返回） |
| answer_model | string | 生成回答使用的模型 |
| answer_elapsed_ms | float | LLM 回答耗时（毫秒） |
| elapsed_ms | float | 检索耗时（毫秒） |
| cached | boolean | 是否来自缓存 |
| rewritten_queries | string[] \| null | 查询改写后的问题列表（启用 query_rewrite 时返回，hyde 时为假设性文档，sub_query 时为子问题列表） |

**响应示例**

示例 1：普通检索（content_hybrid 模式，分块有预生成问题）
```json
{
  "results": [
    {
      "chunk_id": "chunk_42",
      "document_id": 7,
      "kb_id": 3,
      "content": "FastAPI 是一个高性能的 Python Web 框架...",
      "score": 0.92,
      "chunk_index": 1,
      "questions": [
        "FastAPI 框架的主要特点是什么？",
        "如何使用 FastAPI 定义一个 REST API 接口？",
        "FastAPI 与 Flask 有什么区别？"
      ],
      "metadata": { "page": 5 },
      "file_info": { "filename": "fastapi_guide.pdf" }
    }
  ],
  "total": 1,
  "query": "如何使用 FastAPI 构建 REST API",
  "search_mode": "content_hybrid",
  "original_mode": null,
  "mode_fallback": false,
  "top_k": 10,
  "vector_weight": 0.7,
  "bm25_weight": 0.3,
  "answer": null,
  "answer_model": null,
  "answer_elapsed_ms": null,
  "elapsed_ms": 156.3,
  "cached": false,
  "rewritten_queries": null
}
```

示例 2：分块未启用问题生成时（questions 为 null）
```json
{
  "results": [
    {
      "chunk_id": "chunk_42",
      "document_id": 7,
      "kb_id": 3,
      "content": "FastAPI 是一个高性能的 Python Web 框架...",
      "score": 0.92,
      "chunk_index": 1,
      "questions": null,
      "metadata": { "page": 5 },
      "file_info": { "filename": "fastapi_guide.pdf" }
    }
  ],
  "total": 1,
  "query": "如何使用 FastAPI 构建 REST API",
  "search_mode": "content_hybrid",
  "original_mode": null,
  "mode_fallback": false,
  "top_k": 10,
  "vector_weight": 0.7,
  "bm25_weight": 0.3,
  "answer": null,
  "answer_model": null,
  "answer_elapsed_ms": null,
  "elapsed_ms": 156.3,
  "cached": false,
  "rewritten_queries": null
}
```

示例 3：启用查询改写（sub_query 策略）
```json
{
  "results": [ "...（同上结构）" ],
  "total": 5,
  "query": "FastAPI 如何实现用户认证和权限控制",
  "search_mode": "content_hybrid",
  "original_mode": null,
  "mode_fallback": false,
  "top_k": 10,
  "vector_weight": 0.7,
  "bm25_weight": 0.3,
  "answer": null,
  "answer_model": null,
  "answer_elapsed_ms": null,
  "elapsed_ms": 520.8,
  "cached": false,
  "rewritten_queries": [
    "FastAPI 中如何配置 JWT 认证？",
    "FastAPI 权限控制的实现方式有哪些？",
    "如何在 FastAPI 中实现基于角色的访问控制（RBAC）？"
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| KNOWLEDGE_BASE_NOT_FOUND | 404 | 知识库不存在或不属于该空间 |
| SEARCH_ERROR | 400 | 检索失败 |
| EMBEDDING_ERROR | 400 | 向量化失败 |
| INVALID_SEARCH_MODE | 400 | 无效的检索模式 |
| RERANK_ERROR | 400 | Rerank 失败 |

---

### 5.2 获取可用检索模式

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search/modes`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| modes | array | 可用检索模式列表 |
| modes[].mode | string | 模式标识 |
| modes[].label | string | 显示名称 |
| modes[].description | string | 模式描述 |
| modes[].requires_question_generation | boolean | 是否需要启用问题生成 |
| total | integer | 可用模式总数 |

**响应示例**
```json
{
  "modes": [
    {
      "mode": "content_bm25",
      "label": "内容全文检索",
      "description": "使用 BM25 算法对内容进行全文检索",
      "requires_question_generation": false
    },
    {
      "mode": "content_vector",
      "label": "内容向量检索",
      "description": "使用向量相似度对内容进行语义检索",
      "requires_question_generation": false
    },
    {
      "mode": "content_hybrid",
      "label": "内容混合检索",
      "description": "结合 BM25 和向量检索的内容混合检索",
      "requires_question_generation": false
    }
  ],
  "total": 3
}
```

---

### 5.3 获取模型配置

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/search/model-config`

> **注意**：Embedding 模型信息从空间级别配置读取，LLM 和 Rerank 模型从系统默认配置读取。

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| space_id | integer | 是 | 空间 ID（> 0） |
| kb_id | integer | 是 | 知识库 ID（> 0） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| embedding_model | string | 空间配置的 Embedding 模型名称 |
| embedding_dimension | integer | 空间配置的向量维度 |
| default_llm_model | string | 默认 LLM 模型名称 |
| default_rerank_model | string | 默认 Rerank 模型名称 |
| available_embedding_models | string[] | 用户可用的 Embedding 模型列表 |
| available_llm_models | string[] | 用户可用的 LLM 模型列表 |
| available_rerank_models | string[] | 用户可用的 Rerank 模型列表 |

**响应示例**
```json
{
  "embedding_model": "embedding-3",
  "embedding_dimension": 1024,
  "default_llm_model": "glm-4-flash",
  "default_rerank_model": "bge-reranker-v2-m3",
  "available_embedding_models": ["embedding-3", "text-embedding-ada-002"],
  "available_llm_models": ["glm-4-flash", "glm-4-plus", "qwen-turbo"],
  "available_rerank_models": ["bge-reranker-v2-m3"]
}
```

---

## 接口总览

| 序号 | 方法 | URL | 说明 | 最低权限 |
|------|------|-----|------|---------|
| 1.1 | POST | `/api/v1/spaces` | 创建知识空间 | 登录用户 |
| 1.2 | GET | `/api/v1/spaces` | 获取我的空间列表 | 登录用户 |
| 1.3 | GET | `/api/v1/spaces/public` | 获取公开空间列表 | 登录用户 |
| 1.4 | GET | `/api/v1/spaces/search` | 搜索知识空间 | 登录用户 |
| 1.5 | GET | `/api/v1/spaces/{space_id}` | 获取空间详情 | 空间成员 |
| 1.6 | PUT | `/api/v1/spaces/{space_id}` | 更新空间设置 | ADMIN |
| 1.7 | DELETE | `/api/v1/spaces/{space_id}` | 删除空间 | ADMIN |
| 1.8 | GET | `/api/v1/spaces/{space_id}/config` | 获取空间配置（含 Embedding 模型） | 空间成员 |
| 1.9 | PATCH | `/api/v1/spaces/{space_id}/config` | 更新空间配置（深度合并） | ADMIN |
| 2.1 | GET | `/api/v1/spaces/{space_id}/knowledge-bases` | 获取知识库列表 | VIEWER |
| 2.2 | GET | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}` | 获取知识库详情 | VIEWER |
| 2.3 | POST | `/api/v1/spaces/{space_id}/knowledge-bases` | 创建知识库 | EDITOR |
| 2.4 | PUT | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}` | 更新知识库 | EDITOR |
| 2.5 | DELETE | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}` | 删除知识库 | ADMIN |
| 2.6 | GET | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/config` | 获取知识库配置 | VIEWER |
| 2.7 | PATCH | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/config` | 更新知识库配置 | EDITOR |
| 3.1 | POST | `.../knowledge-bases/{kb_id}/documents` | 上传文档（支持批量，最多20个） | EDITOR |
| 3.2 | GET | `.../knowledge-bases/{kb_id}/documents` | 获取文档列表 | VIEWER |
| 3.3 | GET | `.../knowledge-bases/{kb_id}/documents/{document_id}` | 获取文档详情 | VIEWER |
| 3.4 | GET | `.../knowledge-bases/{kb_id}/documents/{document_id}/chunks` | 获取文档分块 | VIEWER |
| 3.5 | GET | `.../knowledge-bases/{kb_id}/documents/{document_id}/download` | 下载文档 | VIEWER |
| 3.6 | DELETE | `.../knowledge-bases/{kb_id}/documents/{document_id}` | 删除文档 | EDITOR |
| 3.7 | POST | `.../knowledge-bases/{kb_id}/documents/{document_id}/process` | 触发文档拆分解析 | EDITOR |
| 3.8 | POST | `.../knowledge-bases/{kb_id}/documents/process` | 批量触发拆分解析 | EDITOR |
| 3.9 | POST | `.../knowledge-bases/{kb_id}/documents/{document_id}/reprocess` | 重新解析文档 | EDITOR |
| 4.1 | GET | `/api/v1/spaces/{space_id}/members` | 获取成员列表 | 空间成员 |
| 4.2 | POST | `/api/v1/spaces/{space_id}/members` | 邀请成员 | ADMIN |
| 4.3 | POST | `/api/v1/spaces/{space_id}/members/join` | 加入空间 | 登录用户 |
| 4.4 | GET | `/api/v1/spaces/{space_id}/members/me` | 获取我的成员信息 | 空间成员 |
| 4.5 | PUT | `/api/v1/spaces/{space_id}/members/{target_user_id}` | 更新成员角色 | ADMIN |
| 4.6 | DELETE | `/api/v1/spaces/{space_id}/members/{target_user_id}` | 移除成员 | ADMIN |
| 4.7 | POST | `/api/v1/spaces/{space_id}/members/leave` | 离开空间 | 空间成员 |
| 5.1 | POST | `.../knowledge-bases/{kb_id}/search` | 统一检索 | 空间成员 |
| 5.2 | GET | `.../knowledge-bases/{kb_id}/search/modes` | 获取可用检索模式 | 空间成员 |
| 5.3 | GET | `.../knowledge-bases/{kb_id}/search/model-config` | 获取模型配置 | 空间成员 |

---

## 完整错误码参考

| 错误码 | HTTP 状态码 | 说明 |
|--------|------------|------|
| SPACE_NOT_FOUND | 404 | 空间不存在 |
| SPACE_ALREADY_EXISTS | 409 | 空间名称已存在 |
| SPACE_ACCESS_DENIED | 403 | 无权访问空间 |
| SPACE_LIMIT_EXCEEDED | 400 | 已达空间数量上限 |
| MEMBER_NOT_FOUND | 404 | 成员不存在 |
| MEMBER_ALREADY_EXISTS | 409 | 用户已是空间成员 |
| INVITE_EXPIRED | 410 | 邀请已过期 |
| INVITE_INVALID | 400 | 邀请令牌无效 |
| CANNOT_REMOVE_LAST_ADMIN | 403 | 不能移除最后一个管理员 |
| CANNOT_MODIFY_SELF_ROLE | 403 | 不能修改自己的角色 |
| KNOWLEDGE_BASE_NOT_FOUND | 404 | 知识库不存在或不属于该空间 |
| KNOWLEDGE_BASE_ALREADY_EXISTS | 409 | 知识库名称已存在 |
| KNOWLEDGE_BASE_ACCESS_DENIED | 403 | 无权访问知识库 |
| KNOWLEDGE_BASE_LIMIT_EXCEEDED | 400 | 已达知识库数量上限 |
| DOCUMENT_NOT_FOUND | 404 | 文档不存在 |
| DOCUMENT_ALREADY_EXISTS | 409 | 文档已存在 |
| DOCUMENT_PROCESSING_ERROR | 500 | 文档处理失败 |
| DOCUMENT_INVALID_TYPE | 400 | 不支持的文件类型 |
| DOCUMENT_SIZE_EXCEEDED | 400 | 文件大小超限 |
| DOCUMENT_COUNT_EXCEEDED | 400 | 文件数量超限 |
| DOCUMENT_ALREADY_PROCESSING | 409 | 文档正在处理中 |
| SEARCH_ERROR | 400 | 检索失败 |
| EMBEDDING_ERROR | 400 | 向量化失败 |
| INVALID_SEARCH_MODE | 400 | 无效的检索模式 |
| INVALID_SEARCH_WEIGHT | 400 | 检索权重校验失败 |
| RERANK_ERROR | 400 | Rerank 重排序失败 |
| QUESTION_GENERATION_ERROR | 500 | 问题生成失败 |
| USER_NOT_FOUND | 404 | 用户不存在 |
| INVALID_PARAMETER | 400 | 参数无效 |
