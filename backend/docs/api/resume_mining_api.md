# 简历挖掘应用 API 文档

## 概述

简历挖掘应用提供简历上传解析、结构化数据提取、面试准备报告生成、自动追问、面试准备建议、简历优化建议等功能。用户上传简历文件（PDF/DOCX/TXT/MD）后，系统自动在后台执行完整 Pipeline（S1-S12），包括：简历解析、分析报告、自动追问、面试准备建议、简历优化建议，最终生成三段式 Markdown 报告。

模块路由前缀：`/api/v1/apps`

| 子模块 | 路由 | 说明 |
|-------|------|------|
| 简历上传 | `POST .../resume/upload` | 上传简历，触发后台 Pipeline |
| 会话管理 | `GET .../resume/sessions` 等 | 列表、详情、删除 |
| 报告获取 | `GET .../sessions/{id}/report` / `download` | 查看/下载 Markdown 报告 |

### 认证方式

所有接口均需要 JWT 认证，在请求头中携带：

```
Authorization: Bearer <token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. 用户只能访问自己的简历会话
3. 上传接口使用 `multipart/form-data`，其余接口使用 `application/json`

### 通用 Header

| Header | 值 | 必填 | 说明 |
|--------|------|------|------|
| Authorization | `Bearer <token>` | 是 | JWT 访问令牌 |
| Content-Type | `multipart/form-data` 或 `application/json` | 是 | 上传用 multipart，其余用 json |

### 通用响应格式

**成功响应**：各接口独立定义。

**错误响应**：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-05-11T10:00:00+08:00"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| SESSION_NOT_FOUND | 404 | 简历会话不存在或无权访问 |
| PARSE_ERROR | 500 | 简历解析失败（文件格式不支持、报告未生成、LLM 调用失败等） |
| INVALID_FILE_TYPE | 400 | 不支持的文件格式 |
| INVALID_CONFIG | 400 | 配置参数校验失败 |
| FILE_SIZE_EXCEEDED | 400 | 文件大小超过限制 (50MB) |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## 枚举值定义

### 简历会话状态（ResumeSessionStatus）

| 值 | 名称 | 说明 |
|----|------|------|
| `0` | DRAFT | 草稿 |
| `1` | PARSING | 正在解析简历（S1-S4） |
| `2` | ANALYZING | 正在生成分析报告（S5-S9） |
| `3` | READY | 分析完成，中间报告已生成 |
| `4` | PROBING | 自动追问进行中（S10-S11） |
| `5` | COMPLETED | Pipeline 全部完成，最终报告已生成 |
| `6` | FAILED | Pipeline 失败，查看 error_message |

---

## 一、简历上传

### 1.1 上传简历并解析

上传简历文件，系统立即返回会话（`status=1` PARSING），然后在后台异步执行完整 Pipeline（S1-S12）。前端可通过轮询会话详情接口获取进度。

> **重要变更**：此接口为异步模式，调用后立即返回，Pipeline 在后台运行。前端应通过 `GET .../sessions/{id}` 轮询 `status` 字段跟踪进度。

`POST` `/api/v1/apps/resume/upload`

**Content-Type**：`multipart/form-data`

**请求参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| file | File | 是 | — | 简历文件，支持 `.pdf`、`.docx`、`.doc`、`.txt`、`.md`，最大 50MB |
| jd_text | string | 否 | `""` | 岗位 JD 文本。有 JD 时追问会侧重岗位相关技术 |
| config | string (JSON) | 否 | `"{}"` | 追问配置，JSON 字符串 |
| llm_model | string | 否 | `""` | 指定使用的 LLM 模型名称。不传则使用用户默认 LLM 模型 |

**config 参数详情**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| breadth | int | 否 | — | 追问广度（知识点覆盖数量） |
| depth | int | 否 | — | 追问深度（每个知识点的追问轮数） |
| llm_model | string | 否 | — | LLM 模型名称（可被顶层 llm_model 参数覆盖） |

**请求示例**：

```
POST /api/v1/apps/resume/upload
Content-Type: multipart/form-data

