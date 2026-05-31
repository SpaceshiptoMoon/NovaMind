# 简历挖掘模块 API 文档

## 概述

简历挖掘模块提供简历上传、自动解析、结构化分析、LLM 自问自答追问和面试准备建议报告生成的完整流程。上传简历后系统自动在后台完成所有处理（解析 → 分析 → 追问 → 建议），用户可在历史记录中查看进度和结果。

路由前缀：`/api/v1/apps`

- **认证方式**：所有接口均需 JWT 认证，请求头携带 `Authorization: Bearer <token>`
- **处理模式**：上传后异步后台执行全流程，用户无感知，在历史记录页查看进度
- **文件存储**：原始简历和最终报告均存储在 MinIO，数据库只保存地址

### 通用 Header

| Header | 值 | 必填 | 说明 |
|--------|------|------|------|
| Authorization | `Bearer <token>` | 是 | JWT 访问令牌 |

### 通用错误响应

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-05-11T10:00:00+08:00"
}
```

---

## 枚举值定义

### 会话状态（status）

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | DRAFT | 初始/失败状态 |
| 1 | PARSING | 正在解析简历（S1-S4） |
| 2 | ANALYZING | 正在生成分析报告（S5-S9） |
| 4 | PROBING | 正在自动追问（S10-S11） |
| 5 | COMPLETED | 全部完成，可查看/下载报告 |

---

## 一、简历挖掘

### 1.1 上传简历

上传简历文件，系统自动在后台执行完整的解析、分析、追问和建议生成流程。接口立即返回会话信息（status=1），用户在历史记录页查看进度。

**请求**
- 方法：`POST`
- URL：`/api/v1/apps/resume/upload`
- Content-Type：`multipart/form-data`

**请求参数（FormData）**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| file | File | 是 | - | 简历文件（PDF/DOCX/TXT/MD） |
| jd_text | string | 否 | `""` | 岗位 JD 描述文本 |
| config | string | 否 | `"{}"` | 追问配置 JSON 字符串 |
| llm_model | string | 否 | `""` | LLM 模型名称，空则用用户默认 |

**config 参数结构**

```json
{
  "breadth": 3,
  "depth": 3
}
```

| 字段 | 类型 | 范围 | 默认值 | 说明 |
|------|------|------|--------|------|
| breadth | int | 1-5 | 3 | 追问广度：每个知识点的衍生子话题数 |
| depth | int | 1-5 | 3 | 追问深度：每个知识点的连续追问轮数 |

**响应参数**

返回 `ResumeSessionResponse`，同 1.3 响应参数。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| PARSE_ERROR | 400 | 未配置 LLM 模型 |
| VALIDATION_ERROR | 422 | 请求参数验证失败 |

---

### 1.2 获取会话列表

获取当前用户的简历解析会话列表，支持按状态筛选。

**请求**
- 方法：`GET`
- URL：`/api/v1/apps/resume/sessions`

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
|--------|------|------|--------|------|
| limit | int | 否 | `20` | 返回数量（1-100） |
| offset | int | 否 | `0` | 偏移量（>=0） |
| status | int | 否 | `null` | 按状态筛选（0/1/2/4/5），不传则返回全部 |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| sessions | array | 会话列表（结构同 1.3） |
| total | int | 符合条件的总数 |

---

### 1.3 获取会话详情

获取指定简历会话的元数据和结构化简历。报告内容需通过 1.4 单独获取。

**请求**
- 方法：`GET`
- URL：`/api/v1/apps/resume/sessions/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应参数（ResumeSessionResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | string | 会话 UUID |
| user_id | int | 用户 ID |
| resume_filename | string | 原始文件名 |
| structured_resume | object \| null | 结构化简历数据 |
| jd_text | string | JD 文本 |
| md_report_url | string \| null | MD 报告 MinIO 文件地址 |
| status | int | 会话状态（见枚举定义） |
| config | object | 用户配置 |
| created_at | string \| null | 创建时间（ISO 8601） |
| updated_at | string \| null | 更新时间（ISO 8601） |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

### 1.4 获取报告内容

从 MinIO 读取指定会话的 MD 报告文本内容，用于前端渲染。

**请求**
- 方法：`GET`
- URL：`/api/v1/apps/resume/sessions/{session_id}/report`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应**

- Content-Type：`text/markdown`
- Body：MD 报告纯文本

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| PARSE_ERROR | 400 | 报告尚未生成 / 报告读取失败 |

---

### 1.5 下载报告

下载最终 MD 报告文件（带 Content-Disposition 触发浏览器下载）。

**请求**
- 方法：`GET`
- URL：`/api/v1/apps/resume/sessions/{session_id}/download`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应**

- Content-Type：`text/markdown`
- Content-Disposition：`attachment; filename*=UTF-8''<URL编码文件名>_report.md`

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| PARSE_ERROR | 400 | 报告尚未生成 / 报告读取失败 |

---

