# 全项目逻辑审查报告

> 审查时间：2026-05-09
> 审查范围：src/features/ 下全部 7 个业务模块
> 审查方法：数据模型追踪 → API 接口逻辑 → 服务层链路 → Repository 层 → 跨模块依赖

---

## 统计汇总

| 模块 | 严重 | 警告 | 建议 |
|------|------|------|------|
| agent | 8 | 10 | 8 |
| knowledge_space | 5 | 9 | 7 |
| qa | 6 | 8 | 7 |
| deep_research | 5 | 8 | 8 |
| evaluation | 7 | 10 | 8 |
| skill | 6 | 9 | 7 |
| user | 4 | 8 | 8 |
| **合计** | **41** | **62** | **53** |

---

## 修复优先级建议

### 立即修复（严重问题）

#### Agent 模块

- [ ] **A-1** `api/exception_handlers.py:14` — `STATUS_MAP` 中 key 是 `CONVERSATION_NOT_FOUND`，但 `SessionNotFoundError` 的 code 是 `SESSION_NOT_FOUND`，导致会话不存在返回 500 而非 404
- [ ] **A-2** `api/routes.py:331-356` — `/tools` 和 `/tools/{tool_name}` 无需认证即可访问，暴露系统工具信息
- [ ] **A-3** `services/chat_service.py:62-122` — SSE 流式对话中多个 DB 操作无事务保护
- [ ] **A-4** `services/chat_service.py:326-354` — `_handle_done` 先 commit 再做内存巩固，巩固失败时 session 状态不确定
- [ ] **A-5** `services/agent_service.py:106-111` — 删除 Agent 是硬删除，关联的 sessions/messages/memories 未级联清理
- [ ] **A-6** `repository/agent_repository.py:45-50` — `list_by_user` 返回系统级 Agent（user_id IS NULL），暴露系统提示词
- [ ] **A-7** `tools/builtins/knowledge_search.py:105-202` — 知识库搜索工具未校验用户对 space_id 的访问权限
- [ ] **A-8** `startup.py:63-87` — 系统级 MCP 服务器启动时 DB 操作可能缺少 commit

#### Knowledge Space 模块

- [ ] **KS-1** `document_routes.py:74-77` — `DocumentSizeExceededError` 构造参数名不匹配（`size_mb` vs `size`），导致 TypeError
- [ ] **KS-2** `document_routes.py:168-177` — 多文件批量上传时单个文件类型错误中断整个批量上传
- [ ] **KS-3** `dependencies.py:297-298` — `validate_space_admin/editor` 重复查询用户未使用缓存
- [ ] **KS-4** `space_service.py:143-160` — 嵌套事务外执行 Embedding 配置回填，失败时空间配置不完整
- [ ] **KS-5** `member_routes.py:52` — 获取成员列表接口缺少 `validate_space_member` 依赖注入

#### QA 模块

- [ ] **Q-1** `ai_chat_routes.py:137-158` — `get_chat_history` 构造裸 dict 而非 `ChatMessageResponse`，`created_at` 为 None 时 500
- [ ] **Q-2** `ai_chat_service.py:185,361` — 双重提交事务问题，LLM 调用失败时残留数据风险
- [ ] **Q-3** `session_config_routes.py:67` — 从 `repo.session` 隐式获取 session，耦合脆弱
- [ ] **Q-4** `qa_service.py:254-256` — `commit()` 无异常处理，失败时无回滚
- [ ] **Q-5** `qa_service.py:53` — `_cleanup_user_message` 中 session 关闭后操作静默失败，产生孤立数据
- [ ] **Q-6** `session_config_routes.py:41-93` — session_id 格式校验与其他路由不一致

#### Deep Research 模块

- [ ] **DR-1** `deep_research_service.py:196-209` — `search_service` 延迟初始化，ES 未配置时在检索阶段才报错
- [ ] **DR-2** `deep_research_service.py:857-880` — 研究失败恢复依赖新 session，DB 连接中断时产生僵尸记录
- [ ] **DR-3** `deep_research_service.py:471-477` — 流式路径 `total_tasks` 使用配置值而非实际任务数
- [ ] **DR-4** `deep_research_service.py:514` — 流式路径 `_is_sufficient_results` 使用全局累积结果判断，导致后续任务检索被跳过
- [ ] **DR-5** 同一 POST/GET 路径的 HEAD 请求行为不确定（影响较小）

