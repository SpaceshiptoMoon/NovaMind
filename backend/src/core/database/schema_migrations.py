"""幂等启动期迁移注册表。

``create_all()`` 只创建不存在的表，不会给已存在的表 ``ALTER ADD COLUMN`` 或
调整索引/约束。本模块集中维护启动期迁移清单，由
``startup_manager._run_schema_migrations`` 在启动期逐条检测后执行（幂等可重复）。

两张注册表：

- ``SCHEMA_MIGRATIONS``：新增列 ``(表名, 列名, ALTER DDL)``，检测 ``SHOW COLUMNS``
  缺列则补建。结构由 ``tests/core/test_schema_migrations.py`` 校验。
- ``CONSTRAINT_MIGRATIONS``：唯一约束/索引变更 ``(表名, 待删旧索引, 待建新索引,
  ADD DDL)``，检测新索引存在则跳过；不存在则先 drop 旧索引（若有）再按 DDL 建
  新索引。用于约束口径变更（如去重范围调整）时同步存量库。
"""
from __future__ import annotations

# 唯一约束/索引迁移：(表名, 待删旧索引名, 待建新索引名, ADD DDL)。
# ADD DDL 必须形如 "ALTER TABLE <表名> ADD <UNIQUE KEY|INDEX> <新索引名> ..."。
CONSTRAINT_MIGRATIONS: tuple[tuple[str, str, str, str], ...] = (
    (
        # 去重范围收紧：文档唯一约束从 (kb_id, file_hash) 放宽为
        # (kb_id, uploader_id, file_hash)，允许不同成员各自上传同一文件。
        # 新约束比旧约束宽松，存量数据必然满足，无需数据清洗。
        "documents",
        "uq_kb_file_hash",
        "uq_kb_uploader_file_hash",
        "ALTER TABLE documents ADD UNIQUE KEY uq_kb_uploader_file_hash (kb_id, uploader_id, file_hash)",
    ),
)

SCHEMA_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    (
        "users",
        "role_id",
        "ALTER TABLE users ADD COLUMN role_id BIGINT NULL COMMENT '关联角色ID，替代 is_admin'",
    ),
    (
        "qa_session_configs",
        "kb_bindings",
        "ALTER TABLE qa_session_configs ADD COLUMN kb_bindings JSON NULL",
    ),
    (
        "qa_session_configs",
        "llm_config",
        "ALTER TABLE qa_session_configs ADD COLUMN llm_config JSON NULL",
    ),
    (
        "document_task_items",
        "process_mode",
        "ALTER TABLE document_task_items ADD COLUMN process_mode SMALLINT NOT NULL DEFAULT 0 COMMENT 'Task process mode'",
    ),
    (
        "document_tasks",
        "processed_count",
        "ALTER TABLE document_tasks ADD COLUMN processed_count SMALLINT NULL DEFAULT 0 COMMENT '已处理文档数 completed+failed+cancelled'",
    ),
    (
        "qa_session_configs",
        "web_search_config",
        "ALTER TABLE qa_session_configs ADD COLUMN web_search_config JSON NULL",
    ),
    (
        "agent_messages",
        "reasoning",
        "ALTER TABLE agent_messages ADD COLUMN reasoning TEXT NULL",
    ),
    (
        "agent_tool_calls",
        "call_id",
        "ALTER TABLE agent_tool_calls ADD COLUMN call_id VARCHAR(64) NULL COMMENT 'LLM 工具调用ID，与 tool 消息 tool_call_id 对应'",
    ),
    (
        "agent_messages",
        "iteration",
        "ALTER TABLE agent_messages ADD COLUMN iteration INT NULL COMMENT 'ReAct 轮号（1-based，每次 LLM 调用一轮）；null 为历史数据'",
    ),
    (
        "agent_tool_calls",
        "iteration",
        "ALTER TABLE agent_tool_calls ADD COLUMN iteration INT NULL COMMENT 'ReAct 轮号（1-based，与所属 assistant 决策消息同轮）；null 为历史数据'",
    ),
    (
        "users",
        "is_super_admin",
        "ALTER TABLE users ADD COLUMN is_super_admin BOOLEAN NOT NULL DEFAULT 0 COMMENT '最高管理员标记（不可被其他管理员降级/删除/停用）'",
    ),
)