file: (binary) 张三_简历.pdf
jd_text: "岗位职责：1. 负责公司核心服务的后端开发..."
config: '{"breadth": 10, "depth": 3}'
llm_model: "gpt-4o"
```

**响应参数**（ResumeSessionResponse）：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | string | 会话 UUID |
| user_id | int | 用户 ID |
| resume_filename | string | 原始文件名 |
| structured_resume | object \| null | 结构化简历数据（异步模式下上传时为 null，Pipeline 完成后有值） |
| jd_text | string | JD 原文 |
| md_report_url | string \| null | Markdown 报告 MinIO 文件地址（Pipeline 完成后有值） |
| status | int | 会话状态（上传返回时为 `1` PARSING） |
| config | object | 用户配置 |
| error_message | string \| null | 错误信息（仅 FAILED 状态） |
| created_at | string \| null | 创建时间 (ISO 8601) |
| updated_at | string \| null | 更新时间 (ISO 8601) |

**structured_resume 结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| personal_info | object | 个人信息（name, phone, email, location, summary 等） |
| work_experience | object[] | 工作经历列表 |
| project_experience | object[] | 项目经历列表 |
| education | object[] | 教育经历列表 |
| skills | object | 技能数据（含 skill_groups 分组） |
| publications | object | 论文/专利/技术写作（papers, patents, technical_writings） |
| metadata | object \| null | 解析元数据（项目数、论文数、总工作年限等） |
| validation_warnings | object[] | 校验警告（如缺失量化数据） |
| resume_summary | string | 简历总结 |

**work_experience 子结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| company | string | 公司名称 |
| company_brief | string | 公司简介 |
| position | string | 职位 |
| department | string | 部门 |
| level | string | 职级 |
| employment_type | string | 雇佣类型（fulltime/intern/parttime） |
| start_date | string | 开始日期（YYYY.MM） |
| end_date | string | 结束日期（YYYY.MM 或 "至今"） |
| duration_months | int | 工作月数 |
| is_current | bool | 是否在职 |
| team_context | string | 团队规模和职责 |
| responsibilities | string[] | 工作职责列表 |
| achievements | object[] | 成果列表（含 description, metric, impact） |
| tech_stack | string[] | 使用的技术栈 |
| key_projects | object[] | 关联的项目概要（name, role, brief） |
| promotion_history | object[] | 晋升记录（date, from_level, to_level, reason） |
| leave_reason | string | 离职原因 |

**project_experience 子结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| name | string | 项目名称 |
| source | string | 来源：work/personal/education/open_source |
| associated_company | string | 关联公司 |
| role | string | 担任角色 |
| team_size | int | 团队规模 |
| my_contribution_ratio | string | 个人贡献比例 |
| start_date | string | 开始日期 |
| end_date | string | 结束日期 |
| duration_months | int | 项目月数 |
| background | string | 项目背景 |
| tech_stack | object | 分层技术栈（languages, frameworks, middleware, infrastructure, tools） |
| architecture | string | 架构描述 |
| responsibilities | string[] | 项目职责 |
| challenges | object[] | 挑战列表（challenge + solution + result） |
| achievements | object[] | 成果列表（含量化指标） |
| highlights | string[] | 可追问亮点 |
| probing_directions | string[] | 建议追问方向 |

**skills 子结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| skill_groups | object[] | 技能分组列表 |
| skill_groups[].category | string | 分类（programming_languages/frameworks/middleware/...） |
| skill_groups[].label | string | 显示名称 |
| skill_groups[].items | object[] | 技能项列表（name, proficiency, years, source_projects） |
| certifications | object[] | 证书列表（name, date） |
| languages | object[] | 语言能力列表（language, proficiency, certificate） |

**publications 子结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| papers | object[] | 论文列表（title, authors, author_rank, is_first_author, venue, venue_level, keywords, my_contribution 等） |
| patents | object[] | 专利列表（title, patent_type, patent_number, status, inventors 等） |
| technical_writings | object[] | 技术写作列表（title, platform, url, views, likes） |

**上传响应示例**（立即返回，Pipeline 在后台运行）：

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": 1,
  "resume_filename": "张三_简历.pdf",
  "structured_resume": null,
  "jd_text": "岗位职责：1. 负责公司核心服务的后端开发...",
  "md_report_url": null,
  "status": 1,
  "config": {
    "breadth": 10,
    "depth": 3,
    "llm_model": "gpt-4o"
  },
  "error_message": null,
  "created_at": "2026-05-31T10:00:00",
  "updated_at": "2026-05-31T10:00:00"
}
```

