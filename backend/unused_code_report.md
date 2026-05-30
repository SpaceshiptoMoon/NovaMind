# 未使用代码扫描报告（已二次验证）

扫描范围：`src/` + `tests/` 全目录。经 4 个独立 Agent 二次验证，排除误报。

## 验证发现的误报（8 项，已从报告中移除）

| # | 函数/类 | 文件 | 原因 |
|---|--------|------|------|
| 1 | `get_status_code_for_error()` | `core/middleware/base_exception_handler.py` | 同文件内部 `line 223` 有调用 |
| 2 | `Document.get_storage_info()` | `knowledge_space/models/document.py` | `worker.py:96`、`document_service.py:561,671` 有调用 |
| 3 | `SpaceMember.is_editor_or_above()` | `knowledge_space/models/space_member.py` | `document_routes.py:449`、`dependencies.py:337` 有调用 |
| 4 | `SpaceMember.generate_invite_token()` | `knowledge_space/models/space_member.py` | `member_service.py:103`、`member_repository.py:92` 有调用 |
| 5 | `ResearchSession.get_status_info()` | `deep_research/models/research_session.py` | 类内部被 5 个方法调用 |
| 6 | `ResearchSession.set_started()` | `deep_research/models/research_session.py` | 被 `mark_started()` 内部调用 |
| 7 | `ResearchSession.set_cancelled()` | `deep_research/models/research_session.py` | 被 `mark_cancelled()` 内部调用 |
| 8 | `ResearchSession.get_result()` | `deep_research/models/research_session.py` | 类内部被 get_answer/get_sources 等调用 |

---

## 确认未使用：core/（4 项）

| # | 函数/类 | 文件 | 行号 | 说明 |
|---|--------|------|------|------|
| 1 | `get_trace_id()` | `core/middleware/trace_middleware.py` | 173 | 从未导入或调用 |
| 2 | `SecurityConfigValidator.get_report()` | `core/security/config_validator.py` | 284 | 从未在实例上调用 |
| 3 | `SecurityConfigValidator.has_critical_issues()` | `core/security/config_validator.py` | 315 | 从未在实例上调用 |
| 4 | `LoggingMiddleware.clear_context()` | `core/middleware/structured_logging.py` | 156 | 从未被调用 |

---

## 确认未使用：shared/（12 项）

| # | 函数/类 | 文件 | 行号 | 说明 |
|---|--------|------|------|------|
| 1 | `LRUCache.cleanup_expired()` | `shared/cache/lru_cache.py` | 147 | 从未调用 |
| 2 | `LRUCache.clear()` | `shared/cache/lru_cache.py` | 140 | 从未调用 |
| 3 | `XMLReader` (类) | `shared/utils/document_readers/document_loader.py` | 278 | 未注册到 DocumentRegistry |
| 4 | `SentenceSplitter` (类) | `shared/utils/document_readers/document_loader.py` | 285 | 未注册到 DocumentRegistry |
| 5 | `FileValidator.calculate_hash()` | `shared/utils/file_validator.py` | 332 | 从未调用 |
| 6 | `TokenCounter.estimate_messages_tokens()` | `shared/utils/text_processing/token_counter.py` | 107 | 从未调用 |
| 7 | `TokenCounter.get_encoder()` | `shared/utils/text_processing/token_counter.py` | 120 | 从未调用 |
| 8 | `MinioClient.get_document_path_pattern()` | `shared/storage/minio_client.py` | 852 | 从未调用 |
| 9 | `MinioClient.get_kb_path_pattern()` | `shared/storage/minio_client.py` | 857 | 从未调用 |
| 10 | `MinioClient.get_space_path_pattern()` | `shared/storage/minio_client.py` | 862 | 从未调用 |
| 11 | `MinioClient.get_avatar_path()` | `shared/storage/minio_client.py` | 867 | 从未调用 |
| 12 | `MinioClient.get_temp_path()` | `shared/storage/minio_client.py` | 872 | 从未调用 |

---