### 1.6 删除会话

删除指定会话及其 MinIO 中的原始文件和报告文件。删除后不可恢复。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/apps/resume/sessions/{session_id}`

**路径参数**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| session_id | string | 是 | 会话 UUID |

**响应**

```json
{
  "message": "删除成功"
}
```

**删除范围**

| 删除对象 | 说明 |
|---------|------|
| 数据库记录 | resume_sessions 表中对应记录 |
| MinIO 原始文件 | `resume/{session_id}/{filename}` |
| MinIO 报告文件 | `resume/{session_id}/report.md` |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |

---

## 二、LLM 模型查询

### 2.1 获取可用模型列表

获取当前可用的 LLM 模型列表，用于上传简历时选择模型。

**请求**
- 方法：`GET`
- URL：`/api/v1/ai-chat/models`

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| models | object | 模型字典，key 为模型名称 |
| models.`<name>`.max_tokens | int | 最大 token 数 |
| models.`<name>`.temperature | float | 默认温度 |
| models.`<name>`.top_p | float | 默认 top_p |

---

## 后台处理流程

上传后系统自动在后台执行以下流程：

```
上传简历 → [后台异步]
  存原始文件到 MinIO: resume/{session_id}/{filename}
  S1-S4: 文本提取 → 章节切割 → 并行深度解析 → 交叉校验    (status=1 PARSING)
  S5-S9: JD分析 → 交叉映射 → 追问策略 → 前缀知识           (status=2 ANALYZING)
  S10:   三层追问（项目深挖→技术追问→基础扎实度）           (status=4 PROBING)
  S11:   LLM 生成面试准备建议（闭环测评）                   (status=4 PROBING)
  S12:   组装最终报告 → 上传 MinIO: resume/{session_id}/report.md (status=5 COMPLETED)
```

### 追问策略三层优先级

| 层级 | 类别 | 权重 | 追问模式 |
|------|------|------|----------|
| Tier 1 | project（项目深挖） | ×1.5 | 架构选型→问题挑战→方案方法→指标验证→反思改进 |
| Tier 2 | tech_in_project（项目中的技术） | 标准 | 用XX做了什么→为什么选它→踩坑→量级扩展 |
| Tier 3 | fundamental（基础扎实度） | 标准 | 核心原理→使用场景→对比优劣势→生产注意事项 |

### 前端交互建议

```
1. 上传成功后跳转历史记录页，提示"已提交解析，后台处理中"
2. 历史记录页支持按状态筛选（解析中/分析中/追问中/已完成/失败）
3. 点击已完成记录可查看报告（三栏布局：候选人信息 + 报告主体 + TOC 目录）
4. 点击失败记录提示重试
5. 支持删除记录（二次确认）
```

### MinIO 存储结构

```
resume/{session_id}/
├── {原始文件名}.pdf     ← 用户上传的原始简历
└── report.md           ← 最终生成的面试追问报告
```

### report.md 内容结构

```markdown
# 面试深度追问报告
**候选人**: 张三
**目标岗位**: 高级Go开发工程师 @ 某公司（有JD时）
**追问知识点**: 15 个，共 45 轮 Q&A

---

## 一、岗位匹配概览（有JD时）/ 简历概览（无JD时）

---

## 二、面试前缀知识
（每个相关技术的快速参考卡片）
### Redis
- **核心概念**: ...
- **常见考点**: 每个考点附带简明答案
- **经典问题**: 每个问题附带参考答案
- **常见踩坑**: ...

---

## 三、追问详情
（按三层优先级排列，项目深挖优先）
### 模块: 项目经历
  #### 项目: 订单服务系统
    **Q1:** 你在订单系统中用了什么架构？为什么这么选？
    **A:** 我们采用微服务架构...
    深度评分: 0.7

---

## 四、面试准备建议（闭环测评）
### 项目经验准备
### 技术深度补充
### 基础知识巩固
### 高频考点预测 Top 5
### 表达建议
```

---

## 数据库表结构

`resume_sessions` 表（仅 1 张表）：

| 列名 | 类型 | 说明 |
|------|------|------|
| id | varchar(36) PK | 会话 UUID |
| user_id | bigint FK | 用户 ID |
| resume_file_url | varchar(500) | MinIO 原始文件地址 |
| resume_filename | varchar(200) | 原始文件名 |
| structured_resume | json | 结构化简历数据 |
| jd_text | text | 岗位 JD 文本 |
| md_report_url | varchar(500) | MinIO 报告文件地址 |
| status | int | 会话状态（0-5） |
| config | json | 用户配置 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

---

## 错误码汇总

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SESSION_NOT_FOUND | 404 | 会话不存在或无权访问 |
| PARSE_ERROR | 400 | 简历解析失败 / 未配置 LLM 模型 / 报告未生成 |
| VALIDATION_ERROR | 422 | 请求参数验证失败 |
| INTERNAL_ERROR | 500 | 服务器内部错误 |
