# 智能知识库前端开发计划

## 现有代码审计结果

> **更新 (2026-05)**：以下 8 个严重问题和 6 个缺失功能已全部修复/实现，状态标注如下。

### 严重问题（会导致运行时崩溃）

| # | 问题 | 状态 |
|---|------|------|
| 1 | 响应拦截器假设后端返回 `{code, message, data}` 包装，但后端实际直接返回裸数据 | ✅ 已修复 — `api/index.ts` 直接返回 `response.data` |
| 2 | 搜索 API 路径完全错误，后端用 `/spaces/{id}/knowledge-bases/{kbId}/search`，前端用 `/spaces/{id}/search?kb_id=` | ✅ 已修复 — `api/search.ts` 使用正确路径 |
| 3 | `clearChatHistory` 用 POST 请求，后端要求 DELETE | ✅ 已修复 — 使用 `request.delete()` |
| 4 | `updateSystemPrompt` 调用不存在的接口 | ✅ 已修复 — 函数已移除 |
| 5 | `ResearchRequest` 请求体结构错误，后端需要嵌套对象（`internal_search`/`external_search`/`llm`），前端发扁平字段 | ✅ 已修复 — `types.ts` 使用嵌套结构 |
| 6 | `SearchRequest` 同样的嵌套结构错误 | ✅ 已修复 — `types.ts` 使用嵌套 `weights`/`rerank`/`llm`/`query_rewrite` |
| 7 | SSE 流式响应的 error 事件被内部 catch 吞掉，用户永远看不到错误 | ✅ 已修复 — Store 明确设置 `error.value` |
| 8 | `SessionConfig` 类型结构与后端不匹配（扁平 vs 嵌套 `compression_config`） | ✅ 已修复 — 使用嵌套 `compression` 对象 |

### 缺失的功能

| # | 缺失内容 | 状态 |
|---|---------|------|
| 1 | 用户模型配置管理（LLM/Embedding/Rerank 私有配置 CRUD + 连接测试） | ✅ 已实现 — `api/user.ts` 全部 9 个方法 |
| 2 | QA 消息/会话 CRUD（添加消息、获取消息列表、获取会话列表、更新/删除消息、删除会话、获取上下文） | ✅ 已实现 — `api/session.ts` 全部 7 个方法 |
| 3 | 会话配置管理（创建/获取/删除压缩配置） | ✅ 已实现 — `api/session.ts` 3 个方法 |
| 4 | 路由缺少 `/403` 页面（守卫已重定向但无路由） | ✅ 已实现 — 路由和 `ForbiddenView.vue` 均存在 |
| 5 | 无 Token 自动刷新机制（30 分钟强制登出） | ✅ 已实现 — `api/index.ts` 401 自动刷新 + 请求队列 |
| 6 | SSE 流无 AbortController（无法取消进行中的流） | ✅ 已实现 — `createSSEStream` 接受 `signal`，Store 使用 AbortController |

### 代码质量问题

| # | 问题 | 文件 | 影响 |
|---|------|------|------|
| 1 | 响应拦截器假设后端返回 `{code, message, data}` 包装，但后端实际直接返回裸数据 | `api/index.ts` | 所有接口可能误判为错误 |
| 2 | 搜索 API 路径完全错误，后端用 `/spaces/{id}/knowledge-bases/{kbId}/search`，前端用 `/spaces/{id}/search?kb_id=` | `api/search.ts` | 搜索功能完全不可用 |
| 3 | `clearChatHistory` 用 POST 请求，后端要求 DELETE | `api/chat.ts` | 清除聊天历史报 405 |
| 4 | `updateSystemPrompt` 调用不存在的接口 | `api/chat.ts` | 始终 404 |
| 5 | `ResearchRequest` 请求体结构错误，后端需要嵌套对象（`internal_search`/`external_search`/`llm`），前端发扁平字段 | `api/types.ts` | 深度研究高级参数全部丢失 |
| 6 | `SearchRequest` 同样的嵌套结构错误 | `api/search.ts` | 搜索高级参数全部丢失 |
| 7 | SSE 流式响应的 error 事件被内部 catch 吞掉，用户永远看不到错误 | `stores/chat.ts`, `stores/research.ts` | 流式错误静默丢失 |
| 8 | `SessionConfig` 类型结构与后端不匹配（扁平 vs 嵌套 `compression_config`） | `api/types.ts` | 会话配置功能不可用 |

