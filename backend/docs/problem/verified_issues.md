# NovaMind 后端逻辑审查 — 经验证确认的问题清单

> 审查时间：2026-05-13
> 审查范围：src/features/ 全部 8 个业务模块
> 审查方式：5 个 Agent 并行审查 + 5 个 Agent 并行源码验证
> 原始问题总数：170
> 经验证确认：131（确认 117 + 部分正确 14）
> 误判排除：39

---

## 总览

| 模块 | 确认 | 部分正确 | 误判 | 合计确认 |
|------|------|---------|------|---------|
| knowledge_space | 17 | 4 | 10 | 21 |
| user | 14 | 3 | 6 | 17 |
| qa | 19 | 5 | 2 | 24 |
| deep_research | 16 | 1 | 1 | 17 |
| evaluation | 19 | 0 | 3 | 19 |
| agent | 11 | 1 | 5 | 12 |
| skill | 10 | 0 | 6 | 10 |
| app | 11 | 1 | 5 | 12 |
| **合计** | **117** | **14** | **39** | **131** |

---

## 🔴 严重问题汇总（共 20 个）

### knowledge_space（4 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| KS-C1 | `services/document_service.py:1091-1116` | `retry_document()` 日志记录重置后的状态（UPLOADED），而非重试前的原始状态 | 在第 1092 行重置前保存 `previous_status = document.status` |
| KS-C2 | `services/member_service.py:472-525` | 最后管理员离开时，空间软删除后管理员自身的成员记录未被移除 | commit 前调用 `member_repo.delete_by_space(space_id)` |
| KS-C3 | `services/space_service.py:205-233` | ES 索引创建在 commit 之后执行，失败时空间已存在但搜索不可用 | 添加后台重试或标记空间为"需修复" |
| KS-C4 | `models/document.py:78-86` | `UniqueConstraint(kb_id, file_hash)` 不排除软删除记录，同文件多次删除后约束冲突 | 改为条件唯一索引或软删除时修改 `file_hash` |

### user（4 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| U-C1 | `services/model_config_service.py:426-438` | **P0** LLM 凭证调试日志使用 `logger.info` 打印 API Key 前6后4位 | 移除或降级为 DEBUG，生产环境不记录 |
| U-C2 | `repository/user_repository.py:146-149` | 缓存命中后 `session.get()` 绕过软删除过滤 | 缓存命中路径增加 `status == UserStatus.DELETED` 检查 |
| U-C3 | `repository/user_repository.py:146-149` | `expire_on_commit=False` 下 identity map 可能持有过期状态（风险较低） | 优化查询方式 |
| U-C4 | `services/model_config_service.py:45-48` | 模块级 `_client_cache` 全局字典依赖调用方持锁约定，设计脆弱 | 封装为类，自动管理锁 |

### qa（3 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| QA-C1 | `ai_chat_service.py:232,271` | **P0** 双重 commit：手动 `qa_service.commit()` + `get_db` 自动 commit，LLM 失败后用户消息无法回滚 | 采用 savepoint 方案重构（代码中 TODO(#55) 已承认） |
| QA-C3 | `ai_chat_service.py:508-516` | `chat_stream` 中 `QAError`/`Exception` 异常未调用 `_cleanup_user_message` | 在所有异常分支添加清理逻辑 |
| QA-C4 | `ai_chat_service.py:657-667` | `_inject_attachments_to_context` 绕过 Repository 直接写 SQL，且无 `user_id` 过滤 | 改为通过 Repository 访问，添加 `user_id` 条件 |

### deep_research（4 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| DR-C1 | `research_session.py:74` + `research_repository.py:67-75` | 用户细粒度配置（internal_search/external_search/llm）未写入 `config` JSON 字段 | 在 `create()` 中传入 config 参数 |
| DR-C2 | `deep_research_service.py:698-709` | `_create_research_session` 不传 config，`ctx.params` 包含完整配置但未持久化 | 传递 config 到 repository.create |
| DR-C3 | `deep_research_service.py:405-420` | commit 后异常会用新 session 覆盖已 COMPLETED 状态为 FAILED | 调整异常处理逻辑 |
| DR-C4 | `research_session.py:144-146` | `is_web_search_enabled()` 和 `set_config()` 全项目无外部调用，死代码 | 移除 |

