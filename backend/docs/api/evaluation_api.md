# 知识库测评模块 API 文档

## 概述

知识库测评模块提供对 RAG 系统的自动化评估能力。支持上传测试集（JSON/CSV）并复用，基于测试集创建多次测评任务（可使用不同配置参数进行对比），异步并发执行多阶段评测（检索阶段、生成阶段、端到端评估），LLM 自动打分 + 人工逐条打分，最终生成测评报告并支持导出。

模块包含两个子模块：

| 子模块 | 路由前缀 | 说明 |
|-------|---------|------|
| 测试集管理 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets` | 测试集上传、查询、更新、删除、用例预览 |
| 测评任务管理 | `/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks` | 任务创建、查询、取消、报告、评分、导出、进度 |

评测体系参考 RAGAS/DeepEval 等主流框架，分为三个评估层次：

- **检索阶段**：Precision@K、Hit Rate、MRR
- **生成阶段**：Faithfulness（忠实度）、Answer Relevance（答案相关性）、Correctness（正确性）、Quality（综合质量）
- **端到端**：Context Precision、Context Recall、Answer Similarity、人工评分

### 认证方式

所有接口均需要 JWT 认证，在请求头中携带：

```
Authorization: Bearer <token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. `space_id` 为知识空间 ID，用户必须是该空间的成员
3. `kb_id` 为知识库 ID，需要属于该空间

### 通用 Header

| Header | 值 | 必填 | 说明 |
|--------|------|------|------|
| Authorization | `Bearer <token>` | 是 | JWT 访问令牌 |
| Content-Type | `multipart/form-data` 或 `application/json` | 是 | 上传测试集用 multipart，其余用 json |

### 通用响应格式

**成功响应**：各接口独立定义。

**错误响应**：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-21T10:00:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

---

## 枚举值定义

### EvaluationStatus（测评任务状态）

| 状态字符串 | 整数值 | 说明 |
|-----------|--------|------|
| `pending` | 1 | 待执行 |
| `completed` | 2 | 已完成 |
| `failed` | 3 | 执行失败 |
| `deleted` | 4 | 已删除（内部状态，不对外暴露） |
| `running` | 5 | 执行中 |
| `cancelled` | 6 | 已取消 |

> **说明**：
> - API 响应中的 `status` 字段统一返回字符串值（如 `"completed"`），不再返回整数。
> - 任务列表接口的 `status` 查询参数使用整数值进行过滤（如 `status=2` 筛选已完成的任务）。

### 测试集文件格式

支持 JSON 和 CSV 两种格式，文件编码必须为 UTF-8。文件大小限制为 **10MB**。

**JSON 格式**：

```json
{
  "name": "产品文档测试集",
  "test_cases": [
    {
      "question": "如何重置密码？",
      "expected_answer": "在设置页面点击「重置密码」，输入邮箱后按邮件指引操作即可。"
    },
    {
      "question": "退款流程是什么？",
      "expected_answer": "提交退款申请后，客服将在3个工作日内审核并处理。"
    }
  ]
}
```

**CSV 格式**：

```csv
question,expected_answer
"如何重置密码？","在设置页面点击「重置密码」..."
"退款流程是什么？","提交退款申请后..."
```

| 字段 | 必填 | 说明 |
|------|------|------|
| question | 是 | 测试问题 |
| expected_answer | 是 | 期望答案 |
| name | 否 | 测试集名称（仅 JSON 格式支持） |

### 评估策略

#### 检索阶段评估策略

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| Precision@K | 前 K 个检索结果中相关文档的比例 | 命中相关文档数 / K |
| Hit Rate | 至少有一个相关文档被检索到的查询比例 | 统计含相关结果的查询占比 |
| MRR | 第一个相关文档排名倒数的均值 | 取第一个相关结果排名倒数求平均 |
| Recall@K | 所有相关文档中被检索到的比例（可选） | 命中的相关文档数 / 总相关文档数 |

