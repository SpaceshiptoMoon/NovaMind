"""
启动管理器，负责应用启动和关闭时的组件管理。
"""
import os
import time
from contextlib import asynccontextmanager

from sqlalchemy import text

from novamind.setting.yaml_config import get_config
from novamind.core.middleware.structured_logging import get_logger
from novamind.core.middleware.manifest_loader import get_sorted_manifests

from novamind.core.database.base import create_tables, ensure_fulltext_indexes
from novamind.core.database.database import get_engine, dispose_engine
from novamind.core.database.schema_migrations import SCHEMA_MIGRATIONS
from novamind.shared.cache.redis_client import get_redis_client, close_redis_connection

logger = get_logger(__name__)


# ==================== manifest 驱动路径（默认） ====================


def _import_models() -> None:
    """动态导入所有业务模型，确保在创建表之前注册到 SQLAlchemy metadata。

    遍历各 feature manifest 的 `models_loader`；legacy 路径
    （`NOVAMIND_LEGACY_MANIFEST=1`）走 `_import_models_legacy` 硬编码导入。
    """
    if os.getenv("NOVAMIND_LEGACY_MANIFEST") == "1":
        _import_models_legacy()
        return
    for m in get_sorted_manifests():
        if not m.enabled or m.models_loader is None:
            continue
        m.models_loader()


# ==================== legacy 硬编码路径（回滚用） ====================

# 功能模块初始化注册表（legacy）
_feature_initializers = []


def register_feature_initializer(init_func):
    """注册功能模块初始化函数（legacy）"""
    _feature_initializers.append(init_func)


# 注册已知的功能模块（统一接受 app 参数，legacy）
async def _init_user(app):
    """用户模块初始化（legacy，不使用 app 参数）"""
    from novamind.features.user.api.startup import init_user_components
    await init_user_components()


register_feature_initializer(_init_user)


async def _init_knowledge_space(app):
    """知识空间模块初始化（legacy）"""
    from novamind.features.knowledge_space.api.startup import init_knowledge_space_components
    await init_knowledge_space_components(app)


register_feature_initializer(_init_knowledge_space)


async def _init_agent(app):
    """Agent 模块初始化（legacy）"""
    from novamind.features.agent.api.startup import init_agent_components
    await init_agent_components(app)


register_feature_initializer(_init_agent)


async def _init_notification(app):
    """通知模块初始化（legacy）"""
    from novamind.features.notification.api.startup import init_notification_components
    await init_notification_components(app)


register_feature_initializer(_init_notification)


async def _init_clawmate(app):
    """ClawMate 终端模块初始化（legacy）"""
    from novamind.features.clawmate.api.startup import init_clawmate_components
    await init_clawmate_components(app)


register_feature_initializer(_init_clawmate)


def _import_models_legacy() -> None:
    """动态导入所有业务模型（legacy 硬编码，回滚用）"""
    from novamind.features.user.models.user import User  # noqa: F401
    from novamind.features.user.models.user_model_config import UserModelConfig  # noqa: F401
    from novamind.features.user.models.user_disabled_app import UserDisabledApp  # noqa: F401
    from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace  # noqa: F401
    from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase  # noqa: F401
    from novamind.features.knowledge_space.models.document import Document  # noqa: F401
    from novamind.features.knowledge_space.models.space_member import SpaceMember  # noqa: F401
    from novamind.features.knowledge_space.models.space_audit_log import SpaceAuditLog  # noqa: F401
    from novamind.features.qa.models.question_answer import QuestionAnswer  # noqa: F401
    from novamind.features.qa.models.session_config import SessionConfig  # noqa: F401
    from novamind.features.qa.models.session_summary import SessionSummary  # noqa: F401
    from novamind.features.deep_research.models.research_session import ResearchSession  # noqa: F401
    from novamind.features.evaluation.models.evaluation_task import EvaluationTestSet, EvaluationTask  # noqa: F401
    from novamind.features.agent.models.agent import AgentDefinition  # noqa: F401
    from novamind.features.agent.models.session import AgentSession  # noqa: F401
    from novamind.features.agent.models.message import AgentMessage  # noqa: F401
    from novamind.features.agent.models.tool_call import AgentToolCall  # noqa: F401
    from novamind.features.agent.models.mcp_server import AgentMcpServer  # noqa: F401
    from novamind.features.agent.models.memory import AgentMemory  # noqa: F401
    from novamind.features.agent.models.context_summary import AgentContextSummary  # noqa: F401
    from novamind.features.skill.models.skill import SkillDefinition, SkillVersion, SkillReview, SkillInstallation  # noqa: F401
    from novamind.features.app.models.resume import ResumeSession  # noqa: F401
    from novamind.features.notification.models.notification import Notification  # noqa: F401
    from novamind.features.notification.models.notification_preference import NotificationPreference  # noqa: F401


