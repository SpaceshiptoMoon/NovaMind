# 技能广场模块 API 文档

## 概述

技能广场模块提供基于 [Anthropic SKILL.md 开放标准](https://docs.anthropic.com/en/docs/agents-and-tools/claude-code/skills) 的技能管理能力。用户可上传包含 `SKILL.md` 的 ZIP 包创建自定义技能，经过安全审查（规则引擎 + 可选 LLM 审查）后发布到广场，其他用户可将技能安装到自己的 Agent 中使用。

模块包含四个子模块：

| 子模块 | 路由前缀 | 说明 |
|-------|---------|------|
| 上传与版本管理 | `/api/v1/skills/upload` 等 | 技能 ZIP 包上传、版本更新 |
| 查询与搜索 | `/api/v1/skills/marketplace` 等 | 广场浏览、我的技能、技能详情、下载 |
| 发布与安装 | `/api/v1/skills/{skill_id}/publish` 等 | 发布/取消发布、安装到 Agent、评价 |
| 管理员管理 | `/api/v1/skills/admin/*` | 审查设置、待审核列表 |

### 认证方式

所有接口均需要 JWT 认证，在请求头中携带：

```
Authorization: Bearer <token>
```

**使用前提**：
1. 需要先通过 `POST /api/v1/user/users/login` 登录获取 JWT Token
2. 用户只能操作自己上传的技能
3. 管理员接口需要 `is_admin=true` 的用户角色

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

### 技能来源（skill_source）

| 值 | 说明 |
|----|------|
| `builtin` | 系统内置技能 |
| `custom` | 用户自定义技能 |

### 技能可见性（visibility）

| 值 | 说明 |
|----|------|
| `0` | 私有（PRIVATE） |
| `1` | 团队可见（TEAM） |
| `2` | 公开（PUBLIC） |

### 技能状态（status）

| 值 | 说明 |
|----|------|
| `0` | 草稿（DRAFT） |
| `1` | 已发布（PUBLISHED） |
| `2` | 已归档（ARCHIVED） |

### 安全审查状态（review_status）

| 值 | 说明 |
|----|------|
| `0` | 待审查（PENDING） |
| `1` | 已通过（APPROVED） |
| `2` | 可疑，需人工审核（SUSPICIOUS） |
| `3` | 已拒绝（REJECTED） |

### ZIP 包结构要求

上传的 ZIP 包必须包含根目录下的 `SKILL.md` 文件，格式遵循 Anthropic SKILL.md 开放标准：

```
skill.zip
├── SKILL.md          # 必须存在，包含 YAML frontmatter + Markdown 指令正文
├── references/       # 可选，引用文件
├── scripts/          # 可选，脚本文件
└── assets/           # 可选，资源文件
```

**SKILL.md 格式示例**：

```markdown
---
name: my-custom-skill
display_name: 我的自定义技能
description: 一个用于演示的自定义技能
category: productivity
tags:
  - demo
  - automation
license: MIT
allowed_tools:
  - knowledge_search
  - web_search
---

# 技能指令

请在回答用户问题时遵循以下规则...

## 使用场景

- 场景一：...
- 场景二：...
```

**frontmatter 字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| name | string | 是 | 技能标识，kebab-case 格式（如 `my-custom-skill`） |
| display_name | string | 是 | 显示名称 |
| description | string | 是 | 技能描述 |
| category | string | 否 | 分类 |
| tags | string[] | 否 | 标签列表 |
| license | string | 否 | 许可证标识 |
| allowed_tools | string[] | 否 | 该技能需要使用的工具名列表 |

---

## 一、上传与版本管理

### 1.1 上传技能

上传包含 SKILL.md 的 ZIP 包创建新技能。上传后自动执行安全审查（规则引擎 + 可选 LLM 审查），审查结果记录到 `review_status` 字段。同一用户下技能名称不可重复。

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/upload`
- Content-Type：`multipart/form-data`
- 认证：需要 JWT 登录

**请求参数（Form Data）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file | file | 是 | 技能 ZIP 包（必须以 `.zip` 结尾，内含 SKILL.md） |

**请求示例（cURL）**

```bash
curl -X POST "http://localhost:8100/api/v1/skills/upload" \
  -H "Authorization: Bearer <token>" \
  -F "file=@my-skill.zip"
```

**响应参数（SkillResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 技能 ID |
| user_id | int \| null | 所属用户 ID |
| name | string | 技能标识 |
| display_name | string | 显示名称 |
| description | string | 技能描述 |
| license | string \| null | 许可证 |
| allowed_tools | string[] \| null | 允许的工具列表 |
| frontmatter_raw | string \| null | YAML frontmatter 原文 |
| body_markdown | string | Markdown 指令正文 |
| category | string \| null | 分类 |
| tags | string[] \| null | 标签列表 |
| icon | string \| null | 图标 |
| version | int | 当前版本号（首次上传为 1） |
| version_note | string \| null | 版本说明 |
| skill_source | string | 来源（`custom`） |
| visibility | int | 可见性（初始为 `0` 私有） |
| status | int | 状态（初始为 `0` 草稿） |
| install_count | int | 安装次数（初始为 0） |
| rating_avg | float | 平均评分（初始为 0.0） |
| rating_count | int | 评价数量（初始为 0） |
| review_status | int | 审查状态（`0`=PENDING / `1`=APPROVED / `2`=SUSPICIOUS / `3`=REJECTED） |
| review_result | object \| null | 审查结果详情 |
| review_result.rules | object | 规则引擎检查结果 |
| review_result.rules.passed | bool | 规则检查是否通过 |
| review_result.rules.matches | array | 匹配到的规则列表 |
| review_result.llm | object | LLM 审查结果（启用时） |
| review_result.llm.level | string \| null | LLM 审查级别 |
| review_result.llm.reason | string \| null | LLM 审查原因 |
| reviewed_at | datetime \| null | 审查时间 |
| created_at | datetime \| null | 创建时间 |
| updated_at | datetime \| null | 更新时间 |

**响应示例**

```json
{
  "id": 1,
  "user_id": 1,
  "name": "my-custom-skill",
  "display_name": "我的自定义技能",
  "description": "一个用于演示的自定义技能",
  "license": "MIT",
  "allowed_tools": ["knowledge_search", "web_search"],
  "frontmatter_raw": "name: my-custom-skill\ndisplay_name: 我的自定义技能\n...",
  "body_markdown": "# 技能指令\n\n请在回答用户问题时遵循以下规则...",
  "category": "productivity",
  "tags": ["demo", "automation"],
  "icon": null,
  "version": 1,
  "version_note": null,
  "skill_source": "custom",
  "visibility": 0,
  "status": 0,
  "install_count": 0,
  "rating_avg": 0.0,
  "rating_count": 0,
  "review_status": 1,
  "review_result": {
    "rules": {
      "passed": true,
      "matches": []
    },
    "llm": {
      "level": null,
      "reason": null
    }
  },
  "reviewed_at": "2026-05-09T10:00:00",
  "created_at": "2026-05-09T10:00:00",
  "updated_at": "2026-05-09T10:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| INVALID_SKILL_FORMAT | 400 | ZIP 包格式无效（缺少 SKILL.md、frontmatter 缺少必填字段等） |
| SKILL_ALREADY_EXISTS | 409 | 同一用户下已存在同名技能 |
| VALIDATION_ERROR | 422 | 文件格式不是 .zip |

---

### 1.2 更新技能（上传新版本）

为已有技能上传新版本 ZIP 包。版本号自动递增，已发布的技能更新后会变回草稿状态，需重新发布。

**请求**
- 方法：`PUT`
- URL：`/api/v1/skills/{skill_id}/upload`
- Content-Type：`multipart/form-data`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**请求参数（Form Data）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| file | file | 是 | 新版技能 ZIP 包 |

**响应参数**

同 1.1 响应参数（SkillResponse，返回更新后的完整技能信息，`version` 自动 +1）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_ACCESS_DENIED | 403 | 无权操作（非技能所有者） |
| INVALID_SKILL_FORMAT | 400 | ZIP 包格式无效 |
| VALIDATION_ERROR | 422 | 文件格式不是 .zip |

---

## 二、查询与搜索

### 2.1 我的技能列表

获取当前用户上传的技能列表，支持按状态过滤。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/mine`
- 认证：需要 JWT 登录

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| status | int | 否 | 无 | - | 按状态过滤（`0`=草稿 / `1`=已发布 / `2`=已归档） |
| limit | int | 否 | `20` | 1-100 | 返回数量 |
| offset | int | 否 | `0` | >= 0 | 偏移量 |

**响应参数（SkillMarketplaceListResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 技能列表（轻量，不含 body_markdown） |
| items[].id | int | 技能 ID |
| items[].name | string | 技能标识 |
| items[].display_name | string | 显示名称 |
| items[].description | string | 描述 |
| items[].category | string \| null | 分类 |
| items[].tags | string[] \| null | 标签 |
| items[].icon | string \| null | 图标 |
| items[].version | int | 当前版本号 |
| items[].skill_source | string | 来源 |
| items[].install_count | int | 安装次数 |
| items[].rating_avg | float | 平均评分 |
| items[].rating_count | int | 评价数量 |
| items[].author_name | string \| null | 作者名称 |
| items[].created_at | datetime \| null | 创建时间 |
| items[].updated_at | datetime \| null | 更新时间 |
| total | int | 总数 |
| limit | int | 每页数量 |
| offset | int | 偏移量 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "name": "my-custom-skill",
      "display_name": "我的自定义技能",
      "description": "一个用于演示的自定义技能",
      "category": "productivity",
      "tags": ["demo", "automation"],
      "icon": null,
      "version": 1,
      "skill_source": "custom",
      "install_count": 3,
      "rating_avg": 4.5,
      "rating_count": 2,
      "author_name": null,
      "created_at": "2026-05-09T10:00:00",
      "updated_at": "2026-05-09T10:00:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 2.2 广场浏览

浏览公开的技能广场，支持关键词搜索、分类过滤、标签过滤和多种排序方式。仅返回已发布且审查通过的技能。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/marketplace`
- 认证：无需登录

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| keyword | string | 否 | 无 | 最大 200 字符 | 搜索关键词（匹配名称、显示名称、描述） |
| category | string | 否 | 无 | 最大 50 字符 | 分类过滤 |
| tags | string | 否 | 无 | - | 逗号分隔标签（如 `demo,automation`） |
| sort | string | 否 | `newest` | 枚举：`popular` / `rating` / `newest` / `name` | 排序方式 |
| limit | int | 否 | `20` | 1-100 | 返回数量 |
| offset | int | 否 | `0` | >= 0 | 偏移量 |

**响应参数**

同 2.1 响应参数结构（SkillMarketplaceListResponse，`items` 中每项为轻量级技能信息）。

**响应示例**

```json
{
  "items": [
    {
      "id": 5,
      "name": "rag-optimizer",
      "display_name": "RAG 优化助手",
      "description": "优化 RAG 检索策略和结果质量",
      "category": "ai",
      "tags": ["rag", "optimization"],
      "icon": null,
      "version": 2,
      "skill_source": "custom",
      "install_count": 42,
      "rating_avg": 4.8,
      "rating_count": 15,
      "author_name": null,
      "created_at": "2026-05-01T08:00:00",
      "updated_at": "2026-05-08T14:30:00"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 2.3 技能详情

获取指定技能的完整详情，包含 frontmatter 原文和 Markdown 指令正文。接口接收当前用户 ID 用于可见性检查。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/{skill_id}`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应参数（SkillResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 技能 ID |
| user_id | int \| null | 所属用户 ID |
| name | string | 技能标识 |
| display_name | string | 显示名称 |
| description | string | 描述 |
| license | string \| null | 许可证 |
| allowed_tools | string[] \| null | 允许的工具列表 |
| frontmatter_raw | string \| null | YAML frontmatter 原文 |
| body_markdown | string | Markdown 指令正文 |
| category | string \| null | 分类 |
| tags | string[] \| null | 标签 |
| icon | string \| null | 图标 |
| version | int | 当前版本号 |
| version_note | string \| null | 版本说明 |
| skill_source | string | 来源 |
| visibility | int | 可见性 |
| status | int | 状态 |
| install_count | int | 安装次数 |
| rating_avg | float | 平均评分 |
| rating_count | int | 评价数量 |
| review_status | int | 审查状态 |
| review_result | object \| null | 审查结果详情 |
| reviewed_at | datetime \| null | 审查时间 |
| created_at | datetime \| null | 创建时间 |
| updated_at | datetime \| null | 更新时间 |

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |

---

### 2.4 下载技能

下载指定技能的 ZIP 包。ZIP 包内包含 SKILL.md 和所有资源文件。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/{skill_id}/download`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应**

- Content-Type：`application/zip`
- Content-Disposition：`attachment; filename=skill_{skill_id}.zip`
- Body：ZIP 包二进制数据

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |

---

### 2.5 删除技能

删除指定技能。只有技能所有者可以删除。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/skills/{skill_id}`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应参数（SkillActionResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | bool | 操作是否成功 |
| message | string | 操作结果描述 |

**响应示例**

```json
{
  "success": true,
  "message": "技能已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_ACCESS_DENIED | 403 | 无权操作（非技能所有者） |

---

### 2.6 Agent 已安装技能

获取指定 Agent 已安装的技能列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/installed/{agent_id}`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| agent_id | int | 是 | > 0 | Agent ID |

**响应参数**

返回安装记录数组（`SkillInstallationResponse[]`）：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| [].id | int | 安装记录 ID |
| [].skill_id | int | 技能 ID |
| [].agent_id | int | Agent ID |
| [].created_at | datetime \| null | 安装时间 |

**响应示例**

```json
[
  {
    "id": 1,
    "skill_id": 5,
    "agent_id": 3,
    "created_at": "2026-05-09T10:00:00"
  },
  {
    "id": 2,
    "skill_id": 8,
    "agent_id": 3,
    "created_at": "2026-05-09T11:00:00"
  }
]
```

---

## 三、发布与安装

### 3.1 发布技能

将草稿状态的技能发布到广场。发布后技能变为公开可见。

**前置条件**：
- 技能必须处于草稿（`status=0`）状态
- 审查状态不能为 REJECTED（`review_status=3`）或 SUSPICIOUS（`review_status=2`）

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/{skill_id}/publish`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应参数**

同 2.3 技能详情（SkillResponse，返回更新后的完整信息，`status` 变为 `1`，`visibility` 变为 `2`）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_ACCESS_DENIED | 403 | 无权操作（非技能所有者） |
| SKILL_REVIEW_REJECTED | 400 | 安全审查未通过或待人工审核 |

---

### 3.2 取消发布

将已发布的技能取消发布，变回草稿状态。

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/{skill_id}/unpublish`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应参数**

同 2.3 技能详情（SkillResponse，`status` 变为 `0`，`visibility` 变为 `0`）。

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_ACCESS_DENIED | 403 | 无权操作 |

---

### 3.3 安装技能到 Agent

将指定技能安装到 Agent。安装后会自动将技能引用（`skill__{id}_{name}`）和技能声明的工具追加到 Agent 的 `enabled_tools` 中。

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/{skill_id}/install`
- Content-Type：`application/json`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**请求参数（Body — SkillInstallRequest）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| agent_id | int | 是 | 目标 Agent ID |

**请求示例**

```json
{
  "agent_id": 3
}
```

**响应参数（SkillInstallationResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 安装记录 ID |
| skill_id | int | 技能 ID |
| agent_id | int | Agent ID |
| created_at | datetime \| null | 安装时间 |

**响应示例**

```json
{
  "id": 1,
  "skill_id": 5,
  "agent_id": 3,
  "created_at": "2026-05-09T10:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_NOT_PUBLISHED | 400 | 技能未发布，无法安装 |
| SKILL_ALREADY_INSTALLED | 409 | 技能已安装到该 Agent |

---

### 3.4 卸载技能

从 Agent 卸载指定技能。会自动从 Agent 的 `enabled_tools` 中移除技能引用。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/skills/{skill_id}/install/{agent_id}`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |
| agent_id | int | 是 | > 0 | Agent ID |

**响应参数（SkillActionResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | bool | 操作是否成功 |
| message | string | 操作结果描述 |

**响应示例**

```json
{
  "success": true,
  "message": "技能已卸载"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_INSTALLED | 404 | 技能未安装到该 Agent |

---

## 四、评价系统

### 4.1 创建/更新评价

对指定技能创建或更新评价。每个用户对每个技能只能有一条评价，重复提交会覆盖之前的评分和内容。

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/{skill_id}/reviews`
- Content-Type：`application/json`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**请求参数（Body — SkillReviewCreate）**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| rating | int | 是 | 1-5 | 评分 |
| content | string | 否 | 最大 2000 字符 | 评价内容 |

**请求示例**

```json
{
  "rating": 5,
  "content": "非常好用的技能，大大提升了工作效率！"
}
```

**响应参数（SkillReviewResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | int | 评价 ID |
| skill_id | int | 技能 ID |
| user_id | int | 用户 ID |
| rating | int | 评分 |
| content | string \| null | 评价内容 |
| user_name | string \| null | 用户名称 |
| created_at | datetime \| null | 创建时间 |
| updated_at | datetime \| null | 更新时间 |

**响应示例**

```json
{
  "id": 1,
  "skill_id": 5,
  "user_id": 2,
  "rating": 5,
  "content": "非常好用的技能，大大提升了工作效率！",
  "user_name": null,
  "created_at": "2026-05-09T10:00:00",
  "updated_at": "2026-05-09T10:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |

---

### 4.2 评价列表

获取指定技能的评价列表。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/{skill_id}/reviews`
- 认证：无需登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| limit | int | 否 | `20` | 1-100 | 返回数量 |
| offset | int | 否 | `0` | >= 0 | 偏移量 |

**响应参数（SkillReviewListResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 评价列表（结构同 4.1 SkillReviewResponse） |
| total | int | 评价总数 |

**响应示例**

```json
{
  "items": [
    {
      "id": 1,
      "skill_id": 5,
      "user_id": 2,
      "rating": 5,
      "content": "非常好用的技能！",
      "user_name": null,
      "created_at": "2026-05-09T10:00:00",
      "updated_at": "2026-05-09T10:00:00"
    },
    {
      "id": 2,
      "skill_id": 5,
      "user_id": 3,
      "rating": 4,
      "content": "整体不错，有个别场景可以优化",
      "user_name": null,
      "created_at": "2026-05-09T11:00:00",
      "updated_at": "2026-05-09T11:00:00"
    }
  ],
  "total": 2
}
```

---

### 4.3 删除评价

删除当前用户对指定技能的评价。删除后技能的平均评分会自动更新。

**请求**
- 方法：`DELETE`
- URL：`/api/v1/skills/{skill_id}/reviews`
- 认证：需要 JWT 登录

**路径参数**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| skill_id | int | 是 | > 0 | 技能 ID |

**响应参数（SkillActionResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | bool | 操作是否成功 |
| message | string | 操作结果描述 |

**响应示例**

```json
{
  "success": true,
  "message": "评价已删除"
}
```

---

## 五、验证

### 5.1 验证 SKILL.md 格式

验证 SKILL.md 内容是否符合格式要求，不需要实际上传。用于前端实时校验。

**请求**
- 方法：`POST`
- URL：`/api/v1/skills/validate`
- Content-Type：`application/json`
- 认证：无需登录

**请求参数（Body — SkillValidateRequest）**

| 参数名 | 类型 | 必填 | 约束 | 说明 |
|--------|------|------|------|------|
| content | string | 是 | 最少 1 字符 | 完整 SKILL.md 内容 |

**请求示例**

```json
{
  "content": "---\nname: test-skill\ndisplay_name: 测试技能\ndescription: 测试用\n---\n\n# 指令\n测试内容"
}
```

**响应参数（SkillValidateResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| valid | bool | 格式是否有效 |
| errors | string[] | 错误列表 |
| parsed | object \| null | 解析结果（格式有效时有值） |
| parsed.name | string | 技能标识 |
| parsed.description | string | 技能描述 |

**响应示例（有效）**

```json
{
  "valid": true,
  "errors": [],
  "parsed": {
    "name": "test-skill",
    "description": "测试用"
  }
}
```

**响应示例（无效）**

```json
{
  "valid": false,
  "errors": [
    "frontmatter 缺少必填字段: name",
    "frontmatter 缺少必填字段: description"
  ],
  "parsed": null
}
```

---

## 六、管理员管理

以下接口仅限管理员（`is_admin=true`）调用，普通用户调用将返回 403。

### 6.1 获取审查设置

获取当前 LLM 安全审查的配置信息。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/admin/settings`
- 认证：管理员（`require_admin`）

**响应参数（SkillAdminSettingsResponse）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| llm_review_enabled | bool | 是否启用 LLM 安全审查 |
| llm_review_model | string \| null | 使用的 LLM 模型名称（null 表示系统默认） |

**响应示例**

```json
{
  "llm_review_enabled": false,
  "llm_review_model": null
}
```

---

### 6.2 更新审查设置

更新 LLM 安全审查的全局开关。设置实时生效，通过 Redis 存储，无需重启服务。

**请求**
- 方法：`PUT`
- URL：`/api/v1/skills/admin/settings`
- Content-Type：`application/json`
- 认证：管理员（`require_admin`）

**请求参数（Body — SkillAdminSettingsUpdate）**

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| llm_review_enabled | bool | 是 | 是否启用 LLM 安全审查 |

**请求示例**

```json
{
  "llm_review_enabled": true
}
```

**响应参数**

同 6.1 响应参数（SkillAdminSettingsResponse）。

**响应示例**

```json
{
  "llm_review_enabled": true,
  "llm_review_model": null
}
```

---

### 6.3 待审核技能列表

获取被安全审查标记为 SUSPICIOUS（可疑）的技能列表，供管理员人工审核。

**请求**
- 方法：`GET`
- URL：`/api/v1/skills/admin/reviews`
- 认证：管理员（`require_admin`）

**查询参数**

| 参数名 | 类型 | 必填 | 默认值 | 约束 | 说明 |
|--------|------|------|--------|------|------|
| limit | int | 否 | `20` | 1-100 | 返回数量 |
| offset | int | 否 | `0` | >= 0 | 偏移量 |

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| items | array | 待审核技能列表（结构同 2.1 列表项 SkillListItemResponse） |
| total | int | 待审核技能总数 |

**响应示例**

```json
{
  "items": [
    {
      "id": 12,
      "name": "suspicious-skill",
      "display_name": "可疑技能示例",
      "description": "包含潜在安全风险的技能",
      "category": null,
      "tags": null,
      "icon": null,
      "version": 1,
      "skill_source": "custom",
      "install_count": 0,
      "rating_avg": 0.0,
      "rating_count": 0,
      "author_name": null,
      "created_at": "2026-05-09T10:00:00",
      "updated_at": "2026-05-09T10:00:00"
    }
  ],
  "total": 1
}
```

---

## 典型使用流程

```
1. 创建技能
   ├─ 准备 SKILL.md + 资源文件 → 打包为 ZIP
   └─ POST /skills/validate       → 前端可选：验证 SKILL.md 格式

2. 上传技能
   └─ POST /skills/upload          → 上传 ZIP，自动安全审查
      ├─ review_status=1 (APPROVED) → 可直接发布
      ├─ review_status=2 (SUSPICIOUS) → 进入管理员审核队列
      └─ review_status=3 (REJECTED) → 修改后重新上传

3. 管理员查看审核队列（仅 SUSPICIOUS 时）
   └─ GET /skills/admin/reviews    → 查看待审核列表

4. 发布技能
   └─ POST /skills/{id}/publish    → 发布到广场（需 review_status 通过）

5. 浏览与安装
   ├─ GET /skills/marketplace      → 浏览广场
   ├─ GET /skills/{id}             → 查看技能详情
   ├─ POST /skills/{id}/install    → 安装到 Agent
   └─ GET /skills/installed/{agent_id} → 查看 Agent 已安装的技能

6. 评价
   ├─ POST /skills/{id}/reviews    → 提交评价
   └─ GET /skills/{id}/reviews     → 查看评价列表

7. 版本更新
   ├─ PUT /skills/{id}/upload      → 上传新版本 ZIP（版本号自动 +1）
   └─ POST /skills/{id}/publish    → 重新发布

8. 管理（管理员）
   ├─ GET /skills/admin/settings   → 查看审查设置
   └─ PUT /skills/admin/settings   → 开关 LLM 安全审查
```

---

## 安全审查机制

技能上传时自动执行双层安全审查：

### 规则引擎（始终启用）

基于正则表达式检查 11 种安全模式，包括：
- 提示注入攻击模式
- 敏感信息泄露模式
- 恶意代码执行模式
- 权限绕过模式

### LLM 审查（管理员可开关）

通过 `PUT /skills/admin/settings` 接口启用。使用 LLM 对 SKILL.md 内容进行深度语义分析，识别潜在安全风险。

### 审查结果判定

| 规则引擎 | LLM 审查 | 最终状态 |
|---------|---------|---------|
| 通过 | 未启用 / 通过 | APPROVED（`1`） |
| 通过 | 可疑 | SUSPICIOUS（`2`） |
| 失败 | 任意 | REJECTED（`3`） |
| 通过 | 拒绝 | REJECTED（`3`） |

---

## 模块错误码汇总

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| SKILL_NOT_FOUND | 404 | 技能不存在 |
| SKILL_ALREADY_EXISTS | 409 | 同一用户下已存在同名技能 |
| SKILL_NOT_PUBLISHED | 400 | 技能未发布，无法安装 |
| SKILL_ACCESS_DENIED | 403 | 无权操作（非技能所有者） |
| SKILL_ALREADY_INSTALLED | 409 | 技能已安装到该 Agent |
| SKILL_NOT_INSTALLED | 404 | 技能未安装到该 Agent |
| INVALID_SKILL_FORMAT | 400 | SKILL.md 格式无效 |
| SKILL_REVIEW_REJECTED | 400 | 安全审查未通过 |