#### 检索相关性判断方式

| 值 | 说明 |
|----|------|
| `llm` | LLM 逐条判断检索内容是否与问题相关（默认） |
| `embedding` | 计算 question 与检索结果的 Embedding 余弦相似度，取阈值判断 |

#### 生成阶段评估策略

| 指标 | 默认策略 | 可选策略 | 说明 |
|------|---------|---------|------|
| Correctness（正确性） | `llm` | `llm` / `embedding` / `hybrid` | 回答与期望答案的吻合度 |
| Faithfulness（忠实度） | `decompose` | `decompose` / `llm` | 回答是否基于检索上下文，无幻觉 |
| Answer Relevance（答案相关性） | `reverse_question` | `reverse_question` / `llm` | 回答是否与问题相关 |
| Quality（综合质量） | `llm` | `llm`（唯一） | 完整性、条理性、可读性综合评价 |

**策略说明**：

- `llm`：LLM-as-Judge 直接打分（1-10 分）
- `embedding`：计算 Embedding 余弦相似度，映射到 1-10 分
- `hybrid`：LLM 打分 × 0.7 + Embedding 相似度 × 0.3
- `decompose`：Claim 拆解法 — LLM 将回答拆解为独立 claims → 逐条验证是否可由上下文推导 → 支撑数/总数 → 映射到 10 分制
- `reverse_question`：反向问题法 — LLM 从回答反向生成候选问题 → 计算与原始问题的 Embedding 相似度 → 平均值映射到 10 分制

#### 端到端评估指标

| 指标 | 说明 | 计算方式 |
|------|------|----------|
| Context Precision | 检索到的相关文档是否排在前面 | 位置加权精确率 |
| Context Recall | 期望答案中的信息点是否都被检索到 | 拆解 expected_answer 为 claims，检查覆盖 |
| Answer Similarity | 生成答案与期望答案的语义相似度 | Embedding 余弦相似度 |

---

## 一、测试集管理

路由前缀：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets`

### 1.1 上传测试集

上传测试集文件（JSON/CSV）到 MinIO，创建测试集记录。同一测试集可用于多次测评。文件大小限制为 **10MB**。

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets`
- Content-Type：`multipart/form-data`
- 权限：编辑者（EDITOR）及以上
- 成功状态码：**201 Created**

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |

**请求参数（Form Data）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file | file | 是 | 测试集文件（.json 或 .csv，最大 10MB） |
| name | string | 是 | 测试集名称 |

**请求示例（cURL）**

```bash
curl -X POST "http://localhost:8100/api/v1/spaces/1/knowledge-bases/1/evaluation/test-sets" \
  -H "Authorization: Bearer <token>" \
  -F "file=@test_set.json" \
  -F "name=产品文档测试集"
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| test_set_id | int | 测试集 ID |
| name | string | 测试集名称 |
| filename | string | 文件名 |
| file_type | string | 文件类型（json/csv） |
| file_size | int | 文件大小（字节） |
| total_cases | int | 测试用例数量 |
| message | string | 提示信息（默认值：`"测试集已上传"`） |

**响应示例**

```json
{
  "test_set_id": 3,
  "name": "产品文档测试集",
  "filename": "test_set.json",
  "file_type": "json",
  "file_size": 1710,
  "total_cases": 5,
  "message": "测试集已上传"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| INVALID_TEST_SET | 400 | 文件格式不支持/内容为空/解析失败/文件超过 10MB |
| EVALUATION_ACCESS_DENIED | 403 | 无权操作（需要编辑者权限） |

---

### 1.2 获取测试集列表

获取指定知识库下的测试集列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| skip | int | 否 | `0` | ≥ 0 | 跳过的记录数 |
| limit | int | 否 | `20` | 1-100 | 返回的最大记录数 |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 测试集列表 |
| items[].id | int | 测试集 ID |
| items[].name | string | 测试集名称 |
| items[].filename | string | 文件名 |
| items[].file_type | string | 文件类型 |
| items[].file_size | int | 文件大小（字节） |
| items[].total_cases | int | 测试用例数量 |
| items[].created_at | datetime | 创建时间 |
| items[].updated_at | datetime | 更新时间 |
| total | int | 总数 |
| skip | int | 跳过数 |
| limit | int | 每页数量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 3,
      "name": "产品文档测试集",
      "filename": "test_set.json",
      "file_type": "json",
      "file_size": 1710,
      "total_cases": 5,
      "created_at": "2026-04-21T15:39:07",
      "updated_at": "2026-04-21T15:39:07"
    }
  ],
  "total": 2,
  "skip": 0,
  "limit": 20
}
```

---

### 1.3 获取测试集详情

获取指定测试集的详细信息。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets/{test_set_id}`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| test_set_id | integer | 是 | > 0 | 测试集 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 测试集 ID |
| name | string | 测试集名称 |
| filename | string | 文件名 |
| file_type | string | 文件类型 |
| file_size | int | 文件大小（字节） |
| total_cases | int | 测试用例数量 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