### 缺失的功能

| # | 缺失内容 | 后端接口数量 |
|---|---------|-------------|
| 1 | 用户模型配置管理（LLM/Embedding/Rerank 私有配置 CRUD + 连接测试） | 9 个接口 |
| 2 | QA 消息/会话 CRUD（添加消息、获取消息列表、获取会话列表、更新/删除消息、删除会话、获取上下文） | 7 个接口 |
| 3 | 会话配置管理（创建/获取/删除压缩配置） | 3 个接口 |
| 4 | 路由缺少 `/403` 页面（守卫已重定向但无路由） | - |
| 5 | 无 Token 自动刷新机制（30 分钟强制登出） | - |
| 6 | SSE 流无 AbortController（无法取消进行中的流） | - |

### 代码质量问题

| # | 问题 |
|---|------|
| 1 | 6 个通用组件已编写但从未被任何页面使用 |
| 2 | `MainLayout` 侧边栏无法高亮嵌套路由（`/spaces/1/knowledge-bases` 不会激活"知识空间"菜单） |
| 3 | 无 `.env` 文件，无 Vite 开发代理配置，无法联调后端 |
| 4 | 多处 `ElMessageBox` 取消判断使用不安全的 `(error as string) !== 'cancel'` |
| 5 | vitest 已配置但无任何测试文件 |
| 6 | 路由守卫直接读 `localStorage` 而非使用 user store |

---

## 开发计划

### 总体策略

**从底层到上层，逐层重建**：基础设施 → API 层 → 状态管理 → 页面视图 → 打磨优化。每个阶段完成后可独立验证。

---

## 阶段 0：基础设施修复（预计 1-2 小时）

> 目标：让项目能在开发环境正常运行，与后端联调。

### 0.1 环境配置

- 创建 `.env.development`：定义 `VITE_API_BASE_URL=http://localhost:8100`
- 创建 `.env.production`：定义 `VITE_API_BASE_URL=`（使用相对路径，部署时同域）
- 创建 `.env.example`：模板文件
- 配置 `vite.config.ts` 开发代理：将 `/api` 代理到 `http://localhost:8100`

### 0.2 修复 Axios 实例

**重写 `src/api/index.ts`**：

- 移除 `ApiResponse` 包装类型的假设——后端直接返回数据或错误
- 响应拦截器：200-299 直接返回 `response.data`，其余走错误处理
- 添加 **静默 Token 刷新机制**：
  - 401 响应时，使用 `refresh_token` 自动获取新 token
  - 刷新期间其他请求排队等待（避免并发刷新）
  - 刷新失败才跳转登录页
- 添加 **请求取消支持**：基于 `AbortController`
- 删除辅助方法保持不变（upload、download 等）
- SSE 流式请求继续使用原生 `fetch`，但统一 token 获取方式

### 0.3 修复路由

- 添加 `/403` 路由指向 `ForbiddenView.vue`（新建）
- 修复 `MainLayout` 侧边栏 active 高亮逻辑：使用 `route.matched` 或手动计算

### 0.4 验收标准

- [ ] `npm run dev` 启动无报错
- [ ] 登录页能正常显示
- [ ] 登录后能获取用户信息
- [ ] Token 过期能自动刷新而非强制登出
- [ ] 无权限时正确显示 403 页面

---

## 阶段 1：API 层重建（预计 3-4 小时）

> 目标：所有 API 调用与后端接口文档 100% 对齐，类型定义完整准确。

### 1.1 重写类型定义 `src/api/types.ts`

按后端文档逐字段校验，**严格对齐**所有接口的请求和响应类型：

**用户模块类型**：
- `User`、`LoginRequest`、`LoginResponse`、`RefreshTokenRequest`、`RefreshTokenResponse`
- `CreateUserRequest`、`UpdateUserRequest`（区分普通用户/管理员可修改字段）
- `ModelConfig`、`CreateModelConfigRequest`、`UpdateModelConfigRequest`、`ModelConfigTestRequest`、`ModelConfigTestResponse`
- `AvailableModels`、`AvailableModelDetail`、`AvailableModelItem`

