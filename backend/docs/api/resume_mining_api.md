# 简历挖掘应用 API 文档

## 概述

简历挖掘应用是应用中心的首个小应用，提供简历上传解析、结构化数据提取、面试准备报告生成、对话式追问等功能。用户上传简历文件（PDF/DOCX）后，系统自动解析为结构化数据，结合可选的岗位 JD 生成面试前缀知识和追问计划，最后通过 SSE 流式对话进行项目经验深度挖掘。

模块包含三个子模块：

| 子模块 | 路由前缀 | 说明 |
|-------|---------|------|
| 应用中心 | `/api/v1/apps` | 应用列表查询 |
| 简历解析 | `/api/v1/apps/resume/upload` 等 | 上传解析、会话管理 |
| 追问对话 | `/api/v1/apps/resume/sessions/{id}/probing` 等 | 创建追问、SSE 对话、进度查询 |

### 认证方式

所有接口均需要 JWT 认证，在请求头中携带：

```
Authorization: Bearer <token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. 用户只能访问自己的简历会话和追问会话
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
| PROBING_NOT_FOUND | 404 | 追问会话不存在或无权访问 |
| PARSE_ERROR | 500 | 简历解析失败（文件格式不支持、LLM 调用失败等） |
| INTERNAL_ERROR | 500 | 服务器内部错误 |

---

## 枚举值定义

### 简历会话状态（resume_session_status）

| 值 | 名称 | 说明 |
|----|------|------|
| `0` | DRAFT | 草稿，解析未开始或失败 |
| `1` | PARSING | 正在解析简历 |
| `2` | ANALYZING | 正在生成分析报告 |
| `3` | READY | 解析完成，可以查看报告或开始追问 |
| `4` | PROBING | 追问进行中 |
| `5` | COMPLETED | 追问已完成 |

### 追问会话状态（probing_session_status）

| 值 | 名称 | 说明 |
|----|------|------|
| `0` | READY | 已创建，等待开始 |
| `1` | PROBING | 正在追问中 |
| `2` | SUMMARY | 正在生成总结报告 |
| `3` | FREE | 自由对话模式（追问完成后） |
| `4` | COMPLETED | 已完成 |

### 广度模式（breadth_mode）

| 值 | 说明 |
|----|------|
| `balanced` | 均衡模式（默认）— 覆盖所有技术但 JD 相关的分配更多轮数 |
| `full` | 全面覆盖 — 覆盖所有项目中的所有技术 + 衍生 |
| `focused` | 聚焦 JD — 只覆盖与 JD 关联度 > 0.3 的技术 |

---

## 一、应用中心

### 1.1 获取应用列表

获取当前系统中所有已启用的应用列表。

`GET` `/api/v1/apps`

**请求参数**：无

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| apps | object[] | 应用列表 |
| apps[].id | string | 应用ID（如 `resume_mining`） |
| apps[].name | string | 应用名称 |
| apps[].description | string | 应用描述 |
| apps[].icon | string | 图标 |
| apps[].route_path | string | 前端路由路径（如 `/apps/resume`） |
| apps[].status | int | 状态（1=启用） |
| apps[].sort_order | int | 排序序号 |

**响应示例**：

```json
{
  "apps": [
    {
      "id": "resume_mining",
      "name": "简历挖掘",
      "description": "上传简历，AI 自动解析结构化数据，生成面试准备报告并进行项目经验深度追问",
      "icon": "document",
      "route_path": "/apps/resume",
      "status": 1,
      "sort_order": 0
    }
  ]
}
```

---

## 二、简历解析

### 2.1 上传简历并解析

上传简历文件，系统自动执行完整解析 Pipeline（S1-S4 解析 + S5-S9 分析），返回结构化简历数据、分析报告和追问计划。

> **注意**：此接口耗时较长（约 10-30 秒），因为需要多次 LLM 调用。前端应显示加载状态。

`POST` `/api/v1/apps/resume/upload`

**Content-Type**：`multipart/form-data`

**请求参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| file | File | 是 | — | 简历文件，支持 `.pdf`、`.docx`、`.doc`、`.txt`、`.md` |
| jd_text | string | 否 | `""` | 岗位 JD 文本。有 JD 时追问会侧重岗位相关技术 |
| config | string (JSON) | 否 | `"{}"` | 追问配置，JSON 字符串 |

**config 参数详情**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| total_rounds | int | 否 | `30` | 总追问轮数（10-100） |
| breadth_mode | string | 否 | `"balanced"` | 广度模式：`balanced` / `full` / `focused` |

**请求示例**：

```
POST /api/v1/apps/resume/upload
Content-Type: multipart/form-data