**响应示例**

```json
{
  "id": 3,
  "name": "产品文档测试集",
  "filename": "test_set.json",
  "file_type": "json",
  "file_size": 1710,
  "total_cases": 5,
  "created_at": "2026-04-21T15:39:07",
  "updated_at": "2026-04-21T15:39:07"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在 |

---

### 1.4 更新测试集名称

更新指定测试集的名称。

**请求**
- 方法：`PUT`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets/{test_set_id}`
- Content-Type：`application/json`
- 权限：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| test_set_id | integer | 是 | > 0 | 测试集 ID |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| name | string | 是 | 1-200 字符 | 新的测试集名称 |

**请求示例**

```json
{
  "name": "更新后的测试集名称"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 测试集 ID |
| name | string | 更新后的测试集名称 |
| filename | string | 文件名 |
| file_type | string | 文件类型 |
| file_size | int | 文件大小（字节） |
| total_cases | int | 测试用例数量 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

**响应示例**

```json
{
  "id": 3,
  "name": "更新后的测试集名称",
  "filename": "test_set.json",
  "file_type": "json",
  "file_size": 1710,
  "total_cases": 5,
  "created_at": "2026-04-21T15:39:07",
  "updated_at": "2026-04-21T16:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在 |
| EVALUATION_ACCESS_DENIED | 403 | 无权操作（需要编辑者权限） |

---

### 1.5 预览测试集用例

获取指定测试集中的测试用例内容列表，用于前端预览。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets/{test_set_id}/cases`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| test_set_id | integer | 是 | > 0 | 测试集 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| test_set_id | int | 测试集 ID |
| total_cases | int | 用例总数 |
| test_cases | array | 测试用例列表 |
| test_cases[].question | string | 测试问题 |
| test_cases[].expected_answer | string | 期望答案 |

**响应示例**

```json
{
  "test_set_id": 3,
  "total_cases": 2,
  "test_cases": [
    {
      "question": "如何重置密码？",
      "expected_answer": "在设置页面点击「重置密码」，输入邮箱后按邮件指引操作即可。"
    },
    {
      "question": "退款流程是什么？",
      "expected_answer": "提交退款申请后，客服将在3个工作日内审核并处理。"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在 |

---

### 1.6 删除测试集

删除指定的测试集。接口会验证测试集是否属于指定的 `space_id` 和 `kb_id`，若不匹配则返回 404。若有关联的待执行（pending）或执行中（running）任务则拒绝删除。删除时会同时清理 MinIO 中的测试集文件及关联任务的结果文件。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/test-sets/{test_set_id}`
- 权限：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| test_set_id | integer | 是 | > 0 | 测试集 ID |

**响应示例**

```json
{
  "success": true,
  "message": "测试集已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在，或不属于指定的 space_id/kb_id |
| EVALUATION_TASK_PENDING | 409 | 存在待执行或执行中的关联任务，无法删除 |

---

## 二、测评任务管理

路由前缀：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks`

### 2.1 创建测评任务

基于已有测试集创建测评任务，创建后自动异步并发执行（最多 5 路并发）。同一测试集可创建多个任务，使用不同 config 参数进行对比评测。

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks`
- Content-Type：`application/json`
- 权限：编辑者（EDITOR）及以上
- 成功状态码：**202 Accepted**

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| test_set_id | int | 是 | > 0 | 测试集 ID |
| name | string | 是 | 1-200 字符 | 任务名称 |
| config | object | 否 | — | 测评配置（不传则使用默认值） |

**config 参数说明**

> **模型选择**：前端可通过 `GET /api/v1/user/model-configs/available` 获取当前可用的模型列表，返回格式为 `{"llm": ["模型名1", ...], "embedding": ["模型名1", ...]}`。将选中的模型名称字符串填入下方 `llm_model` 或 `embedding_model` 字段即可。不传则使用系统默认模型。

| 参数名 | 类型 | 默认值 | 约束 | 说明 |
|--------|------|--------|------|------|
| search_mode | string | `content_hybrid` | — | 检索模式 |
| top_k | int | `5` | 1-50 | 检索返回数量 |
| score_threshold | float | `0.0` | 0.0-1.0 | 检索分数阈值 |
| enable_generation | bool | `true` | — | 是否启用生成阶段 |
| llm_model | string | null | — | 生成回答与评估打分使用的 LLM 模型名称（如 `"glm-4-flash"`、`"deepseek-chat"`）。null 使用系统默认，任务执行后自动回写实际使用的模型名 |
| embedding_model | string | null | — | 向量相似度计算使用的 Embedding 模型名称（如 `"embedding-3"`、`"bge-large-zh-v1.5"`）。null 使用系统默认，前端也可从可用模型列表中指定选择，任务执行后自动回写实际使用的模型名 |
| retrieval_relevance_strategy | string | `llm` | — | 检索相关性判断策略：`llm` / `embedding` |
| enable_mrr | bool | `true` | — | 是否启用 MRR 指标 |
| enable_recall_at_k | bool | `false` | — | 是否启用 Recall@K |
| correctness_strategy | string | `llm` | — | 正确性评估策略：`llm` / `embedding` / `hybrid` |
| faithfulness_strategy | string | `decompose` | — | 忠实度评估策略：`decompose` / `llm` |
| relevance_strategy | string | `reverse_question` | — | 相关性评估策略：`reverse_question` / `llm` |
| enable_context_precision | bool | `true` | — | 是否启用 Context Precision |
| enable_context_recall | bool | `true` | — | 是否启用 Context Recall |
| enable_answer_similarity | bool | `true` | — | 是否启用 Answer Similarity |
| scoring_dimensions | string[] | `["correctness","faithfulness","relevance","quality"]` | — | 启用的评分维度 |

**请求示例**

```json
{
  "test_set_id": 3,
  "name": "第一次测评",
  "config": {
    "top_k": 5,
    "llm_model": "glm-4-flash",
    "embedding_model": "embedding-3",
    "enable_generation": true,
    "faithfulness_strategy": "decompose",
    "relevance_strategy": "reverse_question"
  }
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| task_id | int | 测评任务 ID |
| name | string | 任务名称 |
| test_set_id | int | 关联测试集 ID |
| status | string | 任务状态（`"pending"`） |
| message | string | 提示信息（默认值：`"测评任务已创建，等待执行"`） |

**响应示例**

```json
{
  "task_id": 1,
  "name": "第一次测评",
  "test_set_id": 3,
  "status": "pending",
  "message": "测评任务已创建，等待执行"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在 |
| EVALUATION_CONFIG_ERROR | 400 | 测评配置参数无效 |
| EVALUATION_ACCESS_DENIED | 403 | 无权操作（需要编辑者权限） |

---

### 2.2 获取测评任务列表

获取指定知识库下的测评任务列表，支持按状态过滤。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| skip | int | 否 | `0` | ≥ 0 | 跳过的记录数 |
| limit | int | 否 | `20` | 1-100 | 返回的最大记录数 |
| status | int | 否 | 无 | 1/2/3/5/6 | 按状态过滤：`1`（pending）、`2`（completed）、`3`（failed）、`5`（running）、`6`（cancelled） |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 任务列表 |
| items[].id | int | 任务 ID |
| items[].test_set_id | int | 关联测试集 ID |
| items[].name | string | 任务名称 |
| items[].status | string | 任务状态（见 EvaluationStatus） |
| items[].created_at | datetime | 创建时间 |
| items[].updated_at | datetime | 更新时间 |
| total | int | 总数 |
| skip | int | 跳过数 |
| limit | int | 每页数量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "test_set_id": 3,
      "name": "第一次测评",
      "status": "completed",
      "created_at": "2026-04-21T15:39:07",
      "updated_at": "2026-04-21T15:44:07"
    }
  ],
  "total": 2,
  "skip": 0,
  "limit": 20
}
```

---

### 2.3 获取测评任务详情

获取指定测评任务的详细信息，包含本次使用的测评配置。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 任务 ID |
| test_set_id | int | 关联测试集 ID |
| name | string | 任务名称 |
| status | string | 任务状态 |
| config | object / null | 测评配置（创建时保存的参数） |
| error_message | string / null | 错误信息（失败时有值） |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

**响应示例**

```json
{
  "id": 1,
  "test_set_id": 3,
  "name": "第一次测评",
  "status": "completed",
  "config": {
    "search_mode": "content_hybrid",
    "top_k": 5,
    "score_threshold": 0.0,
    "enable_generation": true,
    "llm_model": "glm-4-flash",
    "embedding_model": "embedding-3",
    "retrieval_relevance_strategy": "llm",
    "enable_mrr": true,
    "enable_recall_at_k": false,
    "correctness_strategy": "llm",
    "faithfulness_strategy": "decompose",
    "relevance_strategy": "reverse_question",
    "enable_context_precision": true,
    "enable_context_recall": true,
    "enable_answer_similarity": true,
    "scoring_dimensions": ["correctness", "faithfulness", "relevance", "quality"]
  },
  "error_message": null,
  "created_at": "2026-04-21T15:39:07",
  "updated_at": "2026-04-21T15:44:07"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |

---

### 2.4 删除测评任务

删除指定的测评任务。接口会验证任务是否属于指定的 `space_id` 和 `kb_id`，若不匹配则返回 404。待执行（pending）或执行中（running）的任务不可删除，删除时会同时清理 MinIO 中的结果文件。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}`
- 权限：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**响应示例**

```json
{
  "success": true,
  "message": "测评任务已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在，或不属于指定的 space_id/kb_id |
| EVALUATION_TASK_PENDING | 409 | 任务正在执行中或等待执行，无法删除 |

---

### 2.5 取消测评任务

取消指定的测评任务。仅待执行（pending）或执行中（running）状态的任务可以取消。

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}/cancel`
- Content-Type：`application/json`
- 权限：编辑者（EDITOR）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| task_id | int | 测评任务 ID |
| status | string | 取消后的状态（`"cancelled"`） |
| message | string | 提示信息（默认值：`"任务已取消"`） |

**响应示例**

```json
{
  "task_id": 1,
  "status": "cancelled",
  "message": "任务已取消"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |
| EVALUATION_TASK_NOT_CANCELLABLE | 409 | 非 pending/running 状态的任务不可取消 |
| EVALUATION_ACCESS_DENIED | 403 | 无权操作（需要编辑者权限） |

---

### 2.6 获取任务执行进度

获取测评任务的实时执行进度。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}/progress`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| task_id | int | 测评任务 ID |
| status | string | 任务当前状态 |
| current | int | 已完成的用例数（默认值：`0`） |
| total | int | 总用例数（默认值：`0`） |

**响应示例**

```json
{
  "task_id": 1,
  "status": "running",
  "current": 5,
  "total": 10
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |

---

### 2.7 提交人工评分

对已完成任务的测试用例逐条提交人工评分（1-10分），可附加评语。提交后报告的 `summary.human_scores` 会自动更新。仅已完成（completed）状态的任务可提交评分。

**请求**
- 方法：`POST`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}/scores`
- Content-Type：`application/json`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**请求参数（Body）**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| scores | array | 是 | 1-500 条 | 评分列表 |
| scores[].index | int | 是 | ≥ 0 | 测试用例索引（从 0 开始） |
| scores[].score | int | 是 | 1-10 | 人工评分 |
| scores[].comment | string | 否 | 最大 1000 字符 | 评语 |

**请求示例**

```json
{
  "scores": [
    {"index": 0, "score": 9, "comment": "回答准确全面"},
    {"index": 1, "score": 7, "comment": "基本正确但不够完整"},
    {"index": 2, "score": 8, "comment": "描述准确"}
  ]
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| updated_count | int | 实际更新的评分数量 |
| message | string | 提示信息（默认值：`"评分提交成功"`） |

**响应示例**

```json
{
  "updated_count": 3,
  "message": "评分提交成功"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |
| EVALUATION_TASK_NOT_COMPLETED | 409 | 非 completed 状态不允许提交评分 |

---

### 2.8 获取测评报告

获取测评任务的汇总报告，包含逐条详情和汇总指标。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}/report`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| task_id | int | 任务 ID |
| name | string | 任务名称 |
| status | string | 任务状态 |
| total_cases | int | 测试用例总数 |
| completed_cases | int | 已完成用例数（默认值：`0`） |
| summary | object / null | 汇总指标 |
| details | array / null | 逐条详情 |

**summary 结构**

```json
{
  "total_cases": 5,
  "completed_cases": 5,
  "elapsed_seconds": 267.1,
  "retrieval": {
    "precision_at_k": 0.32,
    "hit_rate": 1.0,
    "mrr": 1.0
  },
  "generation": {
    "faithfulness": 8.2,
    "answer_relevance": 8.2,
    "correctness": 9.4,
    "quality": 7.0,
    "overall": 8.2
  },
  "end_to_end": {
    "context_precision": 0.32,
    "answer_similarity": 0.8818
  },
  "human_scores": null
}
```

**details 中每条记录结构**

```json
{
  "index": 0,
  "question": "FastAPI 的核心优势有哪些？",
  "expected_answer": "...",
  "generated_answer": "...",
  "retrieved_chunks": [
    {
      "chunk_id": "chunk_39_2",
      "content": "...",
      "score": 1.0
    }
  ],
  "retrieval": {
    "precision_at_k": 1.0
  },
  "generation_scores": {
    "faithfulness": 10,
    "answer_relevance": 9,
    "correctness": 9,
    "quality": 8
  },
  "end_to_end": {
    "context_precision": 1.0,
    "answer_similarity": 0.9215
  },
  "human_score": null,
  "human_comment": null
}
```

**响应示例**

```json
{
  "task_id": 1,
  "name": "第一次测评",
  "status": "completed",
  "total_cases": 5,
  "completed_cases": 5,
  "summary": {
    "total_cases": 5,
    "completed_cases": 5,
    "elapsed_seconds": 267.1,
    "retrieval": {
      "precision_at_k": 0.32,
      "hit_rate": 1.0,
      "mrr": 1.0
    },
    "generation": {
      "faithfulness": 8.2,
      "answer_relevance": 8.2,
      "correctness": 9.4,
      "quality": 7.0,
      "overall": 8.2
    },
    "end_to_end": {
      "context_precision": 0.32,
      "answer_similarity": 0.8818
    },
    "human_scores": null
  },
  "details": [...]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |

---

### 2.9 导出测评结果

以文件形式下载测评结果，支持 JSON 和 CSV 格式。仅已完成（completed）状态的任务可导出。

**请求**
- 方法：`GET`
- URL：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation/tasks/{task_id}/export`
- 权限：成员（MEMBER）及以上

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| space_id | integer | 是 | > 0 | 知识空间 ID |
| kb_id | integer | 是 | > 0 | 知识库 ID |
| task_id | integer | 是 | > 0 | 测评任务 ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| format | string | 否 | `json` | 仅 `json` / `csv` | 导出格式 |

**响应**

- JSON 格式：`Content-Type: application/json`，返回完整结果 JSON（结构同 report 的 details）
- CSV 格式：`Content-Type: text/csv`，返回扁平化的逐条详情

**CSV 列定义**

| 列名 | 说明 |
|------|------|
| index | 用例索引 |
| question | 测试问题 |
| expected_answer | 期望答案 |
| generated_answer | 生成的回答 |
| faithfulness | 忠实度评分 |
| answer_relevance | 答案相关性评分 |
| correctness | 正确性评分 |
| quality | 质量评分 |
| context_precision | 上下文精确率 |
| answer_similarity | 答案语义相似度 |
| human_score | 人工评分 |
| human_comment | 人工评语 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |
| EVALUATION_TASK_PENDING | 409 | 任务正在执行中或等待执行，无法导出 |
| `VALIDATION_ERROR` | 422 | format 参数值无效（仅支持 json/csv） |

---

## 典型使用流程

```
1. 准备测试集文件（JSON 或 CSV 格式，最大 10MB）

2. POST /test-sets               → 上传测试集，获得 test_set_id

3. GET /test-sets/{test_set_id}/cases  → 预览测试集用例内容（可选）

4. POST /tasks                   → 创建测评任务（传 test_set_id + config），获得 task_id
   ├─ 同一测试集可创建多个任务
   └─ 不同 config 可对比评测效果

5. GET /tasks/{task_id}/progress → 查询任务执行进度（current / total）
   ├─ status=pending（待执行）→ 继续等待
   ├─ status=running（执行中）→ 查看进度
   ├─ status=completed（已完成）→ 查看结果
   ├─ status=failed（执行失败）→ 查看 error_message
   └─ 若不再需要，可调用 POST /tasks/{task_id}/cancel 取消任务

6. POST /tasks/{task_id}/cancel  → 取消正在执行的任务（可选，仅 pending/running 可取消）

7. GET /tasks/{task_id}/report   → 获取汇总报告

8. POST /tasks/{task_id}/scores  → 提交人工评分（可选，仅 completed 状态可提交）

9. GET /tasks/{task_id}/export   → 导出结果（JSON 或 CSV，仅 completed 状态可导出）
```

**并发执行说明**：测评任务创建后自动异步执行，采用并发方式处理测试用例（最多 5 路并发），执行速度显著提升。任务开始时状态从 `pending` 变为 `running`，全部完成后变为 `completed`。

---

## 模块错误码汇总

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| INVALID_TEST_SET | 400 | 测试集文件无效（格式不支持/内容为空/解析失败/文件超过 10MB） |
| EVALUATION_CONFIG_ERROR | 400 | 测评配置参数无效 |
| EVALUATION_ACCESS_DENIED | 403 | 无权操作该测评任务 |
| EVALUATION_TEST_SET_NOT_FOUND | 404 | 测试集不存在 |
| EVALUATION_TASK_NOT_FOUND | 404 | 测评任务不存在 |
| EVALUATION_TASK_PENDING | 409 | 任务正在执行中或等待执行，无法删除/导出 |
| EVALUATION_TASK_NOT_CANCELLABLE | 409 | 非 pending/running 状态的任务不可取消 |
| EVALUATION_TASK_NOT_COMPLETED | 409 | 非 completed 状态不允许操作（如提交评分） |
| EVALUATION_ERROR | 500 | 测评模块内部错误 |