**知识空间模块类型**：
- `Space`、`SpaceConfig`、`CreateSpaceRequest`、`UpdateSpaceRequest`、`SpaceListResponse`
- `KnowledgeBase`、`KBConfig`、`SplittingConfig`（联合类型：recursive/fixed_size/markdown/semantic）、`ParsingConfig`、`EmbeddingConfig`、`QuestionGenerationConfig`
- `CreateKBRequest`、`UpdateKBRequest`、`KBConfigResponse`
- `Document`、`DocumentDetail`（含 chunks）、`Chunk`、`DocumentStatus`
- `Member`、`InviteRequest`、`InviteResponse`、`JoinRequest`、`UpdateMemberRoleRequest`

**搜索模块类型**：
- `SearchRequest`（嵌套 `weights`、`rerank`、`llm`、`query_rewrite` 对象）
- `SearchResult`（含 `chunk_id`、`kb_id`、`metadata`、`file_info`）
- `SearchResponse`（含 `original_mode`、`mode_fallback`、`answer`、`answer_model`、`elapsed_ms`、`cached`）
- `SearchMode`、`SearchModelConfig`

**问答模块类型**：
- `ChatRequest`（含 `llm_model`、`max_tokens`、`temperature`、`top_p`、`system_prompt`）
- `ChatResponse`（含 `session_id`、`user_message`、`ai_message`、`conversation_history`）
- `QAMessage`（含完整字段：`id`、`content`、`role`、`user_id`、`session_id`、`space_id`、`kb_id`、`extra`、`created_at`）
- `SessionListItem`（`session_id` + `preview`）
- `SessionListResponse`（`items` + `total` + `limit` + `offset`）
- `AddMessageRequest`、`UpdateMessageRequest`

**会话配置类型**：
- `CompressionConfig`（`enable_compression`、`strategy`、`threshold`、`target_tokens`、`keep_recent`、`custom_prompt`）
- `CreateSessionConfigRequest`（嵌套 `compression` 对象）
- `SessionConfigResponse`（含 `id`、`session_id`、`user_id`、`compression_config`、`created_at`、`updated_at`）

**深度研究类型**：
- `ResearchRequest`（嵌套 `internal_search`、`external_search`、`llm` 对象）
- `Research`（含 `research_tasks`、`search_source`、`external_provider`、`search_summary`、`stats`）
- `ResearchTask`、`SearchSummary`、`ResearchStats`
- SSE 事件类型：`ProgressEvent`、`ContentEvent`、`DoneEvent`、`ErrorEvent`

### 1.2 重写 API 模块

**`src/api/user.ts`**——补充缺失的 9 个模型配置接口：

```
getAvailableModels()          → GET /user/model-configs/available
getAvailableModelDetails()    → GET /user/model-configs/available/detail
getModelConfigs(modelType?)   → GET /user/model-configs
createModelConfig(data)       → POST /user/model-configs
getModelConfig(configId)      → GET /user/model-configs/{configId}
updateModelConfig(configId, data) → PUT /user/model-configs/{configId}
deleteModelConfig(configId)   → DELETE /user/model-configs/{configId}
testModelConfig(data)         → POST /user/model-configs/test
deleteModelConfigByModel(modelType, model) → DELETE /user/model-configs/by-model/{modelType}/{model}
```

**`src/api/space.ts`**——验证并修正所有 7 个空间接口路径

**`src/api/member.ts`**——验证并修正所有 7 个成员接口路径

**`src/api/knowledgeBase.ts`**——验证并修正所有 7 个知识库接口路径

**`src/api/document.ts`**——验证并修正所有 9 个文档接口路径

**`src/api/search.ts`**——**重写**，修正 URL 路径和请求体结构：
```
search(spaceId, kbId, body)     → POST /spaces/{spaceId}/knowledge-bases/{kbId}/search
getSearchModes(spaceId, kbId)   → GET /spaces/{spaceId}/knowledge-bases/{kbId}/search/modes
getSearchModelConfig(spaceId, kbId) → GET /spaces/{spaceId}/knowledge-bases/{kbId}/search/model-config
```

