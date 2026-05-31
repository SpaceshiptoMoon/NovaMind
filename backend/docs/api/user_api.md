# 用户管理模块 API 文档

## 概述

用户管理模块提供用户注册、认证、信息管理和模型配置等功能。所有接口的基础路径为 `/api/v1/user`。

### 认证方式

除登录和刷新令牌接口外，所有接口均需要在请求头中携带 JWT 访问令牌：

```
Authorization: Bearer <access_token>
```

**使用前提**：
1. 通过 `POST /api/v1/user/users/login`（接口 2）登录获取 access_token 和 refresh_token
2. 访问令牌（access_token）有效期 30 分钟
3. 过期后通过 `POST /api/v1/user/users/refresh`（接口 3）使用 refresh_token 获取新的令牌
4. 部分接口需要管理员权限（`is_admin = true`），文档中已标注"需要管理员权限"
5. 用户被软删除、停用或管理员强制撤销会话后，所有 Token 将立即失效（基于用户级黑名单机制）

### 用户状态说明

| 状态值 | 含义 |
|-------|------|
| 0 | 禁用（INACTIVE） |
| 1 | 正常（ACTIVE） |
| 2 | 封禁（BANNED） |
| 3 | 已删除（DELETED） |

### 通用错误响应格式

所有接口在发生错误时，返回以下统一格式：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "错误描述信息"
  },
  "timestamp": "2026-04-15T12:00:00.000000"
}
```

### 通用错误码

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `AUTHENTICATION_FAILED` | 401 | 认证失败（未携带 Token 或 Token 无效） |
| `TOKEN_EXPIRED` | 401 | Token 已过期，请重新登录 |
| `TOKEN_INVALID` | 401 | 无效的登录凭证 |
| `PERMISSION_DENIED` | 403 | 权限不足 |
| `INTERNAL_ERROR` | 500 | 服务器内部错误 |

---

## 1. 创建用户

**请求**
- 方法：POST
- URL：`/api/v1/user/users`
- Content-Type：application/json
- 权限：需要管理员权限

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| username | string | 是 | body | 用户名，3-50 个字符，只能包含字母、数字、下划线，不能以下划线开头或结尾，不能包含连续下划线 |
| email | string | 是 | body | 邮箱地址，必须符合邮箱格式 |
| password | string | 是 | body | 密码，8-30 个字符，必须包含大写字母、小写字母、数字和特殊字符，且不能包含用户名 |
| phone | string | 否 | body | 手机号码，11 位，以 1 开头，第二位为 3-9 |

**请求示例**

```json
{
  "username": "zhangsan",
  "email": "zhangsan@example.com",
  "password": "Secure@123",
  "phone": "13800138000"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 用户唯一 ID |
| username | string | 用户名 |
| email | string | 邮箱地址 |
| phone | string \| null | 手机号码 |
| is_admin | boolean | 是否管理员，默认 false |
| status | integer | 用户状态，1 为正常 |
| last_login_at | string \| null | 最后登录时间（ISO 8601 格式） |
| created_at | string | 创建时间（ISO 8601 格式） |
| updated_at | string \| null | 最后更新时间（ISO 8601 格式） |

**响应示例**

```json
{
  "id": 1,
  "username": "zhangsan",
  "email": "zhangsan@example.com",
  "phone": "13800138000",
  "is_admin": false,
  "status": 1,
  "last_login_at": null,
  "created_at": "2026-04-15T10:30:00",
  "updated_at": null
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `USER_ALREADY_EXISTS` | 409 | 用户名、邮箱或手机号已被注册 |
| `USER_CREATION_FAILED` | 400 | 用户创建失败 |
| `PERMISSION_DENIED` | 403 | 非管理员用户无权创建 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

**速率限制**：3 次/分钟

---

## 2. 用户登录

> **无需认证**：此接口不需要携带 Token。

**请求**
- 方法：POST
- URL：`/api/v1/user/users/login`
- Content-Type：application/json
- 权限：无需认证

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| username | string | 是 | body | 用户名或邮箱 |
| password | string | 是 | body | 密码 |

**请求示例**

```json
{
  "username": "zhangsan",
  "password": "Secure@123"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| access_token | string | 访问令牌（JWT 格式） |
| token_type | string | 令牌类型，固定为 `bearer` |
| refresh_token | string \| null | 刷新令牌，用于获取新的访问令牌 |
| expires_in | integer \| null | 访问令牌过期时间（秒） |

**响应示例**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in": 1800
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `INVALID_CREDENTIALS` | 400 | 用户名或密码错误 |
| `AUTHENTICATION_FAILED` | 401 | 认证失败 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

**速率限制**：5 次/分钟

---

## 3. 刷新令牌

> **无需认证**：此接口不需要携带 access_token，但需要提供 refresh_token。

**请求**
- 方法：POST
- URL：`/api/v1/user/users/refresh`
- Content-Type：application/json
- 权限：无需认证

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| refresh_token | string | 是 | body | 刷新令牌 |

**请求示例**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| access_token | string | 新的访问令牌 |
| refresh_token | string | 新的刷新令牌 |
| token_type | string | 令牌类型，固定为 `bearer` |
| expires_in | integer \| null | 访问令牌过期时间（秒） |

**响应示例**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 1800
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `TOKEN_EXPIRED` | 410 | 刷新令牌已过期 |
| `TOKEN_INVALID` | 400 | 无效的刷新令牌 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

**速率限制**：5 次/分钟

---

## 4. 用户登出

**请求**
- 方法：POST
- URL：`/api/v1/user/users/logout`
- 权限：需要登录

**请求参数**

无请求体参数。从请求头 `Authorization` 中自动提取 Token 并加入黑名单。

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |

**响应示例**

```json
{
  "message": "登出成功"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 5. 获取用户列表

**请求**
- 方法：GET
- URL：`/api/v1/user/users`
- 权限：需要管理员权限

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| skip | integer | 否 | query | 跳过的记录数，默认 0 |
| limit | integer | 否 | query | 返回的最大记录数，1-100，默认 20 |

**请求示例**

```
GET /api/v1/user/users?skip=0&limit=20
```

**响应参数**

返回数组，每个元素包含以下字段：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 用户唯一 ID |
| username | string | 用户名 |
| email | string | 邮箱地址 |
| phone | string \| null | 手机号码 |
| is_admin | boolean | 是否管理员 |
| status | integer | 用户状态 |
| last_login_at | string \| null | 最后登录时间 |
| created_at | string | 创建时间 |
| updated_at | string \| null | 最后更新时间 |

**响应示例**

```json
[
  {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "phone": null,
    "is_admin": true,
    "status": 1,
    "last_login_at": "2026-04-15T09:00:00",
    "created_at": "2026-01-01T00:00:00",
    "updated_at": "2026-04-15T09:00:00"
  },
  {
    "id": 2,
    "username": "zhangsan",
    "email": "zhangsan@example.com",
    "phone": "13800138000",
    "is_admin": false,
    "status": 1,
    "last_login_at": null,
    "created_at": "2026-04-15T10:30:00",
    "updated_at": null
  }
]
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `PERMISSION_DENIED` | 403 | 非管理员用户无权访问 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 6. 获取用户详情

**请求**
- 方法：GET
- URL：`/api/v1/user/users/{user_id}`
- 权限：需要登录（普通用户仅可查看自己，管理员可查看所有用户）

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| user_id | integer | 是 | path | 用户 ID，必须大于 0 |

**请求示例**

```
GET /api/v1/user/users/1
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 用户唯一 ID |
| username | string | 用户名 |
| email | string | 邮箱地址 |
| phone | string \| null | 手机号码 |
| is_admin | boolean | 是否管理员 |
| status | integer | 用户状态 |
| last_login_at | string \| null | 最后登录时间 |
| created_at | string | 创建时间 |
| updated_at | string \| null | 最后更新时间 |

**响应示例**

```json
{
  "id": 1,
  "username": "zhangsan",
  "email": "zhangsan@example.com",
  "phone": "13800138000",
  "is_admin": false,
  "status": 1,
  "last_login_at": "2026-04-15T09:00:00",
  "created_at": "2026-04-15T10:30:00",
  "updated_at": null
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `PERMISSION_DENIED` | 403 | 普通用户查看其他用户信息 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 7. 更新用户信息

**请求**
- 方法：PUT
- URL：`/api/v1/user/users/{user_id}`
- Content-Type：application/json
- 权限：需要登录（普通用户仅可修改自己，`is_admin` 和 `status` 字段仅管理员可修改）

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| user_id | integer | 是 | path | 用户 ID，必须大于 0 |
| username | string | 否 | body | 用户名，3-50 个字符，只能包含字母、数字、下划线 |
| email | string | 否 | body | 邮箱地址 |
| phone | string | 否 | body | 手机号码 |
| password | string | 否 | body | 新密码，8-30 个字符，必须包含大写字母、小写字母、数字和特殊字符，且不能包含用户名 |
| is_admin | boolean | 否 | body | 是否管理员（仅管理员可修改） |
| status | integer | 否 | body | 用户状态：0-禁用，1-正常，2-封禁，3-已删除（仅管理员可修改） |

> 注意：仅传入需要修改的字段，未传入的字段不会被更新。

**请求示例**

```json
{
  "email": "newemail@example.com",
  "phone": "13900139000"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 用户唯一 ID |
| username | string | 用户名 |
| email | string | 邮箱地址 |
| phone | string \| null | 手机号码 |
| is_admin | boolean | 是否管理员 |
| status | integer | 用户状态 |
| last_login_at | string \| null | 最后登录时间 |
| created_at | string | 创建时间 |
| updated_at | string \| null | 最后更新时间 |

**响应示例**

```json
{
  "id": 2,
  "username": "zhangsan",
  "email": "newemail@example.com",
  "phone": "13900139000",
  "is_admin": false,
  "status": 1,
  "last_login_at": null,
  "created_at": "2026-04-15T10:30:00",
  "updated_at": "2026-04-15T11:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `USER_ALREADY_EXISTS` | 409 | 用户名、邮箱或手机号已被占用 |
| `PERMISSION_DENIED` | 403 | 普通用户修改其他用户信息，或修改敏感字段 |
| `USER_OPERATION_FAILED` | 400 | 用户操作失败 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

---

## 8. 删除用户

**请求**
- 方法：DELETE
- URL：`/api/v1/user/users/{user_id}`
- 权限：需要管理员权限（管理员不可删除自己）

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| user_id | integer | 是 | path | 用户 ID，必须大于 0 |

**请求示例**

```
DELETE /api/v1/user/users/2
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |

**响应示例**

```json
{
  "message": "用户已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `PERMISSION_DENIED` | 403 | 管理员删除自己的账户，或非管理员操作 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

> 注意：此操作为软删除，删除后该用户的所有 Token 将立即失效。

---

## 9. 停用/激活用户

**请求**
- 方法：PATCH
- URL：`/api/v1/user/users/{user_id}/status`
- 权限：需要管理员权限（管理员不可停用自己）

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| user_id | integer | 是 | path | 用户 ID，必须大于 0 |

**请求示例**

```
PATCH /api/v1/user/users/2/status
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息，"用户已停用" 或 "用户已激活" |

**响应示例**

```json
{
  "message": "用户已停用"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `USER_NOT_FOUND` | 404 | 用户不存在 |
| `PERMISSION_DENIED` | 403 | 管理员停用自己的账户，或非管理员操作 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

> 注意：
> - 停用用户后，该用户的所有 Token 将立即失效。
> - 激活用户后，将清除该用户的 Token 黑名单，允许正常登录。
> - 此接口为切换操作：当前为正常状态则停用，当前为停用状态则激活。

---

## 10. 强制撤销所有会话

**请求**
- 方法：POST
- URL：`/api/v1/user/users/{user_id}/logout-all`
- 权限：需要管理员权限

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| user_id | integer | 是 | path | 用户 ID，必须大于 0 |

**请求示例**

```
POST /api/v1/user/users/2/logout-all
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |
| revoked_count | integer | 已撤销的会话数量 |

**响应示例**

```json
{
  "message": "已撤销用户 2 的所有会话",
  "revoked_count": 3
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `PERMISSION_DENIED` | 403 | 非管理员用户操作 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 11. 获取可用模型列表

获取当前用户可用的所有模型名称（用户私有配置），供前端下拉框使用。

**请求**
- 方法：GET
- URL：`/api/v1/user/model-configs/available`
- 权限：需要登录

**请求参数**

无额外参数。

**请求示例**

```
GET /api/v1/user/model-configs/available
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| llm | string[] | 可用的 LLM 模型名称列表 |
| embedding | string[] | 可用的 Embedding 模型名称列表 |
| rerank | string[] | 可用的 Rerank 模型名称列表 |
| vlm | string[] | 可用的 VLM（视觉语言模型）名称列表 |

**响应示例**

```json
{
  "llm": ["gpt-4o", "glm-4", "qwen-plus"],
  "embedding": ["text-embedding-3-small", "embedding-3"],
  "rerank": ["bge-reranker-v2-m3"],
  "vlm": ["qwen-vl-max"]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 12. 获取可用模型详细信息

获取当前用户可用的所有模型详细信息（包含通信协议等）。

**请求**
- 方法：GET
- URL：`/api/v1/user/model-configs/available/detail`
- 权限：需要登录

**请求参数**

无额外参数。

**请求示例**

```
GET /api/v1/user/model-configs/available/detail
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| llm | object[] | LLM 模型信息列表 |
| llm[].model | string | 模型名称 |
| llm[].protocol | string | 通信协议 |
| embedding | object[] | Embedding 模型信息列表（结构同上） |
| rerank | object[] | Rerank 模型信息列表（结构同上） |

**响应示例**

```json
{
  "llm": [
    {
      "model": "gpt-4o",
      "protocol": "openai"
    },
    {
      "model": "glm-4",
      "protocol": "openai"
    }
  ],
  "embedding": [
    {
      "model": "text-embedding-3-small",
      "protocol": "openai"
    }
  ],
  "rerank": []
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 13. 获取模型配置列表

获取当前用户的私有模型配置列表，可按模型类型筛选。

**请求**
- 方法：GET
- URL：`/api/v1/user/model-configs`
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| model_type | string | 否 | query | 模型类型筛选，可选值：`llm`、`embedding`、`rerank` |

**请求示例**

```
GET /api/v1/user/model-configs?model_type=llm
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| total | integer | 配置总数 |
| items | object[] | 配置列表 |
| items[].id | integer | 配置 ID |
| items[].user_id | integer | 用户 ID |
| items[].model_type | string | 模型类型：llm / embedding / rerank |
| items[].protocol | string | 通信协议：openai / anthropic / ollama / transformers |
| items[].model | string | 模型名称 |
| items[].base_url | string \| null | API Base URL |
| items[].api_key | string \| null | API Key（已脱敏） |
| items[].extra_config | object \| null | 扩展配置（如 dimension、endpoint 等） |
| items[].created_at | string | 创建时间（ISO 8601 格式） |
| items[].updated_at | string | 更新时间（ISO 8601 格式） |

> 注意：此接口返回用户的模型配置列表。

**响应示例**

```json
{
  "total": 2,
  "items": [
    {
      "id": 10,
      "user_id": 2,
      "model_type": "llm",
      "protocol": "openai",
      "model": "glm-4",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "api_key": "sk-****xxxx",
      "extra_config": null,
      "created_at": "2026-04-15T10:00:00",
      "updated_at": "2026-04-15T10:00:00"
    },
    {
      "id": 11,
      "user_id": 2,
      "model_type": "embedding",
      "protocol": "openai",
      "model": "embedding-3",
      "base_url": "https://open.bigmodel.cn/api/paas/v4",
      "api_key": "sk-****xxxx",
      "extra_config": {"dimension": 1024},
      "created_at": "2026-04-15T10:05:00",
      "updated_at": "2026-04-15T10:05:00"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |

---

## 14. 创建用户私有模型配置

**请求**
- 方法：POST
- URL：`/api/v1/user/model-configs`
- Content-Type：application/json
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| model_type | string | 是 | body | 模型类型：`llm`、`embedding`、`rerank` |
| protocol | string | 是 | body | 通信协议：`openai`、`anthropic`、`ollama`、`transformers`，1-50 个字符 |
| model | string | 是 | body | 模型名称 |
| base_url | string | 否 | body | API Base URL |
| api_key | string | 否 | body | API Key |
| extra_config | object | 否 | body | 扩展配置（如 dimension、endpoint 等） |

> 注意：同一用户的 (model_type, model) 组合必须唯一。如果是 embedding 类型，系统会自动探测向量维度。

**请求示例**

```json
{
  "model_type": "llm",
  "protocol": "openai",
  "model": "glm-4",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key": "sk-xxxxxxxxxxxxxxxx",
  "extra_config": null
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 配置 ID |
| user_id | integer | 用户 ID |
| model_type | string | 模型类型 |
| protocol | string | 通信协议 |
| model | string | 模型名称 |
| base_url | string \| null | API Base URL |
| api_key | string \| null | API Key（已脱敏） |
| extra_config | object \| null | 扩展配置 |
| created_at | string | 创建时间 |
| updated_at | string | 更新时间 |

**响应示例**

```json
{
  "id": 12,
  "user_id": 2,
  "model_type": "llm",
  "protocol": "openai",
  "model": "glm-4",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key": "sk-****xxxx",
  "extra_config": null,
  "created_at": "2026-04-15T11:00:00",
  "updated_at": "2026-04-15T11:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_ALREADY_EXISTS` | 409 | 同类型下模型名称已存在 |
| `MODEL_CONFIG_ERROR` | 400 | 模型配置错误 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

**速率限制**：10 次/分钟

---

## 15. 获取单个模型配置

**请求**
- 方法：GET
- URL：`/api/v1/user/model-configs/{config_id}`
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| config_id | integer | 是 | path | 配置 ID，必须大于 0 |

**请求示例**

```
GET /api/v1/user/model-configs/12
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 配置 ID |
| user_id | integer | 用户 ID |
| model_type | string | 模型类型 |
| protocol | string | 通信协议 |
| model | string | 模型名称 |
| base_url | string \| null | API Base URL |
| api_key | string \| null | API Key（已脱敏） |
| extra_config | object \| null | 扩展配置 |
| created_at | string | 创建时间 |
| updated_at | string | 更新时间 |

**响应示例**

```json
{
  "id": 12,
  "user_id": 2,
  "model_type": "llm",
  "protocol": "openai",
  "model": "glm-4",
  "base_url": "https://open.bigmodel.cn/api/paas/v4",
  "api_key": "sk-****xxxx",
  "extra_config": null,
  "created_at": "2026-04-15T11:00:00",
  "updated_at": "2026-04-15T11:00:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_NOT_FOUND` | 404 | 配置不存在 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

---

## 16. 更新模型配置

**请求**
- 方法：PUT
- URL：`/api/v1/user/model-configs/{config_id}`
- Content-Type：application/json
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| config_id | integer | 是 | path | 配置 ID，必须大于 0 |
| protocol | string | 否 | body | 通信协议，1-50 个字符 |
| model | string | 否 | body | 模型名称 |
| base_url | string | 否 | body | API Base URL |
| api_key | string | 否 | body | API Key |
| extra_config | object | 否 | body | 扩展配置 |

> 注意：仅传入需要修改的字段，未传入的字段不会被更新。

**请求示例**

```json
{
  "base_url": "https://new-api.example.com/v1",
  "api_key": "sk-newkeyxxxxxxxx"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| id | integer | 配置 ID |
| user_id | integer | 用户 ID |
| model_type | string | 模型类型 |
| protocol | string | 通信协议 |
| model | string | 模型名称 |
| base_url | string \| null | API Base URL |
| api_key | string \| null | API Key（已脱敏） |
| extra_config | object \| null | 扩展配置 |
| created_at | string | 创建时间 |
| updated_at | string | 更新时间 |

**响应示例**

```json
{
  "id": 12,
  "user_id": 2,
  "model_type": "llm",
  "protocol": "openai",
  "model": "glm-4",
  "base_url": "https://new-api.example.com/v1",
  "api_key": "sk-****xxxx",
  "extra_config": null,
  "created_at": "2026-04-15T11:00:00",
  "updated_at": "2026-04-15T11:30:00"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_NOT_FOUND` | 404 | 配置不存在 |
| `MODEL_CONFIG_ALREADY_EXISTS` | 409 | 修改后的模型名称与已有配置冲突 |
| `MODEL_CONFIG_ERROR` | 400 | 模型配置错误 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

**速率限制**：10 次/分钟

---

## 17. 删除模型配置

**请求**
- 方法：DELETE
- URL：`/api/v1/user/model-configs/{config_id}`
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| config_id | integer | 是 | path | 配置 ID，必须大于 0 |

**请求示例**

```
DELETE /api/v1/user/model-configs/12
```

**响应参数（成功）**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |

**响应示例（成功）**

```json
{
  "message": "配置已删除"
}
```

**响应参数（存在关联资源）**

当存在关联资源（如会话配置引用了该模型配置）时，返回 409 状态码：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |
| impacts | object | 关联资源影响详情 |

**响应示例（存在关联资源）**

```json
{
  "message": "无法删除，存在关联资源",
  "impacts": {
    "session_configs": [
      {
        "id": 5,
        "name": "默认配置",
        "field": "llm_model",
        "model": "glm-4"
      }
    ]
  }
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_NOT_FOUND` | 404 | 配置不存在 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

> 注意：HTTP 409 不是错误码，而是业务提示，表示存在关联资源需要先处理。

---

## 18. 测试模型连接

测试模型配置是否有效，自动探测 Embedding 维度。

**请求**
- 方法：POST
- URL：`/api/v1/user/model-configs/test`
- Content-Type：application/json
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| model_type | string | 是 | body | 模型类型：`llm`、`embedding`、`rerank` |
| protocol | string | 否 | body | 通信协议，默认 `openai` |
| model | string | 是 | body | 模型名称 |
| base_url | string | 否 | body | API Base URL |
| api_key | string | 是 | body | API Key |

**请求示例**

```json
{
  "model_type": "embedding",
  "protocol": "openai",
  "model": "text-embedding-3-small",
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-xxxxxxxxxxxxxxxx"
}
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| success | boolean | 测试是否成功 |
| message | string | 测试结果消息 |
| latency_ms | float \| null | 响应延迟（毫秒） |
| detected_dimension | integer \| null | 自动检测的 Embedding 向量维度（仅 embedding 类型返回） |

**响应示例**

```json
{
  "success": true,
  "message": "连接成功",
  "latency_ms": 235.6,
  "detected_dimension": 1536
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_TEST_FAILED` | 400 | 模型连接测试失败 |
| `VALIDATION_ERROR` | 422 | 请求参数验证失败 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

**速率限制**：5 次/分钟

> 测试行为说明：
> - **LLM**：发送 "Hello" 获取响应
> - **Embedding**：对 "Hello" 进行向量化，返回维度
> - **Rerank**：对 ["Hello", "World"] 进行重排序

---

## 19. 按模型名称删除配置

根据模型类型和模型名称删除用户私有配置。

**请求**
- 方法：DELETE
- URL：`/api/v1/user/model-configs/by-model/{model_type}/{model}`
- 权限：需要登录

**请求参数**

| 参数名 | 类型 | 必填 | 位置 | 说明 |
|--------|------|------|------|------|
| model_type | string | 是 | path | 模型类型：`llm`、`embedding`、`rerank` |
| model | string | 是 | path | 模型名称 |

**请求示例**

```
DELETE /api/v1/user/model-configs/by-model/llm/glm-4
```

**响应参数**

| 参数名 | 类型 | 说明 |
|--------|------|------|
| message | string | 响应消息 |

**响应示例**

```json
{
  "message": "配置 llm/glm-4 已删除"
}
```

**错误码**

| 错误码 | HTTP 状态码 | 说明 |
|--------|-----------|------|
| `MODEL_CONFIG_NOT_FOUND` | 404 | 配置不存在 |
| `AUTHENTICATION_FAILED` | 401 | 未登录或 Token 无效 |

> 注意：只能删除用户私有配置。