## 确认未使用：user/（7 项）

| # | 函数 | 文件 | 行号 |
|---|------|------|------|
| 1 | `User.is_banned()` | `user/models/user.py` | 87 |
| 2 | `User.set_profile_value()` | `user/models/user.py` | 101 |
| 3 | `User.get_nickname()` | `user/models/user.py` | 107 |
| 4 | `User.get_avatar()` | `user/models/user.py` | 111 |
| 5 | `User.get_preferences()` | `user/models/user.py` | 115 |
| 6 | `User.get_login_count()` | `user/models/user.py` | 123 |
| 7 | `UserModelConfig.set_extra()` | `user/models/user_model_config.py` | 78 |

---

## 确认未使用：qa/（14 项）

| # | 函数 | 文件 | 行号 |
|---|------|------|------|
| 1 | `QuestionAnswer.get_feedback()` | `qa/models/question_answer.py` | 62 |
| 2 | `QuestionAnswer.get_usage()` | `qa/models/question_answer.py` | 66 |
| 3 | `QuestionAnswer.get_references()` | `qa/models/question_answer.py` | 70 |
| 4 | `QuestionAnswer.set_feedback()` | `qa/models/question_answer.py` | 74 |
| 5 | `QuestionAnswer.set_usage()` | `qa/models/question_answer.py` | 87 |
| 6 | `QuestionAnswer.set_references()` | `qa/models/question_answer.py` | 98 |
| 7 | `QuestionAnswer.get_input_tokens()` | `qa/models/question_answer.py` | 104 |
| 8 | `QuestionAnswer.get_output_tokens()` | `qa/models/question_answer.py` | 108 |
| 9 | `QuestionAnswer.set_attachments()` | `qa/models/question_answer.py` | 116 |
| 10 | `SessionSummary.get_stats()` | `qa/models/session_summary.py` | 51 |
| 11 | `SessionSummary.get_compressed_count()` | `qa/models/session_summary.py` | 59 |
| 12 | `SessionSummary.increment_version()` | `qa/models/session_summary.py` | 75 |
| 13 | `SessionConfig.set_compression_config()` | `qa/models/session_config.py` | 76 |
| 14 | `QACacheService.get_cache_stats()` | `qa/services/qa_cache_service.py` | 352 |

---

## 确认未使用：knowledge_space/（55 项）

### KnowledgeSpace 模型 (12 项)

文件: `knowledge_space/models/knowledge_space.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `get_tags()` | 88 |
| 2 | `get_ui_config()` | 92 |
| 3 | `get_minio_bucket()` | 100 |
| 4 | `get_minio_prefix()` | 104 |
| 5 | `get_max_documents()` | 135 |
| 6 | `get_max_storage_mb()` | 139 |
| 7 | `is_archived()` | 165 |
| 8 | `is_private()` | 169 |
| 9 | `is_team_visible()` | 173 |
| 10 | `archive()` | 179 |
| 11 | `soft_delete()` | 183 |
| 12 | `restore()` | 188 |

### KnowledgeBase 模型 (5 项)

文件: `knowledge_space/models/knowledge_base.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `get_retrieval_config()` | 107 |
| 2 | `enable_question_generation()` | 136 |
| 3 | `get_es_index_name()` | 150 |
| 4 | `get_minio_prefix()` | 154 |
| 5 | `archive()` | 182 |

### Document 模型 (16 项)

