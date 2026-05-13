# 审核验证报告

> 验证时间：2026-05-09
> 验证范围：全项目 7 个模块的 41 个严重问题
> 验证方法：逐项回到源码验证，交叉检查跨文件调用

---

## 验证统计

| 模块 | 原始 | ✅确认 | ⚠️部分正确 | ❌误判 | 确认率 |
|------|------|--------|------------|--------|--------|
| agent | 8 | 4 | 3 | 1 | 87.5% |
| knowledge_space | 5 | 3 | 2 | 0 | 100% |
| qa | 6 | 2 | 3 | 1 | 83.3% |
| deep_research | 5 | 3 | 1 | 1 | 80% |
| evaluation | 7 | 1 | 2 | 4 | 42.9% |
| skill | 6 | 6 | 0 | 0 | 100% |
| user | 4 | 2 | 0 | 2 | 50% |
| **合计** | **41** | **21** | **11** | **9** | **78%** |

---

## ✅ 确认存在的问题

### Agent 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| A-1 | `api/exception_handlers.py` | L14 | STATUS_MAP key 与 SessionNotFoundError code 不匹配 | `STATUS_MAP` key 是 `CONVERSATION_NOT_FOUND`，但异常 code 是 `SESSION_NOT_FOUND`，命中默认值 500 |
| A-2 | `api/routes.py` | L331-356 | `/tools` 接口无需认证 | 两个端点参数列表均无 `Depends(get_current_user_id)` |
| A-3 | `services/chat_service.py` | L62-122 | SSE 流中多个 DB 操作无事务保护 | `_prepare`/`_handle_tool_call`/`_handle_tool_result` 逐步 flush，中间失败无法回滚 |
| A-5 | `services/agent_service.py` | L106-111 | 删除 Agent 是硬删除，关联数据未级联清理 | `delete(AgentDefinition).where(...)` 物理删除，sessions/messages/memories 成为孤儿数据 |

### Knowledge Space 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| KS-1 | `api/document_routes.py` + `api/exceptions.py` | L74-77 | DocumentSizeExceededError 参数名不匹配 | 调用端用 `size_mb=`/`max_size_mb=`，定义端签名为 `size`/`limit`，运行时 TypeError |
| KS-2 | `api/document_routes.py` | L168-177 | 批量上传单文件类型错误中断全部 | for 循环内直接 raise，无错误收集，与 failed 字段设计意图矛盾 |
| KS-3 | `api/dependencies.py` | L297-298 | validate_space_admin/editor 绕过请求级缓存 | 直接 `await db.get(User, user_id)` 而 validate_space_member 用了 `_get_cached_user` |

### QA 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| Q-2 | `services/ai_chat_service.py` | L185,361 | 双重提交事务问题 | 先 commit 用户消息再调 LLM，失败后回删已 commit 消息，代码注释也承认此风险 |
| Q-3 | `api/session_config_routes.py` | L67 | 从 repo.session 隐式获取 session | `QuestionAnswerRepository(repo.session)` 依赖另一个 repo 的内部属性 |

### Deep Research 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| DR-1 | `services/deep_research_service.py` | L196-209 | search_service 延迟初始化，ES 未配置时报错太晚 | property 延迟初始化，检索阶段才抛 RuntimeError，已消耗 LLM Token |
| DR-2 | `services/deep_research_service.py` | L857-880 | 错误恢复失败时产生僵尸记录 | rollback 后新 session commit 也失败时，记录停留在 RUNNING |
| DR-3 | `services/deep_research_service.py` | L471-477 | 流式路径 total_tasks 不准确 | 使用配置值 `mode_config["depth"]` 而非实际分解后的任务数 |

### Evaluation 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| E-4 | `services/evaluation_service.py` | L448-452 | 取消返回时自动 commit 持久化中间状态 | CANCELLED 分支内 `session.commit()` 会持久化之前 flush 的中间数据 |

### Skill 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| S-1 | `api/routes.py` | L136 vs L322 | 管理员 GET 路由被 /{skill_id} 拦截 | `/{skill_id}`(int) 先注册，`/admin/settings` 后注册，FastAPI 按顺序匹配返回 422 |
| S-2 | `services/skill_marketplace_service.py` | L217-235 | publish/unpublish 缺少 commit | repo.update 只做 flush，方法末尾无 `await self.db.commit()` |
| S-3 | `services/skill_marketplace_service.py` | L239-281 | install_skill 未校验 Agent 归属 | 完全没有检查 agent.user_id == user_id |
| S-4 | `services/skill_marketplace_service.py` | L283-307 | uninstall_skill 未清理 allowed_tools | 卸载只移除 skill_ref，安装时追加的工具名残留 |
| S-5 | `services/skill_marketplace_service.py` | L142-148 | 更新版本不校验新 ZIP 的 name | name 不在 _UPDATABLE_FIELDS 中不变，但其他字段已被新 ZIP 覆盖 |
| S-6 | `api/routes.py` | L142-150 | get_skill 无可见性检查 | repo.get_by_id 只过滤 deleted_at，任何用户可遍历查看私有技能 |

### User 模块

| # | 文件 | 行号 | 原始描述 | 验证说明 |
|---|------|------|---------|---------|
| U-1 | `services/auth_service.py` | L152-153 | Refresh Token 缺少 iat | create_access_token 有 iat，create_refresh_token 无 iat，导致黑名单检查异常 |
| U-3 | `services/model_config_service.py` | L45-48 | 模块级 _client_cache 多实例不共享 | 性能问题而非功能错误，单 worker 影响可忽略 |