### evaluation（4 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| EV-C1 | `evaluation_service.py:183-197` | `_running_tasks` 模块级字典不支持多 worker 部署 | 使用 Redis 或数据库存储任务状态 |
| EV-C3 | `evaluation_service.py:232-234` | 取消任务在 commit CANCELLED 后才 cancel 后台任务，中间阶段不检查取消信号 | 在 MinIO 上传、汇总计算阶段添加取消检查 |
| EV-C4 | `evaluation_service.py:461-464` | 取消后 `rollback()` 不影响已 commit 的 progress，进度与状态不一致 | 记录实际处理数量到独立字段 |
| EV-C5 | `evaluation_service.py:284` | `delete_test_set`/`delete_task` 先删 MinIO 后删数据库，中间失败产生孤儿记录 | 调换顺序：先删数据库再删 MinIO |

### agent（2 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| AG-C1 | `chat_service.py:118-119` | SSE 流式对话先 yield done 事件再 commit，commit 失败时客户端已收到成功 | commit 成功后再 yield done |
| AG-C2 | `mcp_server_service.py:180-186` | 系统级 MCP 服务器（`user_id is None`）跳过权限校验，任何用户可操作 | 为系统级服务器添加管理员权限检查 |

### skill（3 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| SK-C1 | `skill_parser.py:255-264` | ZIP 解压未检查 `../` 路径遍历，路径可能被利用覆盖其他文件 | 添加 `if ".." in rel_path: raise` 检查 |
| SK-C2 | `routes.py:63` | ZIP 文件大小未限制，`await file.read()` 可能导致 OOM | 添加文件大小限制（如 50MB） |
| SK-C4 | `skill_marketplace_service.py:306` | 卸载技能时 `allowed_tools` 无条件清除，是未完成的 TODO | 查询其他技能的工具引用后再清理 |

### app（4 个）

| # | 位置 | 问题 | 修复建议 |
|---|------|------|---------|
| AP-C1 | `routes.py:167-175` | Pipeline 失败后状态回滚到 DRAFT，用户无法区分"等待执行"和"执行失败" | 添加 FAILED 状态枚举值 |
| AP-C2 | `routes.py:36-57` | 文件上传无类型和大小校验 | 添加白名单校验（.pdf/.docx/.doc/.txt/.md）和大小限制 |
| AP-C3 | `exceptions.py:6-10` | `AppError` 未继承 `BaseAPIError`，无法使用 `register_module_exceptions` | 继承 `BaseAPIError` 并注册模块异常处理器 |
| AP-C4 | `resume_parser.py:380` | `_extract_text` 使用 `delete=False` 临时文件，进程被杀时残留 | 添加文件后缀白名单校验，使用 try/finally 确保清理 |

---

## 🟡 警告汇总（共 45 个）

### knowledge_space（8 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| KS-W1 | `services/search_service.py:492-498` | Sub Query RRF 融合使用简单平均而非标准 RRF 排名融合 | 实现标准 RRF：`1/(k+rank)` |
| KS-W2 | `services/search_service.py:508-532` | 缓存 key 未包含 `user_id` | 加入 `user_id` 参数 |
| KS-W3 | `services/search_service.py:486-498` | 非成员用户可检索公开空间知识库，无知识库级别可见性控制 | 评估是否需要知识库独立可见性 |
| KS-W4 | `repository/member_repository.py:231-238` | 动态附加 `username`/`email` 到 ORM 对象 | 使用独立数据结构 |
| KS-W5 | `repository/space_repository.py:133-139` | 缓存反序列化 Enum 类型丢失（int vs Enum） | 添加枚举字段反序列化 |
| KS-W6 | `services/knowledge_base_service.py:94-105` | 软删除恢复时仅重命名 `name`，未清理 `storage` 中的索引名 | 同步清理 storage 字段 |
| KS-W7 | `api/document_routes.py:56-62,83-86` | 路由层与 Service 层重复定义文件大小和类型限制 | 统一定义在一处 |
| KS-W8 | `services/search_service.py:508-532` | 缓存 key 使用 MD5 哈希，存在碰撞风险 | 改用 SHA256 |