**`src/api/chat.ts`**——**重写**：
- 修正 `clearChatHistory` 改为 DELETE 方法
- 删除不存在的 `updateSystemPrompt`
- 新增 `src/api/qa.ts`——QA 消息/会话管理（7 个接口）：
```
addMessage(data)                    → POST /qa/message
getSessionMessages(sessionId)       → GET /qa/session/{sessionId}
getSessions(limit?, offset?)        → GET /qa/sessions
updateMessage(messageId, data)      → PUT /qa/message/{messageId}
deleteMessage(messageId)            → DELETE /qa/message/{messageId}
deleteSession(sessionId)            → DELETE /qa/session/{sessionId}
getContext(sessionId, limit?)       → GET /qa/context/{sessionId}
```
- 新增 `src/api/sessionConfig.ts`——会话压缩配置（3 个接口）：
```
createSessionConfig(sessionId, data) → POST /sessions/{sessionId}/config
getSessionConfig(sessionId)          → GET /sessions/{sessionId}/config
deleteSessionConfig(sessionId)       → DELETE /sessions/{sessionId}/config
```

**`src/api/research.ts`**——修正请求体结构为嵌套格式

### 1.3 验收标准

- [ ] 所有 API 函数的 URL 路径与后端文档完全一致
- [ ] 所有请求/响应 TypeScript 类型与后端文档完全一致
- [ ] `npm run type-check` 通过
- [ ] 无硬编码 token 读取，统一使用 tokenManager

---

## 阶段 2：状态管理重构（预计 2-3 小时）

> 目标：修复所有 Store 的 bug，补充缺失功能，统一错误处理和 loading 模式。

### 2.1 重写 `src/stores/user.ts`

- 添加 `loading`、`error` 状态
- Token 过期检查（解码 JWT `exp` 字段）
- `fetchProfile` 修改变量遮蔽问题
- 添加 `modelConfigs` 状态和相关 actions（获取/创建/更新/删除/测试模型配置）

### 2.2 重写 `src/stores/chat.ts`

- 修复 SSE 流式响应中 error 事件被吞掉的 bug
- 添加 **AbortController** 支持，`sendMessageStream` 可取消
- 添加 `sendMessageStream` 的 `onAbort` 处理
- 修正 `currentMessages`（移除冗余 computed）
- 修复非流式发送失败时用户消息丢失问题
- 整合 QA 模块的会话管理：使用 `/qa/sessions` 获取会话列表，`/qa/session/{id}` 获取消息
- 添加会话配置 actions（创建/获取/删除压缩配置）

### 2.3 重写 `src/stores/research.ts`

- 修复 SSE 流式响应中 error 事件被吞掉的 bug
- 添加 **AbortController** 支持
- 修正请求体为嵌套结构
- `onDone` 事件正确映射到 `Research` 类型

### 2.4 重写 `src/stores/space.ts`

- 添加 `error` 状态
- 修复 `deleteSpace` 无错误处理
- 修复并发 loading 状态问题（按操作类型区分 loading）
- `fetchPublicSpaces` 不再静默吞错误

### 2.5 验收标准

- [ ] 所有 Store 有 `loading` + `error` 状态
- [ ] SSE 流可通过 AbortController 取消
- [ ] SSE error 事件能正确传递到 UI 层
- [ ] Token 刷新在 Store 层自动处理
- [ ] `npm run type-check` 通过

---

## 阶段 3：布局与路由完善（预计 2 小时）

> 目标：完善应用骨架，添加缺失的页面入口。

### 3.1 修复 `MainLayout.vue`

- 侧边栏菜单高亮修复：使用 `route.matched[0]?.path` 匹配父路由
- 添加"深度研究"菜单入口（需先选择知识空间）
- 添加"模型配置"菜单入口（`/settings/models`）

### 3.2 新增路由

```
/settings/models           → ModelConfigView.vue  （模型配置管理）
/403                       → ForbiddenView.vue    （无权限页面）
```

### 3.3 修复路由守卫 `guards.ts`

- 使用 user store 而非直接读取 localStorage
- 添加 Token 过期预检（解码 exp 字段）