#### Evaluation 模块

- [ ] **E-1** `evaluation_service.py:436` — `asyncio.as_completed` 进度计数不准确
- [ ] **E-2** `evaluation_service.py:327-384` — 后台任务中 5 个并发协程共享同一个 SQLAlchemy session
- [ ] **E-3** `evaluation_service.py:216-234` — 取消操作与后台任务执行之间存在竞态窗口
- [ ] **E-4** `evaluation_service.py:448-452` — 取消返回时 `get_db_session` 自动 commit 可能持久化中间状态
- [ ] **E-5** `evaluation_service.py:275` — 人工评分计算中 `human_score` 可能为 None 导致 TypeError
- [ ] **E-6** `evaluation_service.py:183-189` — 创建任务返回 PENDING 但后台可能已改变状态（设计局限）
- [ ] **E-7** `evaluation_service.py:118-127` — 更新测试集名称不影响正在运行的任务

#### Skill 模块

- [ ] **S-1** `api/routes.py:322-350` — `GET /admin/settings` 和 `GET /admin/reviews` 被 `GET /{skill_id}` 路由拦截，管理员接口完全不可用
- [ ] **S-2** `services/skill_marketplace_service.py:217-235` — `publish_skill` 和 `unpublish_skill` 缺少 `self.db.commit()`，数据不持久化
- [ ] **S-3** `services/skill_marketplace_service.py:239-281` — `install_skill` 未校验 Agent 归属
- [ ] **S-4** `services/skill_marketplace_service.py:283-307` — `uninstall_skill` 卸载时未清理 `allowed_tools` 引用
- [ ] **S-5** `services/skill_marketplace_service.py:142-148` — 更新版本时不校验新 ZIP 中 name 与现有记录是否一致
- [ ] **S-6** `api/routes.py:142-150` — `get_skill` 和 `download_skill` 无可见性检查，可越权查看/下载私有技能

#### User 模块

- [ ] **U-1** `services/auth_service.py:152-153` — Refresh Token 缺少 `iat` 字段
- [ ] **U-2** `repository/user_repository.py:148-149` — 缓存穿透导致软删除用户可被查到
- [ ] **U-3** `services/model_config_service.py:45-48` — 模块级 `_client_cache` 多实例不共享
- [ ] **U-4** `services/model_config_service.py:64-84` — `_cleanup_expired_cache` 潜在锁竞争

---

## 各模块详细报告

### Agent 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| A-W1 | `chat_service.py:216-237` | `_collect_skill_fragments` 解析 skill_id 逻辑错误，`split("_", 2)` 无法正确解析 `skill__{id}_{name}` | 改为 `skill_ref.split("__", 1)` |
| A-W2 | `core/engine.py:58-117` | ReAct 循环空响应时直接 break，Agent 返回空回复 | 增加 empty response 检测 |
| A-W3 | `core/engine.py:61-68` | `generate_with_tools` 可能未在所有子类实现 | 确认或增加降级实现 |
| A-W4 | `repository/agent_repository.py:139-150` | Session 软删除查询时未统一过滤 | 在 repo 层增加 status 过滤 |
| A-W5 | `services/agent_service.py:199-209` | `update_session_stats` 并发竞态 | 使用 SQL 原子更新 |
| A-W6 | `core/memory/short_term.py:65-66` | `build_context` limit=200 硬编码，与 tool_call 查询不一致 | 统一 limit |
| A-W7 | `api/routes.py:173-179` | `get_session` 手动 `model_validate` 与 response_model 重复 | 直接 return ORM 对象 |
| A-W8 | `core/memory/long_term.py:89-98` | `access_count` 返回值比实际少 1 | 先 increment 再读取 |
| A-W9 | `models/__init__.py:1-13` | `AgentMemory` 未导出 | 添加到 `__all__` |
| A-W10 | `mcp/client.py:202-207` | MCP 服务器名称不唯一，可能路由错误 | 增加唯一性约束 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| A-S1 | `models/message.py:10` | AgentMessage/AgentToolCall 改为继承 BaseModel |
| A-S2 | `core/engine.py:34-117` | ReAct 循环改为流式产出 |
| A-S3 | `mcp_server_service.py:126-147` | test_connection 使用 uuid 替代固定 ID |
| A-S4 | `api/routes.py:317-327` | test-connection 路由移到动态路径之前 |
| A-S5 | `core/memory/working.py` | WorkingMemory 增加最大容量限制 |
| A-S6 | `repository/agent_repository.py:73-77` | Agent 统一使用软删除 |
| A-S7 | `tools/builtins/knowledge_search.py:156-172` | 后续增强跨知识库搜索 |
| A-S8 | `core/memory/compress.py:289-309` | 压缩时跳过 system 消息 |