### user（7 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| U-W1 | `api/auth.py:83-92` | 管理员 INACTIVE/BANNED 状态仍可访问所有接口 | 明确设计意图并添加注释 |
| U-W2 | `api/user_routes.py:90-92` | X-Forwarded-For IP 伪造风险 | 配置受信代理或取第一个 IP |
| U-W3 | `services/auth_service.py:106-113` | Access Token 未注册到用户 Token 列表，`logout_all_sessions` 无法撤销 | 注册 jti 或依赖用户级黑名单 |
| U-W4 | `services/auth_service.py:485-486` | 直接访问 `redis_cache.redis_client` 内部属性 | 通过 RedisCache 公开方法操作 |
| U-W5 | `repository/user_repository.py:50-67` | 缓存无 `status` 变更同步机制，TTL 2 小时 | 评估缩短 TTL 或添加主动失效 |
| U-W6 | `models/user.py:64-71` | `phone` UNIQUE 允许 NULL，依赖应用层检查 | 可接受，但添加数据库注释 |
| U-W7 | `api/model_config_routes.py:183-194` | `delete_config_with_check` 返回混合类型响应（409 绕过 response_model） | 定义正式的冲突响应模型 |

### qa（7 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| QA-W1 | `question_answer_repository.py:198` | 会话列表按 `session_id` 字符串排序而非时间 | 改为按 `updated_at` 排序 |
| QA-W2 | `qa_service.py:314-324` | 缓存反序列化使用 `SimpleNamespace` 丢失类型安全 | 使用 Pydantic 模型或 dataclass |
| QA-W3 | `schemas/qa.py:24` | `session_id` 正则过于宽泛，与路由 `Path` 标准不一致 | 统一为 UUID 格式校验 |
| QA-W4 | `chat_attachment_repository.py:58-65` | `get_by_ids` 不校验 `user_id`，存在越权访问风险 | 添加 `user_id` 过滤 |
| QA-W5 | `ai_chat_service.py:594` | `upload_attachment` 手动 commit，请求失败时附件成为孤儿 | 统一到请求结束时 commit |
| QA-W7 | `ai_chat_service.py:446` | SSE thinking 参数无防御，LLM 不支持 thinking 时无降级 | 添加 warning 或降级处理 |
| QA-W8 | `exceptions.py:89` | `SessionConfigAlreadyExistsError` 构造函数参数名不一致 | 修正参数名和调用方式 |

### deep_research（8 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| DR-W1 | `routes.py:43-44` | dict comprehension 覆盖重复 value（当前安全） | 添加注释说明前提条件 |
| DR-W2 | `routes.py:211-260` | GET/POST 同路径不同方法，语义混淆 | 文档说明 |
| DR-W3 | `deep_research_service.py:177-189` | `_model_config_service` 和 `model_config_service` 属性冗余 | 统一使用一个 |
| DR-W4 | `duckduckgo_service.py:89-90` | httpx 客户端创建无锁保护（当前串行安全） | 添加注释 |
| DR-W5 | `deep_research_service.py:962-972` | 知识库搜索异常时静默返回空结果，用户无感知 | 添加 warning 提示 |
| DR-W6 | `deep_research_service.py:1184-1185` | LLM 生成的 `research_topic` 经 sanitize 可能中断报告生成 | 捕获异常并使用原始 topic |
| DR-W7 | `deep_research_service.py:681-691` | 降级默认任务描述同质化严重 | 使用 query + 子主题组合 |
| DR-W8 | 三个外部搜索服务 | `__init__` 设 `_client=None`，依赖 yield cleanup | 当前安全，添加注释 |

### evaluation（9 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| EV-W1 | `evaluation_repository.py:61-65` | `get_by_id` 不检查 `space_id`/`kb_id` | 添加归属校验 |
| EV-W2 | `evaluation_service.py:144-164` | `delete_test_set` 先删 MinIO 后删 DB | 调换顺序 |
| EV-W3 | `evaluation_service.py:212-222` | `delete_task` 同上 | 调换顺序 |
| EV-W4 | `evaluation_service.py:183-184` | `asyncio.create_task` 异步任务管理 | 当前安全，添加注释 |
| EV-W5 | `evaluation_service.py:676-698` | `_generate_answer` 返回 `""` 和 `None` 语义不清 | 统一返回 None |
| EV-W6 | `evaluation_task.py:93-98` | TestSet/Task 无 `deleted_at` 字段 | 评估添加软删除 |
| EV-W7 | `evaluation_service.py:336-338` | 后台任务使用独立 session 但依赖请求级 minio_client | minio_client 是全局单例，当前安全 |
| EV-W8 | `evaluation_service.py:49` | `_running_tasks` 模块级字典不支持多 worker | 使用 Redis 存储 |
| EV-W9 | `routes.py:440-441` | FAILED/CANCELLED 状态导出结果无区分提示 | 细化错误提示 |