### 3.4 新建 `ForbiddenView.vue`

- 显示 403 无权限提示
- 提供返回首页按钮

### 3.5 验收标准

- [ ] 侧边栏所有菜单正确高亮
- [ ] 所有路由可正常访问
- [ ] 无权限时正确显示 403
- [ ] 守卫正确拦截未登录/无权限访问

---

## 阶段 4：用户管理模块（预计 2-3 小时）

> 目标：完善登录、个人中心、用户管理、模型配置页面。

### 4.1 优化 `LoginView.vue`

- 添加登录loading状态
- 添加表单验证反馈
- 错误提示友好化（区分"用户名或密码错误"和"网络异常"）

### 4.2 优化 `UserProfileView.vue`

- 展示完整用户信息
- 修改密码功能（需后端接口支持或通过 updateUser 的 password 字段）
- 关联模型配置快捷入口

### 4.3 优化 `UserManageView.vue`（管理员）

- 表格列完整展示（状态使用 `StatusTag` 组件）
- 批量操作支持
- 确认弹窗使用 `ConfirmDialog` 组件

### 4.4 新建 `ModelConfigView.vue`

**核心功能**：
- 三个 Tab：LLM / Embedding / Rerank
- 每个类型展示用户私有配置（可编辑）
- 新增/编辑配置表单：模型类型、通信协议、模型名称、Base URL、API Key、扩展配置
- **连接测试**按钮：测试配置是否有效，显示延迟和 Embedding 维度
- 删除配置（处理 409 关联资源提示）
- API Key 输入框使用密码模式

### 4.5 验收标准

- [ ] 登录流程完整，错误提示友好
- [ ] 个人中心可正常查看和修改信息
- [ ] 管理员可完整管理用户（创建/编辑/删除/停用/激活/强制登出）
- [ ] 模型配置页面可 CRUD + 测试连接

---

## 阶段 5：知识空间模块（预计 4-5 小时）

> 目标：完善空间、知识库、文档、成员、搜索五大子模块。

### 5.1 优化 `SpaceListView.vue`

- 空间卡片展示完整信息（文档数、存储用量、可见性标签）
- 搜索功能使用 `SearchBar` 组件
- 公开空间列表展示
- 空状态使用 `EmptyState` 组件
- 分页使用 `Pagination` 组件

### 5.2 优化 `SpaceDetailView.vue`

- 空间头部完整信息展示
- Tab 导航（知识库/成员/搜索/深度研究）
- 编辑空间配置对话框（名称、可见性、描述、标签）
- 删除空间确认

### 5.3 优化 `KnowledgeBaseView.vue`

- 知识库表格完整展示
- **创建/编辑对话框补充完整配置**：
  - 基本信息Tab：名称、描述
  - 切分策略Tab：支持 4 种策略切换（recursive/fixed_size/markdown/semantic），每种显示对应参数
  - 解析配置Tab：提取图片、提取表格、OCR、保留结构、编码
  - 向量化配置Tab：模型选择（下拉框从可用模型列表获取）、维度、批处理大小
  - 问题生成Tab：启用开关、LLM 选择、每块最大问题数、自定义提示词
- 知识库配置详情查看
- 归档/取消归档

### 5.4 优化 `DocumentView.vue`

- 文档表格展示完整字段（状态使用 `StatusTag`，文件大小格式化，处理进度）
- **拖拽上传**保留（已有实现）
- 上传进度条
- **处理中的文档自动轮询刷新状态**
- 批量触发解析功能
- 重新解析功能
- 下载文档功能
- 使用 `Pagination` 组件

### 5.5 优化 `DocumentDetailView.vue`

- 文档基本信息展示
- 分块列表（使用 `Pagination` 分页）
- 分块内容展示
- 假设性问题标签展示

### 5.6 优化 `MemberView.vue`

- 成员列表表格（角色使用 `StatusTag` 或自定义 Tag）
- 邀请成员对话框（邮箱、角色选择、有效期）
- 邀请链接复制功能
- 角色修改
- 移除成员确认
- 离开空间功能

### 5.7 重写 `SearchView.vue`