**Pipeline 完成后的会话详情示例**（通过 `GET .../sessions/{id}` 获取）：

```json
{
  "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "user_id": 1,
  "resume_filename": "张三_简历.pdf",
  "structured_resume": {
    "personal_info": {
      "name": "张三",
      "phone": "138****1234",
      "email": "zhangsan@example.com",
      "location": "北京市",
      "age": null,
      "gender": "",
      "summary": "5年后端开发经验，专注于高并发分布式系统",
      "job_intention": null,
      "social_links": []
    },
    "work_experience": [
      {
        "company": "字节跳动",
        "company_brief": "",
        "position": "高级后端工程师",
        "department": "",
        "level": "",
        "employment_type": "fulltime",
        "start_date": "2021.06",
        "end_date": "至今",
        "duration_months": 47,
        "is_current": true,
        "team_context": "",
        "responsibilities": [],
        "achievements": [
          {
            "description": "设计分布式缓存方案，推荐接口 P99 延迟从 200ms 降至 50ms",
            "metric": "P99 延迟降低 75%",
            "impact": "high"
          }
        ],
        "tech_stack": ["Go", "Kafka", "Redis", "Kubernetes"],
        "key_projects": [],
        "promotion_history": [],
        "leave_reason": ""
      }
    ],
    "project_experience": [
      {
        "name": "推荐系统实时特征平台",
        "source": "work",
        "associated_company": "",
        "role": "技术负责人",
        "team_size": 0,
        "my_contribution_ratio": "",
        "start_date": "",
        "end_date": "",
        "duration_months": 0,
        "background": "",
        "tech_stack": {
          "languages": ["Go", "Python"],
          "frameworks": ["gRPC", "Flink"],
          "middleware": ["Kafka", "Redis Cluster", "ClickHouse"],
          "infrastructure": ["Kubernetes"],
          "tools": ["Prometheus", "Grafana"]
        },
        "architecture": "",
        "responsibilities": [],
        "challenges": [
          {
            "challenge": "单日特征写入量峰值达 50 亿条，Redis 写入成为瓶颈",
            "solution": "设计两级缓存架构",
            "result": "写入吞吐量提升 3 倍"
          }
        ],
        "achievements": [],
        "highlights": [],
        "probing_directions": [
          "为什么选择 Flink 而不是 Spark Streaming？",
          "Redis Cluster 分片策略怎么设计的？"
        ]
      }
    ],
    "skills": {
      "skill_groups": [
        {
          "category": "programming_languages",
          "label": "编程语言",
          "items": [
            { "name": "Go", "proficiency": "expert", "years": 5, "source_projects": [] },
            { "name": "Python", "proficiency": "expert", "years": 6, "source_projects": [] }
          ]
        }
      ],
      "certifications": [],
      "languages": []
    },
    "publications": {
      "papers": [],
      "patents": [],
      "technical_writings": []
    },
    "metadata": {
      "parse_time": "",
      "source_file": "张三_简历.pdf",
      "total_experience_months": 47,
      "companies_count": 1,
      "projects_count": 1,
      "papers_count": 0,
      "patents_count": 0
    },
    "validation_warnings": [],
    "resume_summary": ""
  },
  "jd_text": "岗位职责：1. 负责公司核心服务的后端开发...",
  "md_report_url": "resume/a1b2c3d4-e5f6-7890-abcd-ef1234567890/report.md",
  "status": 5,
  "config": {
    "breadth": 10,
    "depth": 3,
    "llm_model": "gpt-4o"
  },
  "error_message": null,
  "created_at": "2026-05-31T10:00:00",
  "updated_at": "2026-05-31T10:05:00"
}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| PARSE_ERROR | 500 | LLM 模型未配置 |
| INVALID_FILE_TYPE | 400 | 不支持的文件格式 |
| INVALID_CONFIG | 400 | config 参数不是合法 JSON 或字段类型错误 |
| FILE_SIZE_EXCEEDED | 400 | 文件大小超过 50MB |
| VALIDATION_ERROR | 422 | 缺少 file 参数 |

**注意**：

> - 此接口为异步模式，调用后立即返回 `status=1`（PARSING）
> - Pipeline 在后台执行（S1-S12），前端应通过轮询 `GET .../sessions/{id}` 跟踪进度
> - 无 JD 时 `jd_text` 留空或不传，系统会按纯简历模式分析
> - `llm_model` 参数优先于 `config.llm_model`，两者都不传则使用用户默认 LLM 模型
> - Pipeline 失败时会话 `status=6`（FAILED），错误信息写入 `error_message`

---

## 二、会话管理

### 2.1 获取简历会话列表

获取当前用户的简历解析历史列表。

`GET` `/api/v1/apps/resume/sessions`

**查询参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `20` | 每页数量（1-100） |
| offset | int | 否 | `0` | 偏移量 |
| status | int | 否 | — | 按状态筛选（ResumeSessionStatus 枚举值） |

**响应参数**（ResumeSessionListResponse）：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sessions | object[] | 会话列表（ResumeSessionResponse 格式，structured_resume 等大字段可能为 null） |
| total | int | 总数 |

**响应示例**：

```json
{
  "sessions": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "user_id": 1,
      "resume_filename": "张三_简历.pdf",
      "structured_resume": null,
      "jd_text": "",
      "md_report_url": "resume/a1b2c3d4-e5f6-7890-abcd-ef1234567890/report.md",
      "status": 5,
      "config": {},
      "error_message": null,
      "created_at": "2026-05-31T10:00:00",
      "updated_at": "2026-05-31T10:05:00"
    }
  ],
  "total": 1
}
```

---

### 2.2 获取简历会话详情

获取指定简历会话的完整数据（含结构化简历、报告地址等）。

`GET` `/api/v1/apps/resume/sessions/{session_id}`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应参数**：ResumeSessionResponse，同 1.1 的完整响应格式。

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

### 2.3 获取报告内容

获取简历会话的 Markdown 报告文本内容，从 MinIO 读取。

`GET` `/api/v1/apps/resume/sessions/{session_id}/report`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应格式**：`text/markdown`

**成功响应**：直接返回 Markdown 文本内容。

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| PARSE_ERROR | 500 | 报告尚未生成（md_report_url 为空）或读取失败 |

---

### 2.4 下载报告文件

下载简历会话的 Markdown 报告文件（.md），从 MinIO 读取，浏览器触发文件下载。

`GET` `/api/v1/apps/resume/sessions/{session_id}/download`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应格式**：`text/markdown`

**响应 Header**：

| Header | 值 | 说明 |
|--------|------|------|
| Content-Disposition | `attachment; filename*=UTF-8''<encoded_filename>` | 触发浏览器下载，文件名格式为 `<原文件名>_report.md` |

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| PARSE_ERROR | 500 | 报告尚未生成（md_report_url 为空）或读取失败 |

---

### 2.5 删除简历会话

删除指定的简历会话及其 MinIO 文件（原始简历文件和报告文件）。

`DELETE` `/api/v1/apps/resume/sessions/{session_id}`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 操作结果（"删除成功"） |

**响应示例**：

```json
{
  "message": "删除成功"
}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