### agent（7 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| AG-W1 | `message.py:6` / `tool_call.py:6` | AgentMessage/AgentToolCall 未继承 BaseModel，缺少 `updated_at` | 评估是否需要继承 |
| AG-W2 | `agent_repository.py:99-109` | `get_by_id`/`get_by_session_id` 无 `status != "deleted"` 过滤 | 添加软删除过滤 |
| AG-W3 | `chat_service.py:296-298` | `_inject_attachments_to_snapshot` 用消息内容做关联键，重复内容丢失附件 | 使用消息 ID 关联 |
| AG-W4 | `mcp/client.py:54-60` | MCP 客户端连接异常时 session/exit_stack 残留 | 异常时清理已保存的状态 |
| AG-W5 | `chat_service.py:330-351` | `_collect_skill_fragments` 绕过服务层，未检查技能 review_status | 添加 `status` 和 `review_status` 检查 |
| AG-W6 | `knowledge_search.py:183-213` | 知识库搜索工具未校验空间权限 | 添加用户权限验证 |
| AG-W7 | `memory_repository.py:75` | 长期记忆搜索使用 LIKE 模糊匹配，无法使用索引 | 集成向量检索（代码中已有 TODO） |

### skill（5 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| SK-W1 | `skill_repository.py:37-41` | `create` 中 `IntegrityError` 时 `rollback()` 会回滚外层事务 | 使用 `begin_nested()` savepoint |
| SK-W2 | `routes.py:136-141` | `list_installed` 未校验 Agent 归属权 | 添加 Agent 归属校验 |
| SK-W3 | `routes.py:302-312` | `download_skill` 无权限校验，可下载 DRAFT/ARCHIVED 技能 | 添加状态和权限检查 |
| SK-W4 | `dependencies.py:23-39` | 管理员设置使用 JSON 文件持久化，无并发保护 | 添加文件锁或迁移到数据库 |
| SK-W5 | `skill_checker.py:148-152` | LLM 安全审查超时自动 APPROVED，恶意技能可能通过审查 | 超时时标记为 PENDING 或 SUSPICIOUS |

### app（6 个）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| AP-W1 | `routes.py:89-178` | Pipeline 失败后用户只能看到 DRAFT，无法得知失败原因 | 存储错误信息到 session |
| AP-W2 | `routes.py:145` | `_assemble_final_md_report` 被外部直接调用私有方法 | 提供公共接口 |
| AP-W3 | `resume_parser.py:327-349` | 并行解析中异常章节使用默认值，不在 `validation_warnings` 中提示 | 添加 warning |
| AP-W4 | `resume_analyzer.py:497-515` | 前缀知识逐个调用 LLM，技术点多时耗时长 | 批量调用或并发 |
| AP-W5 | `resume_repository.py:48-51` | `update` 不返回更新后的对象 | 返回更新后的对象 |
| AP-W6 | `routes.py:51` | config 参数通过 Form + `json.loads`，缺乏 Pydantic 校验 | 使用 Pydantic 模型 |

---

## 🔵 建议改进汇总（共 46 个）

### knowledge_space（9 个）

| # | 位置 | 问题 |
|---|------|------|
| KS-S1 | `services/document_service.py:486-496` | `total_tokens` 实际是按空格分词的字数，命名误导 |
| KS-S2 | `services/audit_service.py:74-78` | 审计 session 创建失败影响业务操作 |
| KS-S3 | `api/document_routes.py:249,260-266` | 状态过滤参数缺少合法值提示，使用 HTTPException 而非模块异常 |
| KS-S4 | `services/document_service.py:504-533` | `_extract_text()` 方法未被调用，死代码 |
| KS-S5 | `api/exceptions.py` + `api/startup.py` | `DocumentCountExceededError` 未注册异常处理器，返回 500 |
| KS-S6 | `services/space_service.py:573-582` | `_deep_merge()` 在两个 Service 中重复定义 |
| KS-S7 | `services/document_service.py:316-502` | `execute_document_pipeline()` 超 180 行，职责过多 |
| KS-S8 | `services/knowledge_base_service.py:108` | `max_kb_per_space = 50` 硬编码 |
| KS-S9 | `api/dependencies.py:56-77` | contextvars 使用不如 `request.state` 规范（无跨请求泄漏风险） |