---

### Knowledge Space 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| KS-W1 | 多个模型 | 自定义 `created_at`/`updated_at` 覆盖 BaseModel 字段 | 统一策略 |
| KS-W2 | `document_service.py:64-65` | `_processing_tasks` 模块级全局字典，多 worker 不共享 | 改用 Redis |
| KS-W3 | `member_service.py:91-98` | 被暂停管理员收到的错误信息不明确 | 增加状态检查 |
| KS-W4 | `space_service.py:549-566` | 统计未排除 ARCHIVED 状态知识库 | 添加状态过滤 |
| KS-W5 | `search_service.py:604-609` | 权重校验对用户不友好 | 自动计算互补权重 |
| KS-W6 | `document_routes.py:237-241` | 文档 status 参数为 str 但 DocumentStatus 是 IntEnum | 改为 int 类型 |
| KS-W7 | `knowledge_base_service.py:131-159` | 创建知识库时内部实例化 ModelConfigService | 通过构造函数注入 |
| KS-W8 | `space_repository.py:129-156` | 缓存反序列化后枚举字段为 int | 手动转换枚举 |
| KS-W9 | `dependencies.py:51-77` | 每次设置 contextvars 都创建新字典 | 原地修改替代 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| KS-S1 | `document_service.py:536` | 中文文档 token 估算不准确 |
| KS-S2 | `member_repository.py:231-237` | 动态属性改为专用数据类 |
| KS-S3 | `search_service.py:496-504` | merge_mode="rrf" 实为平均分，非标准 RRF |
| KS-S4 | `space_audit_log.py:61-72` | set_context 调用语义不清 |
| KS-S5 | `knowledge_base_routes.py:79-80` | 路由层穿透 Service 直接调用 Repository |
| KS-S6 | `document_routes.py:108-211` | 单/多文件上传逻辑混合，拆分函数 |
| KS-S7 | `space_service.py:242-346` | 空间删除逻辑在两处重复，抽取共享方法 |

---

### QA 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| Q-W1 | `qa_routes.py:52-64` | `get_session_messages` 缺少所有者校验，返回空列表而非 404 | 增加存在性检查 |
| Q-W2 | `ai_chat_routes.py:161-177` | `clear_chat_history` 用 DELETE + Query 参数，非 RESTful | 改为路径参数 |
| Q-W3 | `qa_service.py:290-331` | `_get_session_config_with_cache` 隐式创建默认配置 | 区分获取和确保 |
| Q-W4 | `qa_service.py:469` | `enable_compression=None` vs `False` 语义混淆 | 添加注释 |
| Q-W5 | `ai_chat_service.py:108-119` | SSE generate 函数未捕获初始异常 | 添加顶层 try/except |
| Q-W6 | `question_answer_repository.py:207-237` | update 方法 TOCTOU 竞态 | SQL 层校验 |
| Q-W7 | `qa_service.py:322` | `ensure_session_config` 无并发保护 | 捕获 IntegrityError |
| Q-W8 | `session_summary_repository.py:107-108` | 摘要版本号并发竞态 | 使用 max+1 子查询 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| Q-S1 | `ai_chat_routes.py:186-188` | health 端点移到无认证路由组 |
| Q-S2 | `qa_cache_service.py:350-358` | `get_cache_stats` 接口不一致 |
| Q-S3 | `qa_service.py:51` | TokenCounter 线程安全性确认 |
| Q-S4 | `question_answer_repository.py:80-99` | 拆分 `get_by_session` 为两个方法 |
| Q-S5 | `ai_chat_service.py:246-262` | 异常处理增加 `except QAError: raise` |
| Q-S6 | `qa_service.py:56-96` | 使用 `model_validate` 替代手动赋值 |
| Q-S7 | `session_config_routes.py:67-70` | 归属校验用 LIMIT 1 替代全量加载 |

---