**注意**：

> - 删除操作不可恢复
> - 即使 MinIO 文件删除失败，数据库记录仍会被删除
> - MinIO 文件删除失败不会阻断整个删除操作（仅记录警告日志）

---

## 三、完整调用流程

### 有 JD 的完整流程

```
1. POST /api/v1/apps/resume/upload
   file=简历.pdf, jd_text=岗位JD, config={"breadth": 10, "depth": 3}, llm_model="gpt-4o"
   → 立即返回 { status: 1 (PARSING) }

2. GET /api/v1/apps/resume/sessions/{id}  （轮询）
   → status=1 (PARSING) → status=2 (ANALYZING) → status=4 (PROBING) → status=5 (COMPLETED)

3. GET /api/v1/apps/resume/sessions/{id}/report
   → 获取最终 Markdown 报告内容

4. GET /api/v1/apps/resume/sessions/{id}/download
   → 下载 .md 报告文件
```

### 无 JD 的流程

与上述相同，但上传时 `jd_text` 留空。系统会按纯简历内容挖掘，追问侧重项目架构决策和技术深度验证。

### 查看历史记录

```
1. GET /api/v1/apps/resume/sessions?limit=20&offset=0
   → 获取会话列表

2. GET /api/v1/apps/resume/sessions/{id}
   → 查看某个会话详情

3. DELETE /api/v1/apps/resume/sessions/{id}
   → 删除不需要的会话
```