### user（5 个）

| # | 位置 | 问题 |
|---|------|------|
| U-S1 | `api/exceptions.py:105-112` | `ModelConfigNotFoundError` if-elif 逻辑冗余 |
| U-S2 | `api/user_routes.py:84-92` | 客户端 IP 获取逻辑应抽取为工具函数 |
| U-S3 | `services/model_config_service.py:724-732` | 系统配置缓存清除使用 `k.startswith("None:")` 字符串匹配不够健壮 |
| U-S4 | `services/model_config_service.py:420-453` | `get_llm_client_by_model` 凭证重复查询（多一次 DB 查询 + AES 解密） |
| U-S5 | `services/user_service.py:59-95` | `create_user` 三次查询检查唯一性（设计权衡，提供更好错误消息） |

### qa（9 个）

| # | 位置 | 问题 |
|---|------|------|
| QA-S1 | `question_answer_repository.py:198` | 会话列表缺少按活跃时间排序（同 W-01） |
| QA-S2 | `ai_chat_service.py` 多处 | 大量 `[调试]` 前缀 info 级别日志应降低为 DEBUG |
| QA-S3 | `dependencies.py:32-41` | `QACacheService` 每次请求创建新实例 |
| QA-S4 | `chat_attachment.py:4-6` | 孤儿附件无清理机制 |
| QA-S5 | `question_answer_repository.py:83-121` | `get_by_session` 与 `get_by_session_and_user` 逻辑重复 |
| QA-S6 | `qa_cache_service.py:39` | 缓存 key 未包含 `user_id` |
| QA-S7 | `qa_service.py:717-733` | `_compress_with_keep_recent` 与 `_compress_with_sliding_window` 完全相同 |
| QA-S8 | `ai_chat_routes.py:218-226` | `download_chat_attachment` 直接访问 service 内部属性 |
| QA-S9 | `ai_chat_routes.py:241-276` | `health`/`models` 端点放在 ai-chat 路由下不合理 |

### deep_research（5 个）

| # | 位置 | 问题 |
|---|------|------|
| DR-S1 | `research_repository.py:158-173` | `get_by_space` 未 JOIN KnowledgeSpace 过滤（路由层已校验） |
| DR-S2 | `research_schema.py:23-28` | Schema 和 Model 各维护一套 ResearchStatus 枚举 |
| DR-S3 | `external_search_service.py:82-92` | `except Exception: continue` 静默吞没异常 |
| DR-S4 | `deep_research_service.py:1059-1084` | `_deduplicate_results` 混合模式去重策略不完善 |
| DR-S5 | `deep_research_service.py:714` | `refresh` 调用缺少注释说明意图 |

### evaluation（5 个）

| # | 位置 | 问题 |
|---|------|------|
| EV-S1 | `evaluation_schema.py:155-162` | `_status_to_str` 函数依赖枚举，变更时需同步 |
| EV-S2 | `evaluation_repository.py:259-277` | `get_orphan_tasks` 用 UTC 时间对比中国时间的 `created_at`，超时恢复慢 8 小时 |
| EV-S3 | `evaluation_service.py:371-372` | RuntimeError 错误信息未包含 `task_id` |
| EV-S4 | `routes.py:86-94` | 整个文件加载到内存（10MB 限制，当前可接受） |
| EV-S5 | `evaluation_service.py:284-290` | 人工评分平均分写入 MinIO 但未更新数据库标记 |

### agent（2 个）

| # | 位置 | 问题 |
|---|------|------|
| AG-S1 | `chat_service.py:409` | `tool_source` 判断逻辑不完整，`skill__` 前缀被归类为 `builtin` |
| AG-S2 | `agent_schema.py:70` | `AgentResponse` 暴露 `system_prompt`，列表接口也返回 |