### Deep Research 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| DR-W1 | `deep_research_service.py:513` | 全局去重按标题/URL 过于激进 | 使用复合键去重 |
| DR-W2 | `deep_research_service.py:74` | `_sanitize_search_field` 空字符串无操作 | 移除空字符串 |
| DR-W3 | 三个外部搜索服务 | 每次搜索创建新 HTTP 连接，无连接池上限 | 配置 limits |
| DR-W4 | `deep_research_service.py:106-129` | `retrieval_top_k`/`retrieval_weight` 未使用 | 删除死代码 |
| DR-W5 | `research_repository.py:120-136` | `get_by_session_id` 不过滤 space_id | 增加 space_id 参数 |
| DR-W6 | `research_schema.py:80-91` | 非 hybrid 模式下权重被忽略但不报错 | 添加校验提示 |
| DR-W7 | `deep_research_service.py:554-559` | 空 chunk 也被发送 | 过滤空 chunk |
| DR-W8 | `duckduckgo_service.py:108-116` | URL 提取可能失败 | 增加备选提取 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| DR-S1 | `research_session.py:179-186` | 统一时间存储方式 |
| DR-S2 | `deep_research_service.py:366-372` | 按需初始化外部搜索服务 |
| DR-S3 | `deep_research_service.py:882-977` | 缓存 KnowledgeBaseRepository |
| DR-S4 | `deep_research_service.py:530-528` | search_results 使用 list() 副本 |
| DR-S5 | `research_schema.py:74-76` | 自动计算互补权重 |
| DR-S6 | `deep_research_service.py:1096-1202` | 流式/非流式报告 prompt 提取为共享方法 |
| DR-S7 | `deep_research_service.py:58-60` | 充分性阈值与研究模式关联 |
| DR-S8 | `research_repository.py:206-241` | JSON 字段添加 flag_modified |

---

### Evaluation 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| E-W1 | `evaluation_service.py:331-337` | task 不存在时直接 return，可能留下 PENDING 僵尸 | 标记为 FAILED |
| E-W2 | `evaluation_service.py:362-363` | LLM 和 Embedding 都为 None 时不应阻止纯检索评估 | 细化检查逻辑 |
| E-W3 | `evaluation_service.py:469-474` | 评分返回类型混合（int vs tuple） | 统一返回 int |
| E-W4 | `routes.py:206-207` | 删除测试集未校验创建者 | 增加创建者校验 |
| E-W5 | `evaluation_service.py:492-493` | 启用 embedding 指标但无客户端时字段缺失 | 配置可行性校验 |
| E-W6 | `evaluation_service.py:635-650` | `task.test_set` lazy=noload 可能导致 AttributeError | None 检查 |
| E-W7 | `evaluation_repository.py:219-223` | update_status 每次带 selectinload | 轻量级查询方法 |
| E-W8 | `routes.py:440-441` | 已完成任务的测试集被删除后无法导出 | 使用 get_task 替代 |
| E-W9 | `evaluation_service.py:158-160` | 删除测试集时逐个删除 MinIO 文件可能慢 | 批量删除 |
| E-W10 | `evaluation_service.py:530-539` | 异常处理中 session 断开时无法更新状态 | 使用新 session |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| E-S1 | `evaluation_service.py:49` | `_running_tasks` 多进程不共享 |
| E-S2 | `evaluation_service.py:399` | 并发数提取为配置项 |
| E-S3 | `evaluation_service.py:258-282` | 人工评分增量更新 |
| E-S4 | `evaluation_repository.py:259-277` | 确认 created_at 时区一致性 |
| E-S5 | `evaluation_service.py:714-731` | 启动时数据库就绪检查 |
| E-S6 | `routes.py:445` | 导出空结果定义专用 Schema |
| E-S7 | `evaluation_service.py:80-103` | commit 移到 MinIO 上传之后 |
| E-S8 | `evaluation_service.py:175-176` | 配置验证逻辑提取为独立方法 |

---