---

## 四、Pipeline 技术说明

### Pipeline 阶段

上传后，系统在后台异步执行 S1-S12 全流程：

| 阶段 | 步骤 | 说明 | LLM 调用次数 |
|------|------|------|-------------|
| 解析 | S1 文本提取 | 工具处理（PDF/DOCX/TXT/MD） | 0 |
| 解析 | S2 章节切割 | LLM 识别简历结构 | 1 |
| 解析 | S3 并行解析 | 并行解析各模块 | ~6（并行） |
| 解析 | S4 数据合并 | 合并结构化数据 | 0 |
| 分析 | S5 JD 图谱 | 提取 JD 技能要求（有 JD 时） | 0-1 |
| 分析 | S6 交叉映射 | 简历-JD 匹配 | 0 |
| 分析 | S7 追问策略 | 生成追问计划和权重 | 1 |
| 分析 | S8 前缀知识 | 生成面试前缀知识 | 1 |
| 分析 | S9 分析报告 | 生成中间 Markdown 报告 | 1 |
| 追问 | S10 自动追问 | 基于追问计划自动执行追问 | N（按知识点数） |
| 追问 | S11 面试准备建议 | 生成面试准备建议 | 1 |
| 追问 | S11-NEW 简历优化建议 | 生成简历优化建议 | 1 |
| 报告 | S12 最终报告 | 组装三段式报告（分析+追问+建议） | 0 |
| **总计** | | | **~12 + N** |

### 状态流转

```
上传 → PARSING(1) → ANALYZING(2) → PROBING(4) → COMPLETED(5)
                                                    ↘ FAILED(6)
```

### 权重计算公式

**有 JD 时**：

```
probing_weight = jd_relevance × 0.5 + resume_depth × 0.3 + derivative_richness × 0.2
```

**无 JD 时**：

```
probing_weight = resume_depth × 0.6 + derivative_richness × 0.3 + skill_proficiency × 0.1
```

### JD 关联度计算

| 匹配级别 | 条件 | jd_relevance |
|---------|------|-------------|
| 精确匹配 | JD required_skills.name 完全一致 | 1.0 |
| 模糊匹配 | JD 描述中提到相关词 | 0.7 |
| 间接关联 | 同一技术栈/领域 | 0.3 |
| 无关联 | — | 0.1 |
| 无 JD | — | 0.5（统一基准） |