file: (binary) 张三_简历.pdf
jd_text: "岗位职责：1. 负责公司核心服务的后端开发..."
config: '{"total_rounds": 30, "breadth_mode": "balanced"}'
```

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | string | 会话 UUID |
| user_id | int | 用户 ID |
| resume_filename | string | 原始文件名 |
| structured_resume | object \| null | 结构化简历数据（详见下方） |
| jd_text | string | JD 原文 |
| jd_analysis | object \| null | JD 技术图谱（无 JD 时为 null） |
| cross_mapping | object \| null | 交叉映射结果 |
| probing_plan | object \| null | 追问计划 |
| prefix_knowledge | object[] \| null | 前缀知识列表 |
| md_report | string | 生成的 Markdown 报告 |
| status | int | 会话状态（3=READY 表示成功） |
| config | object | 用户配置 |

**structured_resume 结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| personal_info | object | 个人信息（name, phone, email, location, summary 等） |
| work_experience | object[] | 工作经历列表（重点） |
| project_experience | object[] | 项目经历列表（重点） |
| education | object[] | 教育经历列表 |
| skills | object | 技能数据（含 skill_groups 分组） |
| publications | object | 论文/专利/技术写作（papers, patents, technical_writings） |
| metadata | object | 解析元数据（项目数、论文数、总工作年限等） |
| validation_warnings | object[] | 校验警告（如缺失量化数据） |

**work_experience 子结构（重点）**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| company | string | 公司名称 |
| position | string | 职位 |
| department | string | 部门 |
| start_date | string | 开始日期（YYYY.MM） |
| end_date | string | 结束日期（YYYY.MM 或 "至今"） |
| duration_months | int | 工作月数 |
| is_current | bool | 是否在职 |
| team_context | string | 团队规模和职责 |
| responsibilities | string[] | 工作职责列表 |
| achievements | object[] | 成果列表（含 description, metric, impact） |
| tech_stack | string[] | 使用的技术栈 |
| key_projects | object[] | 关联的项目概要 |
| promotion_history | object[] | 晋升记录 |

**project_experience 子结构（重点）**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| name | string | 项目名称 |
| source | string | 来源：work/personal/education/open_source |
| role | string | 担任角色 |
| background | string | 项目背景 |
| tech_stack | object | 分层技术栈（languages, frameworks, middleware, infrastructure, tools） |
| architecture | string | 架构描述 |
| challenges | object[] | 挑战列表（challenge + solution + result） |
| achievements | object[] | 成果列表（含量化指标） |
| highlights | string[] | 可追问亮点 |
| probing_directions | string[] | 建议追问方向 |

**skills 子结构（重点）**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| skill_groups | object[] | 技能分组列表 |
| skill_groups[].category | string | 分类（programming_languages/frameworks/middleware/...） |
| skill_groups[].label | string | 显示名称 |
| skill_groups[].items | object[] | 技能项列表（name, proficiency, years, source_projects） |
| certifications | object[] | 证书列表 |
| languages | object[] | 语言能力列表 |

**publications 子结构（论文/专利）**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| papers | object[] | 论文列表（title, authors, venue, venue_level, keywords, my_contribution 等） |
| patents | object[] | 专利列表（title, patent_type, status, inventors 等） |
| technical_writings | object[] | 技术写作列表 |

**probing_plan 子结构**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| knowledge_points | object[] | 知识点列表（按权重降序） |
| knowledge_points[].id | string | 知识点 ID |
| knowledge_points[].name | string | 知识点名称 |
| knowledge_points[].category | string | 类型（tech/project/paper/patent/skill） |
| knowledge_points[].module | string | 所属模块（project_experience/papers/patents/skills） |
| knowledge_points[].jd_relevance | float | JD 关联度（0-1） |
| knowledge_points[].probing_weight | float | 最终追问权重（0-1，归一化） |
| knowledge_points[].allocated_rounds | int | 分配的追问轮数 |
| knowledge_points[].probing_chain | string[] | 预设问题链 |
| project_priorities | object[] | 项目优先级列表 |
| total_rounds | int | 总追问轮数 |
| rounds_distribution | object | 各类型分配轮数 |
| has_jd | bool | 是否有 JD |

**响应示例**：

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
      "summary": "5年后端开发经验，专注于高并发分布式系统"
    },
    "work_experience": [
      {
        "company": "字节跳动",
        "position": "高级后端工程师",
        "start_date": "2021.06",
        "end_date": "至今",
        "duration_months": 47,
        "is_current": true,
        "achievements": [
          {
            "description": "设计分布式缓存方案，推荐接口 P99 延迟从 200ms 降至 50ms",
            "metric": "P99 延迟降低 75%",
            "impact": "high"
          }
        ],
        "tech_stack": ["Go", "Kafka", "Redis", "Kubernetes"]
      }
    ],
    "project_experience": [
      {
        "name": "推荐系统实时特征平台",
        "source": "work",
        "role": "技术负责人",
        "tech_stack": {
          "languages": ["Go", "Python"],
          "frameworks": ["gRPC", "Flink"],
          "middleware": ["Kafka", "Redis Cluster", "ClickHouse"],
          "infrastructure": ["Kubernetes"],
          "tools": ["Prometheus", "Grafana"]
        },
        "challenges": [
          {
            "challenge": "单日特征写入量峰值达 50 亿条，Redis 写入成为瓶颈",
            "solution": "设计两级缓存架构",
            "result": "写入吞吐量提升 3 倍"
          }
        ],
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
            { "name": "Go", "proficiency": "expert", "years": 5 },
            { "name": "Python", "proficiency": "expert", "years": 6 }
          ]
        }
      ]
    },
    "publications": {
      "papers": [],
      "patents": [],
      "technical_writings": []
    },
    "metadata": {
      "source_file": "张三_简历.pdf",
      "total_experience_months": 47,
      "companies_count": 1,
      "projects_count": 1,
      "papers_count": 0,
      "patents_count": 0
    },
    "validation_warnings": []
  },
  "jd_text": "岗位职责：1. 负责公司核心服务的后端开发...",
  "jd_analysis": {
    "position_title": "高级后端工程师",
    "required_skills": [
      { "name": "Go", "category": "language", "importance": "required", "level": "精通" },
      { "name": "Kafka", "category": "middleware", "importance": "required", "level": "熟练" }
    ]
  },
  "cross_mapping": {
    "knowledge_points": [
      {
        "id": "tech_1",
        "name": "Go",
        "category": "tech",
        "jd_relevance": 1.0,
        "probing_weight": 0.85,
        "allocated_rounds": 3
      }
    ]
  },
  "probing_plan": {
    "knowledge_points": [],
    "total_rounds": 30,
    "has_jd": true
  },
  "prefix_knowledge": [
    {
      "tech_name": "Redis",
      "core_concepts": ["数据结构", "持久化", "高可用"],
      "key_questions": ["Redis 有哪些数据结构？"],
      "quick_reference": "Redis 是内存 KV 存储，支持多种数据结构..."
    }
  ],
  "md_report": "# 面试准备报告\n\n**候选人**: 张三\n...",
  "status": 3,
  "config": {
    "total_rounds": 30,
    "breadth_mode": "balanced"
  }
}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| PARSE_ERROR | 500 | 简历解析失败（文件格式不支持、内容为空、LLM 调用失败） |
| VALIDATION_ERROR | 422 | 缺少 file 参数 |

**注意**：

> - 此接口执行完整 Pipeline（约 9-10 次 LLM 调用），耗时 10-30 秒
> - 无 JD 时 `jd_text` 留空或不传，系统会按纯简历模式分析
> - 上传后 `status=3`（READY）表示解析成功，可以直接查看报告或开始追问

---

### 2.2 获取简历会话列表

获取当前用户的简历解析历史列表。

`GET` `/api/v1/apps/resume/sessions`

**查询参数**：

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `20` | 每页数量（1-100） |
| offset | int | 否 | `0` | 偏移量 |

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sessions | object[] | 会话列表（同 2.1 响应格式，但 structured_resume 等大字段可能为 null） |
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
      "status": 3,
      "md_report": "",
      "config": {}
    }
  ],
  "total": 1
}
```