文件: `knowledge_space/models/document.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `get_original_filename()` | 100 |
| 2 | `get_minio_object_name()` | 108 |
| 3 | `get_minio_etag()` | 112 |
| 4 | `get_status_info()` | 132 |
| 5 | `get_retry_count()` | 140 |
| 6 | `get_metadata_value()` | 161 |
| 7 | `set_metadata()` | 165 |
| 8 | `get_parent_id()` | 183 |
| 9 | `create_new_version()` | 194 |
| 10 | `is_processing()` | 198 |
| 11 | `is_completed()` | 202 |
| 12 | `is_failed()` | 206 |
| 13 | `is_uploaded()` | 210 |
| 14 | `get_processing_duration_seconds()` | 236 |
| 15 | `is_deleted()` | 245 |
| 16 | `soft_delete()` | 249 |
| 17 | `restore()` | 253 |

### SpaceMember 模型 (7 项)

文件: `knowledge_space/models/space_member.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `set_custom_permission()` | 94 |
| 2 | `remove_custom_permission()` | 111 |
| 3 | `clear_custom_permissions()` | 130 |
| 4 | `is_suspended()` | 150 |
| 5 | `is_viewer_or_above()` | 158 |
| 6 | `promote_to_editor()` | 183 |
| 7 | `promote_to_admin()` | 187 |
| 8 | `demote_to_viewer()` | 191 |

### SpaceAuditLog 模型 (11 项)

文件: `knowledge_space/models/space_audit_log.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `get_resource_type()` | 87 |
| 2 | `get_resource_id()` | 91 |
| 3 | `get_resource_name()` | 95 |
| 4 | `set_resource()` | 99 |
| 5 | `get_context()` | 110 |
| 6 | `get_ip_address()` | 114 |
| 7 | `get_user_agent()` | 118 |
| 8 | `get_request_id()` | 122 |
| 9 | `set_context()` | 126 |
| 10 | `get_changes()` | 156 |
| 11 | `set_changes()` | 160 |

### PermissionService (4 项)

文件: `knowledge_space/services/permission_service.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `is_space_owner_or_admin()` | 89 |
| 2 | `can_delete_space()` | 93 |
| 3 | `can_update_space()` | 100 |
| 4 | `can_delete_own_document()` | 128 |

### 独立函数 (1 项)

| # | 函数 | 文件 | 行号 |
|---|------|------|------|
| 1 | `_deserialize_datetime_fields()` | `knowledge_space/repository/space_repository.py` | 13 |

---

## 确认未使用：deep_research/（15 项）

文件: `deep_research/models/research_session.py`

| # | 函数 | 行号 |
|---|------|------|
| 1 | `get_max_iterations()` | 132 |
| 2 | `get_llm_model()` | 140 |
| 3 | `get_started_at()` | 154 |
| 4 | `get_completed_at()` | 158 |
| 5 | `get_cancelled_at()` | 162 |
| 6 | `get_cancel_reason()` | 166 |
| 7 | `get_answer()` | 201 |
| 8 | `get_sources()` | 205 |
| 9 | `get_reasoning_steps()` | 209 |
| 10 | `get_confidence()` | 213 |
| 11 | `get_stats()` | 240 |
| 12 | `set_stats()` | 244 |
| 13 | `is_pending()` | 251 |
| 14 | `is_completed()` | 259 |
| 15 | `is_cancelled()` | 267 |

---

## 确认未使用：skill/ + app/（4 项）

| # | 类名 | 文件 | 行号 | 说明 |
|---|------|------|------|------|
| 1 | `SkillMarketplaceQuery` | `skill/schemas/skill_schema.py` | 28 | 仅 __init__.py 导出，无实际消费 |
| 2 | `SkillUploadPreviewResponse` | `skill/schemas/skill_schema.py` | 157 | 仅 __init__.py 导出，无实际消费 |
| 3 | `SkillVersionResponse` | `skill/schemas/skill_schema.py` | 138 | 仅 __init__.py 导出，无实际消费 |
| 4 | `ResumeUploadRequest` | `app/schemas/resume_schema.py` | 358 | 从未被引用 |

---

## 最终汇总

| 模块 | 确认未使用 | 误报排除 |
|------|-----------|---------|
| core/ | 4 | 1 |
| shared/ | 12 | 0 |
| user/ | 7 | 0 |
| qa/ | 14 | 0 |
| knowledge_space/ | 55 | 3 |
| deep_research/ | 15 | 4 |
| skill/ + app/ | 4 | 0 |
| agent/ | 0 | 0 |
| evaluation/ | 0 | 0 |
| **合计** | **111** | **8** |