- **先选择知识库**，再进行搜索
- 搜索模式从后端获取可用模式列表
- 高级设置面板：
  - 权重配置（向量权重 + BM25 权重，总和 = 1 的联动校验）
  - Rerank 配置（启用开关、top_k、模型选择）
  - LLM 回答配置（启用开关、模型、温度、top_p）
  - 查询改写配置（策略选择、参数配置）
  - 分数阈值、缓存开关
- 结果卡片展示：内容高亮、来源文档、分数、文件信息
- LLM 回答单独展示区域
- 搜索耗时和缓存状态提示
- 使用 `EmptyState` 组件

### 5.8 验收标准

- [ ] 空间完整 CRUD 流程
- [ ] 知识库创建时可配置完整切分/解析/向量化/问题生成参数
- [ ] 文档上传→触发解析→查看分块完整流程
- [ ] 搜索功能正常，高级参数生效
- [ ] 成员邀请→加入→角色变更完整流程
- [ ] 所有列表页分页正常
- [ ] 所有状态字段使用 Tag 组件展示

---

## 阶段 6：AI 对话模块（预计 3-4 小时）

> 目标：完善聊天界面，修复 SSE 流式问题，添加会话管理。

### 6.1 重写 `ChatView.vue`

**左侧边栏**：
- 会话列表（从 `/qa/sessions` 获取，带分页/无限滚动）
- 新建会话按钮
- 会话项：预览文本 + 删除按钮 + 设置按钮
- 会话搜索（可选）

**主聊天区**：
- 消息气泡列表（用户/AI 区分样式）
- AI 消息 Markdown 渲染（代码高亮）
- **SSE 流式输出**：逐字追加显示，带光标动画
- 自动滚动到底部
- 空状态欢迎界面

**输入区域**：
- 多行文本输入框
- 发送按钮（Enter 发送，Shift+Enter 换行）
- 流式/非流式切换开关
- 模型选择下拉框（从 `/ai-chat/models` 获取）
- 高级参数折叠面板（temperature、top_p、max_tokens、system_prompt）

**会话配置对话框**：
- 压缩启用开关
- 压缩策略选择（summary/sliding_window/keep_recent/truncate）
- 阈值配置（trigger threshold、target tokens）
- 保留最近消息数
- 自定义摘要提示词

**关键修复**：
- SSE 流添加 AbortController，支持取消
- SSE error 事件正确显示给用户
- 组件卸载时取消进行中的流
- 新会话的首条消息发送后，从响应中获取 `session_id` 并更新会话列表

### 6.2 验收标准

- [ ] 能正常发送消息并收到 AI 回复
- [ ] 流式输出逐字显示，可中途取消
- [ ] 会话列表正确展示，可切换/删除
- [ ] 会话配置可创建/查看/删除
- [ ] 模型选择和高级参数生效
- [ ] 组件卸载时无内存泄漏

---

## 阶段 7：深度研究模块（预计 2-3 小时）

> 目标：完善研究发起、进度展示、报告查看功能。

### 7.1 重写 `ResearchView.vue`

**研究发起表单**：
- 知识空间选择（必选）
- 研究查询输入
- 研究模式选择（quick/standard/deep，显示耗时预估）
- 搜索来源选择（internal/external/hybrid）
- 高级设置折叠面板：
  - 内部检索配置（知识库选择、检索模式、top_k、向量/BM25 权重、Rerank 配置、查询改写配置）
  - 外部搜索配置（服务商选择、最大结果数、搜索深度、时间范围）
  - LLM 配置（模型选择、温度、top_p、max_tokens）

**研究进度展示**：
- 进度条（百分比）
- 当前步骤描述
- 阶段指示（分析中→检索中→生成报告中）
- 已完成/总任务数
- **取消按钮**（真正中断 SSE 流）

**研究报告展示**：
- Markdown 渲染（代码高亮、目录导航）
- 复制报告内容
- 搜索摘要（内部/外部检索次数、关键来源）
- 统计信息（耗时、检索次数、结果数、报告字数、来源数）

### 7.2 优化 `ResearchHistoryView.vue`

- 历史记录表格（状态筛选、分页）
- 状态使用 `StatusTag` 组件
- 报告详情对话框（Markdown 渲染）
- 删除确认（运行中的研究提示不可删除）
- 研究任务列表展示
- 搜索结果来源列表

