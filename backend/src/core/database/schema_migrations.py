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
)