---

### 2.3 获取简历会话详情

获取指定简历会话的完整数据（含结构化简历、分析报告、追问计划等）。

`GET` `/api/v1/apps/resume/sessions/{session_id}`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应参数**：同 2.1 的完整响应格式。

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

## 三、追问对话

### 3.1 创建追问会话

为指定的简历会话创建追问对话会话。如果已有活跃的追问会话，则返回已有的。

`POST` `/api/v1/apps/resume/sessions/{session_id}/probing`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID（需为 READY 状态） |

**请求参数**：无

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | string | 追问会话 UUID |
| resume_session_id | string | 关联的简历会话 ID |
| status | int | 追问状态（1=PROBING） |
| current_module | string | 当前追问模块 |
| current_item_index | int | 当前模块内子项索引 |
| current_round | int | 当前子项追问轮次 |
| completed_kps | string[] | 已完成的知识点 ID 列表 |
| total_rounds_done | int | 已完成的追问轮数 |
| summary_report | string | 总结报告（追问完成后生成） |

**响应示例**：

```json
{
  "id": "f1e2d3c4-b5a6-7890-abcd-ef1234567890",
  "resume_session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": 1,
  "current_module": "project_experience",
  "current_item_index": 0,
  "current_round": 0,
  "completed_kps": [],
  "total_rounds_done": 0,
  "summary_report": ""
}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 简历会话不存在或状态不正确 |

---

### 3.2 追问对话（SSE 流式）

与面试官 AI 进行流式追问对话。返回 Server-Sent Events 流。

`POST` `/api/v1/apps/resume/sessions/{session_id}/chat`

**Content-Type**：`application/json`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**请求参数（Body）**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| content | string | 是 | 用户输入的回答内容（min_length=1） |

**请求示例**：

```json
{
  "content": "我主要负责实时特征计算引擎的开发，以及 Redis Cluster 的分片策略设计"
}
```

**响应格式**：`text/event-stream`（SSE）

SSE 事件类型：

| 事件类型 | 数据格式 | 说明 |
|---------|---------|------|
| `session` | `{ "probing_session_id": "uuid" }` | 追问会话信息 |
| `content` | `{ "content": "文本片段" }` | AI 回复的流式文本片段 |
| `done` | `{ "total_rounds_done": 5, "status": 1 }` | 本轮对话结束 |
| `error` | `{ "content": "错误信息" }` | 发生错误 |

**SSE 响应示例**：

```
event: session
data: {"probing_session_id": "f1e2d3c4-b5a6-7890-abcd-ef1234567890"}