### 7.3 验收标准

- [ ] 能正常发起深度研究（快速/标准/深度三种模式）
- [ ] SSE 流式进度实时展示
- [ ] 研究报告 Markdown 渲染正确
- [ ] 可取消进行中的研究
- [ ] 历史记录完整展示，可查看/删除
- [ ] 高级参数（内部/外部搜索配置）正确传递给后端

---

## 阶段 8：通用组件与样式统一（预计 2 小时）

> 目标：统一组件使用，消除重复代码。

### 8.1 确保通用组件被实际使用

所有列表页使用：
- `Pagination.vue` — 分页
- `SearchBar.vue` — 搜索
- `StatusTag.vue` — 状态标签
- `EmptyState.vue` — 空状态
- `LoadingOverlay.vue` — 加载遮罩
- `ConfirmDialog.vue` — 确认弹窗

### 8.2 补充缺失的通用组件

- `MarkdownRenderer.vue` — 统一的 Markdown 渲染组件（chat + research 共用）
- `SSEStreamText.vue` — 流式文本展示组件（带光标动画）
- `ModelSelect.vue` — 模型选择下拉框（从可用模型列表获取选项）

### 8.3 样式统一

- 统一使用 Element Plus CSS 变量覆盖
- 确保所有页面一致的间距、圆角、阴影风格
- 响应式布局基础适配

### 8.4 验收标准

- [ ] 所有列表页使用 `Pagination` 组件
- [ ] 所有搜索使用 `SearchBar` 组件
- [ ] 所有状态字段使用 `StatusTag` 组件
- [ ] Chat 和 Research 共用 `MarkdownRenderer` 组件
- [ ] 无重复的 Markdown 渲染逻辑

---

## 阶段 9：测试与优化（预计 2-3 小时）

> 目标：核心逻辑有测试覆盖，性能和体验优化。

### 9.1 单元测试

- API 层测试（mock axios，验证请求参数和 URL）
- Store 测试（验证 actions 和状态变更）
- 工具函数测试（format、storage、markdown）

### 9.2 性能优化

- 路由懒加载（已有，验证）
- 大列表虚拟滚动（文档列表、消息列表）
- Markdown 渲染防抖
- 图片/资源按需加载

### 9.3 用户体验优化

- 所有操作添加 loading 状态
- 错误提示友好化
- 表单输入记忆（高级设置折叠面板状态）
- 文档处理状态轮询（processing → completed）
- 键盘快捷键（搜索 Ctrl+K，新建 Ctrl+N）

### 9.4 验收标准

- [ ] 核心模块有单元测试
- [ ] `npm run test:unit` 通过
- [ ] `npm run lint` 通过
- [ ] `npm run type-check` 通过
- [ ] `npm run build` 构建成功

---

## 开发顺序总结

```
阶段 0: 基础设施 ──────→ 可联调后端
阶段 1: API 层重建 ────→ 所有接口可用
阶段 2: Store 重构 ────→ 状态管理可靠
阶段 3: 布局路由 ──────→ 应用骨架完整
阶段 4: 用户管理 ──────→ 认证+用户+模型配置
阶段 5: 知识空间 ──────→ 核心 CRUD 模块
阶段 6: AI 对话 ───────→ 聊天功能完整
阶段 7: 深度研究 ──────→ 研究功能完整
阶段 8: 组件样式 ──────→ 代码质量统一
阶段 9: 测试优化 ──────→ 可交付
```

**总计预估：20-28 小时**

---

## 技术决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| SSE 流式实现 | 原生 `fetch` + `ReadableStream` | POST 请求不支持 EventSource |
| Token 刷新 | 请求拦截器自动刷新 + 请求队列 | 用户体验优先，避免频繁登出 |
| 状态管理 | Pinia Composition API | 项目已使用，保持一致 |
| UI 组件库 | Element Plus | 项目已使用，保持一致 |
| Markdown 渲染 | `marked` + `highlight.js` | 项目已使用，保持一致 |
| 文件结构 | 按功能模块划分（api/stores/views/components） | 现有结构合理，保持不变 |
