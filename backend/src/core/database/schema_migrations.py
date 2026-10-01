"""幂等启动期迁移注册表。

create_all 不给已存在的表做 ALTER，本模块集中维护补列与约束迁移清单，由 startup_manager 在启动期逐条检测后执行，幂等可重复。
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
    # ===== kb-ops B1 文档生命周期治理（六列一批，模型见 knowledge_space/models/document.py） =====
    (
        "documents",
        "lifecycle_status",
        "ALTER TABLE documents ADD COLUMN lifecycle_status VARCHAR(16) NOT NULL DEFAULT 'active' COMMENT '生命周期：draft/active/superseded/archived；检索默认只召回 active'",
    ),
    (
        "documents",
        "owner_id",
        # 存量回填：owner 先取 uploader（Glean 四要素的落地起点；后续可在 UI 改派）。
        # 补列与回填分两步走：本条只补列，回填由 startup_manager 的数据迁移钩子执行。
        "ALTER TABLE documents ADD COLUMN owner_id BIGINT NULL COMMENT '内容责任人（新上传默认 uploader_id；存量由迁移回填）'",
    ),
    (
        "documents",
        "effective_date",
        "ALTER TABLE documents ADD COLUMN effective_date DATETIME NULL COMMENT '生效时间（时效性过滤/展示用）'",
    ),
    (
        "documents",
        "review_cycle_days",
        "ALTER TABLE documents ADD COLUMN review_cycle_days INT NULL COMMENT '复审周期（天）；KB 级默认值可被文档覆盖'",
    ),
    (
        "documents",
        "next_review_at",
        "ALTER TABLE documents ADD COLUMN next_review_at DATETIME NULL COMMENT '下次复审时间（到期提醒扫描字段）'",
    ),
    (
        "documents",
        "superseded_by_doc_id",
        "ALTER TABLE documents ADD COLUMN superseded_by_doc_id BIGINT NULL COMMENT '被哪个新版文档替代（版本链锚点，superseded 态必填）'",
    ),
)