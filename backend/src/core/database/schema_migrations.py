"""幂等补列迁移注册表。

``create_all()`` 只创建不存在的表，不会给已存在的表 ``ALTER ADD COLUMN``。本模块
集中维护「新增列」迁移清单，由 ``startup_manager._run_schema_migrations`` 在启动期
逐条检测目标列缺失则补建（``SHOW COLUMNS LIKE`` + ``ADD COLUMN``，幂等可重复执行）。

新增列时向 ``SCHEMA_MIGRATIONS`` 追加 ``(表名, 列名, ALTER DDL)`` 三元组。DDL 必须
以 ``ALTER TABLE <表名> ADD COLUMN`` 开头。结构由 ``tests/test_schema_migrations.py``
校验（三元组类型、DDL 规范、无重复 (表,列)），防迁移漂移。
"""
from __future__ import annotations

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