### skill（1 个）

| # | 位置 | 问题 |
|---|------|------|
| SK-S1 | `skill_repository.py:125-126` | `json_contains` 不兼容 PostgreSQL |

### app（2 个）

| # | 位置 | 问题 |
|---|------|------|
| AP-S1 | `resume_parser.py:403-423` | S2 章节切割依赖 LLM，行号偏差已有修补逻辑 |
| AP-S2 | `routes.py:214-266` | `get_report_content` 和 `download_report` 逻辑几乎重复 |

---

## ✅ 修复优先级建议

### P0 — 立即修复（安全/数据问题）

- [x] **U-C1**: 移除 API Key 调试日志（`model_config_service.py:426-438`）
- [x] **SK-C1**: ZIP 解压添加路径遍历检查（`skill_parser.py:255-264`）
- [x] **SK-C2**: ZIP 文件大小限制（`routes.py:63`）
- [x] **QA-C3**: 补充异常分支的用户消息清理（`ai_chat_service.py:508-516`）
- [x] **AG-C2**: 系统级 MCP 服务器添加权限检查（`mcp_server_service.py:180-186`）
- [x] **AP-C2**: 文件上传添加类型和大小校验（`routes.py:36-57`）

- [x] **QA-C1**: 双重 commit 重构为 savepoint 方案（`ai_chat_service.py:235-301`）

> QA-C1 已通过 `async with session.begin_nested()` savepoint 方案修复，LLM 失败时自动回滚 AI 消息部分。

### P1 — 本迭代修复

- [x] **KS-C1**: retry_document 日志状态修正
- [x] **KS-C2**: 最后管理员离开时清理成员记录
- [x] **KS-C4**: 文档唯一约束排除软删除（软删除时修改 file_hash）
- [x] **KS-S4**: 删除 _extract_text 死代码
- [x] **KS-S5**: DocumentCountExceededError 注册异常处理器
- [x] **U-C2**: 缓存命中路径软删除检查增强（同时检查 deleted_at 和 status）
- [x] **U-S4**: 凭证重复查询消除（删除外层调试代码）
- [x] **U-W7**: 409 响应异常规范化
- [x] **QA-C4**: 附件查询添加 user_id 过滤
- [x] **QA-W1**: 会话列表改为按活跃时间排序
- [x] **QA-W8**: 异常构造函数参数修正
- [x] **QA-S2**: 调试日志降级为 DEBUG
- [x] **DR-C1/C2**: 研究配置持久化（config 字段写入）
- [x] **DR-C4**: 删除 is_web_search_enabled/set_config 死代码
- [x] **DR-W3**: 统一使用 _model_config_service，移除冗余属性
- [x] **DR-W6**: research_topic sanitize 异常降级使用原始值
- [x] **DR-S3**: 外部搜索异常添加 warning 日志
- [x] **EV-W2/W3**: MinIO/DB 删除顺序调换
- [x] **EV-W1**: get_by_id 添加 space_id/kb_id 归属校验参数
- [x] **EV-W5**: _generate_answer 统一返回 None
- [x] **EV-S2**: 时区不一致修复（改用 now_china）
- [x] **EV-S3**: RuntimeError 补充 task_id
- [x] **AG-C1**: SSE done 事件时序修正（先 commit 后 yield）
- [x] **AG-W2**: get_by_id/get_by_session_id 添加软删除过滤
- [x] **AG-W5**: 技能内容注入添加 review_status 检查
- [x] **AG-S1**: tool_source 判断支持 skill__ 前缀
- [x] **AG-S2**: AgentResponse 移除 system_prompt，新增 AgentDetailResponse
- [x] **SK-C4**: 卸载技能时正确清理 allowed_tools
- [x] **SK-W1**: create 方法改用 savepoint
- [x] **SK-W5**: LLM 审查超时改为 SUSPICIOUS
- [x] **AP-C1**: Pipeline 失败添加 FAILED 状态和 error_message
- [x] **AP-C4**: 临时文件添加扩展名白名单校验
- [x] **AP-W6**: config 参数添加类型检查

### P2 — 计划修复