---

## ⚠️ 部分正确的问题

| # | 文件 | 修正说明 | 实际影响 |
|---|------|---------|---------|
| A-4 | `chat_service.py:326-354` | 核心问题（commit 先于巩固）存在，但后果是巩固数据丢失而非"未 rollback" | 巩固失败影响低 |
| A-6 | `agent_repository.py:45-50` | 返回系统级 Agent 是有意设计（注释写明"系统级+用户自己的"） | 合理设计，非 bug |
| A-7 | `knowledge_search.py:105-202` | `_search` 路径有权限校验（委托 search_service），但 `_list_documents` 无校验 | 仅 document_list 工具存在越权 |
| KS-4 | `space_service.py:143-160` | 步骤 3-4 在 savepoint 外，但异常时 commit 不执行、session 关闭丢弃变更 | 数据一致性有保障，代码结构不清晰 |
| KS-5 | `member_routes.py:52` | 路由层缺少 validate_space_member，但服务层有基本成员校验 | 缺少空间存在性/状态检查 |
| Q-1 | `ai_chat_routes.py:137-158` | 裸 dict 会被 Pydantic 自动转换，不会 500（会 422），且 created_at 通常不为 None | 严重程度较低 |
| Q-4 | `qa_service.py:254-256` | commit() 无异常处理是事实，但调用方有兜底 try/except | 实际不会崩溃 |
| Q-5 | `qa_service.py:53` | 检查三个 repo 共享 session 是防御性校验，不是 bug | 合理设计 |
| DR-4 | `deep_research_service.py:514` | 全局累积结果导致的是当前任务后续迭代被跳过，非整个任务被跳过 | 影响低于原始描述 |
| E-3 | `evaluation_service.py:216-234` | 竞态窗口存在但属于优雅取消的预期行为 | 影响有限 |
| E-6 | `evaluation_service.py:183-189` | 理论上存在但实际几乎不会发生（asyncio.create_task 不立即执行） | 影响极小 |

---

## ❌ 误判记录

| # | 原始文件 | 原始行号 | 原始描述 | 误判原因 |
|---|---------|---------|---------|---------|
| A-8 | `startup.py` | L63-87 | MCP 服务器启动 DB 缺少 commit | `get_db_session()` 上下文管理器正常退出时自动 commit |
| Q-6 | `session_config_routes.py` | L41-93 | session_id 格式校验不一致 | 所有路由均使用 `Path(min_length=1)`，完全一致 |
| DR-5 | `routes.py` | — | HEAD 请求行为不确定 | FastAPI 自动处理 HEAD 为无 body 的 GET，是标准行为 |
| E-1 | `evaluation_service.py` | L436 | as_completed 进度计数不准确 | completed 计数准确反映已处理协程数 |
| E-2 | `evaluation_service.py` | L327-384 | 并发协程共享 session | 后台任务用独立 session，读操作共享安全，写操作串行 |
| E-5 | `evaluation_service.py` | L275 | human_score 为 None 导致 TypeError | 列表推导已过滤 `is not None`，不会参与求和 |
| E-7 | `evaluation_service.py` | L118-127 | 更新测试集名称影响运行中任务 | name 只是显示属性，任务使用 MinIO 文件数据不依赖 name |
| U-2 | `user_repository.py` | L148-149 | 缓存穿透返回已删除用户 | 代码有 `deleted_at is not None` 检查 + 软删除时主动失效缓存 |
| U-4 | `model_config_service.py` | L64-84 | cleanup 中 aclose 可能死锁 | aclose 是外部客户端方法，不会回访 _cache_lock |

---

## 🔴 确认的严重问题优先修复清单（21 项）

### 最高优先级（功能完全失效或数据错误）

1. **S-1** skill 管理员 GET 路由完全不可用
2. **S-2** skill publish/unpublish 数据不持久化
3. **KS-1** 文件上传超限抛 TypeError 而非业务异常
4. **A-1** 会话不存在返回 500 而非 404
5. **A-5** Agent 硬删除产生孤儿数据
6. **S-6** 任意用户可查看/下载他人私有技能

### 高优先级（安全或越权问题）

7. **A-2** 工具列表接口无认证
8. **S-3** install_skill 未校验 Agent 归属（越权）
9. **S-4** uninstall_skill 未清理 allowed_tools（残留）
10. **S-5** 更新版本不校验 name 一致性

### 中优先级（事务/数据一致性）

11. **A-3** SSE 流中 DB 操作无事务保护
12. **Q-2** 双重提交事务 + 回删失败产生孤立数据
13. **DR-1** ES 未配置时延迟到检索阶段才报错
14. **DR-2** 错误恢复失败产生僵尸记录
15. **DR-3** 流式路径 total_tasks 不准确
16. **KS-2** 批量上传单文件失败中断全部
17. **E-4** 取消时 commit 持久化中间状态

### 低优先级（性能或代码质量）

18. **KS-3** validate_space_admin/editor 绕过请求级缓存
19. **Q-3** session_config 隐式获取 session
20. **U-1** Refresh Token 缺少 iat
21. **U-3** 模块级缓存多实例不共享