### Skill 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| S-W1 | `skill_parser.py:200-290` | ZIP 解压缺少路径穿越检查 | 添加 `..` 校验 |
| S-W2 | `skill_parser.py:217-220` | ZIP 包无总大小和文件数量限制 | 增加上限 |
| S-W3 | `skill_marketplace_service.py:112-128` | MinIO 上传在 DB commit 之前，失败产生孤立文件 | 调换顺序 |
| S-W4 | `api/routes.py:170-185` | `download_skill` 无可见性检查 | 增加校验 |
| S-W5 | `skill_marketplace_service.py:384-395` | approve/reject 不校验当前 review_status | 增加前置校验 |
| S-W6 | `skill_repository.py:95-110` | `json_contains` 是 MySQL 特有函数 | 确认数据库兼容性 |
| S-W7 | `api/routes.py:128-133` | `list_installed` 不校验 Agent 归属 | 增加 agent.user_id 校验 |
| S-W8 | `skill_marketplace_service.py:354-360` | `delete_review` 未校验评价归属（SQL 层已保护） | 风险较低 |
| S-W9 | `api/dependencies.py:47` | lambda 闭包捕获写法不够清晰 | 改为显式依赖函数 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| S-S1 | `skill_marketplace_service.py:364-372` | 软删除前检查安装记录 |
| S-S2 | `schemas/skill_schema.py:28-36` | 移除未使用的 `SkillMarketplaceQuery` |
| S-S3 | `skill_marketplace_service.py:416-444` | download_skill 优先从 MinIO 下载原始文件 |
| S-S4 | `skill_checker.py:109` | findall 改为 search |
| S-S5 | `skill_marketplace_service.py:58-60` | 路由层限制上传文件大小 |
| S-S6 | `api/routes.py:402-420` | `author_name` 始终为 None，JOIN users 表或移除 |
| S-S7 | `skill_parser.py:218` | ZipFile 改为 with 语句 |

---

### User 模块

#### 警告

| # | 文件:行号 | 问题 | 建议 |
|---|----------|------|------|
| U-W1 | `user_repository.py:249-253` | `update_user` 用 Core update 不触发 ORM onupdate | 手动添加 updated_at |
| U-W2 | `auth_service.py:589-593` | Redis 不可用时所有请求被拒绝 | 增加降级策略 |
| U-W3 | `user_routes.py:90-92` | IP 获取用 X-Forwarded-For 最后一个，可能不准 | 使用 X-Real-IP |
| U-W4 | `model_config_service.py:426-453` | `get_llm_client_by_model` 调用两次 get_credentials | 移除多余查询 |
| U-W5 | `auth_service.py:106` | JWT 用 now_china() 而非 UTC | 使用 datetime.now(utc) |
| U-W6 | `model_config_repository.py:289-296` | update 方法无字段白名单 | 过滤 model_type |
| U-W7 | `api/startup.py:56-63` | 管理员密码强度校验失败被吞掉 | 明确报错退出 |
| U-W8 | `user_repository.py:369-398` | soft_delete 用 ORM 方式与 update_user Core 方式不一致 | 统一风格 |

#### 建议

| # | 文件:行号 | 建议 |
|---|----------|------|
| U-S1 | `api/auth.py:28-102` | `get_current_user` 返回强类型对象 |
| U-S2 | `services/user_service.py:34-58` | create_user status 默认值用 UserStatus.ACTIVE |
| U-S3 | `user_repository.py:119-166` | 缓存逻辑抽取为装饰器 |
| U-S4 | `auth_service.py:432-451` | 登出时同时撤销 access + refresh token |
| U-S5 | `schemas/user_schema.py:142-146` | 单独修改密码时校验不包含用户名 |
| U-S6 | `model_config_service.py:617-721` | 维度检测改为后台异步或设超时 |
| U-S7 | `api/dependencies.py:8-10` | 考虑 FastAPI 依赖覆盖机制 |
| U-S8 | `models/user.py:64-71` | phone 唯一约束对 NULL 的行为添加注释 |

---

## 跨模块依赖关系

```
user ──────────────────────────────────────────────────┐
  │ get_current_user, require_admin                     │
  │ ModelConfigService                                  │
  ▼                                                     │
knowledge_space ◄──── evaluation (搜索、权限)           │
  │     ◄──── deep_research (检索)                      │
  │     ◄──── agent (知识库搜索工具)                     │
  ▼                                                     │
qa ◄───── agent (对话能力)                              │
  │                                                     │
deep_research ◄── skill (无直接依赖)                    │
  │                                                     │
skill ◄── agent (技能安装到 Agent)                      │
  │                                                     │
evaluation ◄── knowledge_space (搜索、MinIO)            │
  │                                                     │
  └─────────────────────────────────────────────────────┘
```