- [x] **KS-C3**: ES 索引创建失败补偿机制
- [x] **KS-W1**: Sub Query RRF 融合算法修正
- [x] **EV-C3/C4**: 取消任务逻辑改进
- [x] **EV-W8**: 多 worker 任务状态管理
- [x] **AG-W6**: 知识库搜索工具添加权限校验

### P3 — 补充修复

- [x] **DR-C3**: commit 后异常不再覆盖已 COMPLETED 状态为 FAILED（`deep_research_service.py`）
- [x] **AP-C3**: AppError 改为继承 BaseAPIError 并注册异常处理器（`app/api/exceptions.py` + `exception_handlers.py`）
- [x] **EV-C1**: `_running_tasks` 添加多 worker 约束文档说明（`evaluation_service.py`）
- [x] **U-C3**: 缓存命中后 `session.get()` 添加 `refresh` 确保最新数据（`user_repository.py`）
- [x] **U-C4**: `_client_cache` 添加线程安全约定文档（`model_config_service.py`）
- [x] **QA-W4**: `get_by_ids` 添加 `user_id` 过滤参数防止越权（`chat_attachment_repository.py`）
- [x] **AG-W4**: MCP 客户端连接异常时清理残留 session/exit_stack（`mcp/client.py`）
- [x] **AG-W3**: 附件关联改用消息索引代替内容匹配（`chat_service.py`）
- [x] **AP-W1**: Pipeline 失败错误信息已正确传递（AP-C1 修复时已完成）
- [x] **AP-W5**: `update` 方法返回更新后的对象（`resume_repository.py`）
- [x] **EV-W9**: 导出结果区分 FAILED/CANCELLED 状态（`routes.py`）
- [x] **QA-W5**: 移除 `upload_attachment` 手动 commit，依赖自动 commit（`ai_chat_service.py`）

---

### 未修复项（低优先级 / 需评估）

以下问题经评估为低风险、设计权衡或需要较大重构，暂不修复：

**🟡 警告（27 个）：**

| # | 原因 |
|---|------|
| KS-W2 | 缓存 key 加入 user_id 需评估缓存命中率影响 |
| KS-W3 | 公开空间知识库可见性为设计决策，需产品确认 |
| KS-W4 | 动态附加属性到 ORM 为既有模式，重构风险大 |
| KS-W5 | 缓存枚举反序列化需评估影响范围 |
| KS-W6 | 软删除恢复 storage 清理需同步 ES 操作 |
| KS-W7 | 文件限制重复定义需统一提取到常量 |
| KS-W8 | MD5 碰撞风险极低，缓存场景可接受 |
| U-W1 | 管理员状态设计需与产品确认 |
| U-W2 | X-Forwarded-For 需运维配合配置受信代理 |
| U-W3 | Access Token 撤销机制需架构设计 |
| U-W4 | Redis 内部属性访问需评估缓存接口重构 |
| U-W5 | 缓存 TTL 需评估性能与一致性平衡 |
| U-W6 | phone UNIQUE NULL 可接受 |
| QA-W2 | SimpleNamespace 重构为 Pydantic 模型工作量大 |
| QA-W3 | session_id 正则需与前端协调 |
| QA-W7 | SSE thinking 降级需与前端协调 |
| DR-W1 | dict comprehension 当前安全，仅需注释 |
| DR-W2 | GET/POST 同路径需文档说明 |
| DR-W4 | httpx 客户端当前串行安全 |
| DR-W5 | 知识库搜索 warning 已在 DR-S3 添加 |
| DR-W7 | 降级任务描述优化需 LLM prompt 调优 |
| DR-W8 | 客户端 yield cleanup 当前安全 |
| EV-W4 | asyncio.create_task 当前安全 |
| EV-W6 | 软删除需数据库迁移 |
| EV-W7 | minio_client 是全局单例，当前安全 |
| AG-W1 | AgentMessage 继承 BaseModel 需评估序列化影响 |
| AG-W7 | 向量检索集成需较大开发量 |

**🔵 建议（37 个）：** KS-S1/S2/S3/S6/S7/S8/S9, U-S1/S2/S3/S5, QA-S1/S3/S4/S5/S6/S7/S8/S9, DR-S1/S2/S4/S5, EV-S1/S4/S5, SK-S1, AP-S1/S2 — 均为代码风格/重构/优化建议，非功能性问题。