event: content
data: {"content": "你说到负责 Redis Cluster 的分片策略设计，"}

event: content
data: {"content": "能具体说说你们是怎么决定分片策略的吗？"}

event: done
data: {"total_rounds_done": 5, "status": 1}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| PROBING_NOT_FOUND | 404 | 追问会话不存在 |

**注意**：

> - 追问按模块顺序执行：项目经历 → 工作经历 → 论文 → 专利 → 技能
> - AI 会根据回答质量自适应调整追问深度
> - 每轮回答完成后 `total_rounds_done` 递增
> - 达到 `total_rounds` 后状态变为 SUMMARY，自动生成总结报告

---

### 3.3 获取追问进度

获取当前追问的实时进度信息。

`GET` `/api/v1/apps/resume/sessions/{session_id}/probing/status`

**路径参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 简历会话 UUID |

**响应参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| session | object | 追问会话信息（同 3.1 格式） |
| progress_percent | float | 进度百分比（0-100） |
| current_question | string | 当前正在追问的问题 |
| completed_modules | string[] | 已完成的模块列表 |
| remaining_modules | string[] | 剩余待追问的模块列表 |

**响应示例**：

```json
{
  "session": {
    "id": "f1e2d3c4-b5a6-7890-abcd-ef1234567890",
    "resume_session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "status": 1,
    "current_module": "project_experience",
    "current_item_index": 2,
    "current_round": 1,
    "completed_kps": ["tech_1", "proj_5"],
    "total_rounds_done": 8,
    "summary_report": ""
  },
  "progress_percent": 26.7,
  "current_question": "Redis Cluster 分片策略怎么设计的？热点 key 怎么处理？",
  "completed_modules": ["project_experience"],
  "remaining_modules": ["papers", "skills"]
}
```

**错误码**：

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 简历会话不存在 |
| PROBING_NOT_FOUND | 404 | 追问会话未创建 |

---

## 四、完整调用流程

### 有 JD 的完整流程

```
1. POST /api/v1/apps/resume/upload
   file=简历.pdf, jd_text=岗位JD, config={"total_rounds": 30}
   → 返回 structured_resume + probing_plan + md_report + status=3

2. （前端展示 MD 报告和结构化简历）

3. POST /api/v1/apps/resume/sessions/{id}/probing
   → 返回追问会话 status=1

4. POST /api/v1/apps/resume/sessions/{id}/chat  (SSE, 多轮)
   content=用户回答
   → 流式返回 AI 追问
   → 重复直到 progress_percent=100

5. GET /api/v1/apps/resume/sessions/{id}/probing/status
   → 获取最终进度和总结报告
```

### 无 JD 的流程

与上述相同，但上传时 `jd_text` 留空。系统会按纯简历内容挖掘，追问侧重项目架构决策和技术深度验证。

---

## 五、Pipeline 技术说明

### LLM 调用次数

| 阶段 | 步骤 | LLM 调用次数 |
|------|------|-------------|
| 解析 | S1 文本提取 | 0（工具处理） |
| 解析 | S2 章节切割 | 1 |
| 解析 | S3 并行解析 | 6（并行） |
| 分析 | S5 JD 图谱 | 0-1（有 JD 时） |
| 分析 | S7 追问策略 | 1 |
| 分析 | S8 前缀知识 | 1 |
| 追问 | S10 每轮对话 | N |
| **总计** | | **9-10 + N** |

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