class AppLifespanManager:
    """应用生命周期管理器"""

    def __init__(self):
        self.redis_connected = False
        self.logger = logger

    @asynccontextmanager
    async def lifespan(self, app):
        """管理应用的启动和关闭"""
        start_time = time.time()
        self.logger.info("应用正在启动...")
        self._app = app

        # 加载配置并存储到 app.state
        config = get_config()
        app.state.config = config
        self.logger.info("配置环境已加载", environment=config.environment)

        # 装配加密密钥（shared/utils/crypto 不得直接读 setting；须在任意加解密前注入）
        from novamind.shared.utils.crypto import configure_encryption_key
        configure_encryption_key(config.security.encryption_key)

        # 打印关键配置信息（脱敏）
        self.logger.info("========== 配置信息 ==========")
        self.logger.info(
            "Redis 配置",
            enabled=config.redis.enabled,
            host=config.redis.host,
            port=config.redis.port,
        )
        self.logger.info(
            "数据库配置",
            host=config.database.host,
            port=config.database.port,
            database=config.database.database,
        )
        self.logger.info("向量数据库类型", vector_db_type=getattr(config.vector_db, 'type', 'N/A'))
        self.logger.info("模型配置已迁移到数据库（model_configs）")
        self.logger.info("==============================")

        # 注册提示词模板（须在功能模块初始化与请求处理之前完成）
        await self._register_prompt_templates()

        # 装配共享客户端工厂（注入宿主配置；shared 层不得直接读 setting/features）
        # 路径/索引策略直接用 shared 层 Default* 实现（宿主无需定制层），不注入则自动回退。
        from novamind.shared.storage.client_factory import ClientFactory
        ClientFactory.configure(config)

        # 初始化Redis连接
        redis_start = time.time()
        await self._init_redis(config)
        self.logger.info("Redis 初始化完成", duration=f"{time.time() - redis_start:.2f}s")

        # 创建数据库表
        db_start = time.time()
        await self._create_database_tables()
        self.logger.info("数据库表创建完成", duration=f"{time.time() - db_start:.2f}s")

        # 幂等 schema 迁移（create_all 不 ALTER 已有表，手动补新增列）
        await self._run_schema_migrations()

        # 初始化各功能模块
        features_start = time.time()
        await self._init_features(app)
        self.logger.info("功能模块初始化完成", duration=f"{time.time() - features_start:.2f}s")

        # 恢复孤儿测评任务
        try:
            from novamind.features.evaluation.services.evaluation_service import EvaluationService
            recovered = await EvaluationService.recover_orphan_tasks()
            if recovered:
                self.logger.info("孤儿测评任务恢复完成", recovered=recovered)
        except Exception as e:
            self.logger.warning("孤儿测评任务恢复失败", error=str(e))

        # 启动嵌入式 arq Worker（任务函数从各 feature tasks 收集注入；shared/mq 只提供通用运行时）
        try:
            from novamind.features.knowledge_space.tasks.document_tasks import (
                process_document_task,
                recover_orphan_documents,
            )
            from novamind.features.app.tasks.resume_tasks import (
                process_resume_task,
                recover_orphan_resume_sessions,
            )
            from novamind.shared.mq.worker import start_embedded_worker
            await start_embedded_worker(
                functions=[process_document_task, process_resume_task],
                task_queue=config.task_queue,
            )
            self.logger.info("嵌入式 arq Worker 已启动")

            # 恢复孤儿文档（PROCESSING 状态的文档重新入队）
            recovered_docs = await recover_orphan_documents()
            if recovered_docs:
                self.logger.info("孤儿文档恢复完成", recovered=recovered_docs)

            # 恢复孤儿简历会话（PARSING/ANALYZING/PROBING 状态重新入队）
            try:
                recovered_resumes = await recover_orphan_resume_sessions()
                if recovered_resumes:
                    self.logger.info("孤儿简历会话恢复完成", recovered=recovered_resumes)
            except Exception as e:
                self.logger.warning("孤儿简历会话恢复失败", error=str(e))
        except Exception as e:
            self.logger.warning("arq Worker 启动失败", error=str(e))

        total_time = time.time() - start_time
        self.logger.info("应用启动完成", total_duration=f"{total_time:.2f}s")

        yield

        # 清理资源
        await self._cleanup()

    async def _init_redis(self, config):
        """初始化Redis连接"""
        self.logger.info("检查 Redis 配置", enabled=config.redis.enabled)

        if not config.redis.enabled:
            self.logger.info("Redis 缓存已禁用")
            return

        try:
            self.logger.info(
                "正在连接 Redis",
                host=config.redis.host,
                port=config.redis.port,
            )
            redis_client = await get_redis_client()
            await redis_client.redis_client.ping()
            self.redis_connected = True
            self.logger.info("Redis连接已建立")

            # 向量索引已由 Elasticsearch 管理，无需在 Redis 中创建
            # 如需启用 Redis 向量索引，请取消下方注释并确保安装 Redis Stack（支持 RediSearch 模块）
            # try:
            #     await redis_client.create_embedding_index(1024)
            #     self.logger.info("Redis向量索引创建成功")
            # except Exception as idx_err:
            #     # 普通Redis不支持向量索引，但不影响基础缓存功能
            #     self.logger.warning(
            #         "向量索引创建失败（需要Redis Stack）",
            #         error=str(idx_err),
            #     )
            #     self.logger.info("将使用基础缓存功能，向量相似搜索不可用")

        except Exception as e:
            self.logger.warning("Redis连接失败，部分缓存功能将不可用", error=str(e))

    async def _create_database_tables(self):
        """创建数据库表"""
        try:
            # 动态导入模型以确保注册到 SQLAlchemy metadata
            _import_models()
            db_engine = get_engine()
            await create_tables(db_engine)
            self.logger.info("数据库表创建成功")

            # 创建 FULLTEXT 索引（ngram 中文分词）
            await ensure_fulltext_indexes(db_engine)
        except Exception as e:
            self.logger.error(
                "数据库表创建失败",
                error=str(e),
                hint="请检查数据库连接配置：host、port、user、password、database 是否正确，"
                     "以及数据库服务是否已启动。可在 yaml 配置文件中修改 database 相关配置。",
            )
            raise

    async def _run_schema_migrations(self):
        """
        幂等补列迁移。

        create_all() 只创建不存在的表，不会给已存在的表 ALTER ADD COLUMN。
        在此集中维护「新增列」迁移：检测目标列缺失则补建，幂等可重复执行。
        新增列时向 ``core.database.schema_migrations.SCHEMA_MIGRATIONS`` 追加
        (表名, 列名, DDL) 即可，结构由 ``tests/test_schema_migrations.py`` 校验。
        """
        db_engine = get_engine()
        for table, column, ddl in SCHEMA_MIGRATIONS:
            try:
                async with db_engine.begin() as conn:
                    exists = (
                        await conn.execute(
                            text("SHOW COLUMNS FROM `%s` LIKE :c" % table),
                            {"c": column},
                        )
                    ).fetchone()
                    if not exists:
                        await conn.execute(text(ddl))
                        self.logger.info("schema 迁移：补列", table=table, column=column)
            except Exception as e:
                self.logger.warning(
                    "schema 迁移失败",
                    table=table,
                    column=column,
                    error=str(e),
                )

    async def _init_features(self, app):
        """初始化各功能模块（按 manifest 拓扑序）

        默认遍历 `get_sorted_manifests()`，对每个有 `init_hook` 的 enabled manifest
        按拓扑序调用，日志呈现拓扑顺序（如 user→knowledge_space→agent→
        notification→clawmate）。`NOVAMIND_LEGACY_MANIFEST=1` 时回滚到旧的
        `_feature_initializers` 注册序。
        """
        if os.getenv("NOVAMIND_LEGACY_MANIFEST") == "1":
            for init_func in _feature_initializers:
                await init_func(app)
            self.logger.info("各功能模块初始化完成（legacy）")
            return
        for m in get_sorted_manifests():
            if not m.enabled or m.init_hook is None:
                continue
            self.logger.info("feature 初始化开始", feature=m.name)
            await m.init_hook(app)
            self.logger.info("feature 初始化完成", feature=m.name)
        self.logger.info("各功能模块初始化完成")

    async def _register_prompt_templates(self) -> None:
        """注册各 feature 的提示词模板到 PromptManager。

        提示词注册表（`shared/prompts/prompt_manager.PromptManager`）为纯机制，
        不反向 import feature 模块（消除原 shared→features 分层违规）。提示词数据
        由本方法在启动期注入；注册清单集中在
        `core/middleware/prompt_registration.register_all_prompt_templates`，
        供启动期与单元测试共用，避免清单漂移。
        """
        from novamind.core.middleware.prompt_registration import (
            register_all_prompt_templates,
        )

        count = register_all_prompt_templates()
        self.logger.info("提示词模板注册完成", total=count)

    async def _cleanup(self):
        """清理资源"""
        self.logger.info("应用正在关闭...")

        # 停止 arq Worker
        try:
            from novamind.shared.mq.worker import stop_embedded_worker
            await stop_embedded_worker()
            self.logger.info("arq Worker 已停止")
        except Exception as e:
            self.logger.warning("停止 arq Worker 时出错", error=str(e))

        # 关闭 arq 连接池
        try:
            from novamind.shared.mq import close_arq_pool
            await close_arq_pool()
        except Exception as e:
            self.logger.warning("关闭 arq 连接池时出错", error=str(e))

        # 关闭 MCP 连接
        try:
            if hasattr(self, '_app') and hasattr(self._app.state, 'agent_mcp_manager'):
                await self._app.state.agent_mcp_manager.shutdown()
                self.logger.info("MCP 连接已关闭")
        except Exception as e:
            self.logger.warning("关闭 MCP 连接时出错", error=str(e))

        # 清理 ClawMate sessions
        try:
            if hasattr(self, '_app') and hasattr(self._app.state, 'clawmate_session_manager'):
                manager = self._app.state.clawmate_session_manager
                count = manager.active_count
                if count > 0:
                    self.logger.info("正在清理 ClawMate sessions", active=count)
                    # 清理所有 session
                    for user_id in list(manager._sessions.keys()):
                        manager.destroy(user_id)
                self.logger.info("ClawMate sessions 已清理")
        except Exception as e:
            self.logger.warning("清理 ClawMate sessions 时出错", error=str(e))

        # 关闭数据库引擎连接池
        try:
            await dispose_engine()
            self.logger.info("数据库连接池已关闭")
        except Exception as e:
            self.logger.warning("关闭数据库连接池时出错", error=str(e))

        try:
            if self.redis_connected:
                await close_redis_connection()
                self.logger.info("Redis连接已关闭")
        except Exception as e:
            self.logger.warning("关闭Redis连接时出错", error=str(e))
