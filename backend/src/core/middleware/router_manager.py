"""
路由管理器模块
负责管理和注册所有应用路由，支持 API 版本控制。

批次 1 起，路由来源由「硬编码三张表」（router 对象 dict + prefix_mapping + tag_mapping）
改为从 feature manifest 聚合：`get_all_routers()` 调 `manifest_loader.get_route_sorted_manifests()`
按 `route_order` 遍历各 `FeatureManifest.routers`，产出 (router, prefix, [tag])。

**路由注册顺序与初始化拓扑序分离**：路由注册顺序决定 FastAPI 对同名 Pydantic
响应模型的去重胜出者，必须与 legacy 硬编码顺序逐字一致（否则 openapi 中碰撞 schema
翻转，破坏前端契约），故用 `route_order`（匹配 legacy 路由序）；初始化仍用拓扑序
`order`。两者由 manifest_loader 分别提供。

契约不变：`get_all_routers()` 仍返回 `List[tuple]`，每个元素为 (router, prefix, tags)，
prefix/tag 与改造前逐字一致，确保 `GET /openapi.json` 逐字不变（前端契约源头）。

回滚：设置环境变量 `NOVAMIND_LEGACY_MANIFEST=1` 走旧的硬编码 `_register_routers_legacy`
路径，manifest 路径与新拓扑初始化可独立回滚。
"""
import os
from typing import Dict, List, Tuple

from fastapi import APIRouter

from novamind.core.middleware.manifest import API_V1_PREFIX
from novamind.core.middleware.manifest_loader import get_route_sorted_manifests


class RouterManager:
    """路由管理器"""

    def __init__(self):
        self.routers: Dict[str, APIRouter] = {}
        if os.getenv("NOVAMIND_LEGACY_MANIFEST") == "1":
            self._register_routers_legacy()
        # manifest 路径无需在此预加载 router 对象；get_all_routers 时按需聚合

    # ==================== manifest 聚合路径（默认） ====================

    def get_router(self, name: str) -> APIRouter:
        """获取指定的路由（仅 legacy 路径填充 self.routers；manifest 路径返回 None）"""
        return self.routers.get(name)

    def get_all_routers(self) -> List[Tuple[APIRouter, str, List[str]]]:
        """
        获取所有路由及其配置。

        Returns:
            List[tuple]: 路由配置列表，每个元素为 (router, prefix, tags)

        逐字复刻原 get_all_routers 的产出：每条 (router, prefix, [tag])，prefix 与 tag
        来自 manifest 的 RouterSpec（与原 prefix_mapping/tag_mapping 一致）。health
        路由（system manifest，prefix=""）随其 route_order=0 排在最前，与原显式 append
        行为一致。按 `route_order` 遍历（匹配 legacy 路由注册序），而非初始化拓扑序。
        """
        if os.getenv("NOVAMIND_LEGACY_MANIFEST") == "1" and self.routers:
            return self._get_all_routers_legacy()

        router_configs: List[Tuple[APIRouter, str, List[str]]] = []
        for m in get_route_sorted_manifests():
            if not m.enabled:
                continue
            for spec in m.routers:
                router_configs.append((spec.router, spec.prefix, [spec.tag]))
        return router_configs

    # ==================== legacy 硬编码路径（回滚用） ====================

    def _register_routers_legacy(self):
        """旧硬编码路由注册（仅 NOVAMIND_LEGACY_MANIFEST=1 时使用，保留作回滚）"""
        # 功能模块路由
        from novamind.features.qa.api.qa_routes import router as qa_router
        from novamind.features.qa.api.ai_chat_routes import router as ai_chat_router
        from novamind.features.qa.api.session_config_routes import router as session_config_router
        from novamind.features.user.api.user_routes import router as user_router
        from novamind.features.user.api.model_config_routes import router as model_config_router
        from novamind.core.middleware.health_check import router as health_router

        # 知识空间模块路由
        from novamind.features.knowledge_space.api.space_router import router as space_router
        from novamind.features.knowledge_space.api.knowledge_base_routes import router as knowledge_base_router
        from novamind.features.knowledge_space.api.document_routes import router as document_router
        from novamind.features.knowledge_space.api.member_routes import router as member_router
        from novamind.features.knowledge_space.api.search_routes import router as search_router

        # 深度研究模块路由
        from novamind.features.deep_research.api.routes import router as deep_research_router

        # 测评模块路由
        from novamind.features.evaluation.api.routes import router as evaluation_router

        # Agent 模块路由
        from novamind.features.agent.api.routes import router as agent_router

        # 技能广场路由
        from novamind.features.skill.api.routes import router as skill_router

        # 应用中心路由
        from novamind.features.app.api.routes import router as app_router

        # 通知模块路由
        from novamind.features.notification.api.routes import router as notification_router

        # ClawMate 终端模块路由
        from novamind.features.clawmate.api.routes import router as clawmate_router

        self.routers.update({
            "qa": qa_router,
            "ai_chat": ai_chat_router,
            "session_config": session_config_router,
            "user": user_router,
            "model_config": model_config_router,
            "health": health_router,
            # 知识空间模块
            "space": space_router,
            "space_kb": knowledge_base_router,
            "space_document": document_router,
            "space_member": member_router,
            "space_search": search_router,
            # 深度研究模块
            "deep_research": deep_research_router,
            # 测评模块
            "evaluation": evaluation_router,
            # Agent 模块
            "agent": agent_router,
            # 技能广场
            "skills": skill_router,
            # 应用中心
            "apps": app_router,
            # 通知模块
            "notifications": notification_router,
            # ClawMate 终端模块
            "clawmate": clawmate_router,
        })

    def _get_all_routers_legacy(self) -> List[Tuple[APIRouter, str, List[str]]]:
        """旧 get_all_routers 实现（仅 legacy 路径使用）"""
        router_configs: List[Tuple[APIRouter, str, List[str]]] = []

        # 系统路由（无版本前缀）
        router_configs.append((self.routers.get("health"), "", ["健康检查"]))

        prefix_mapping = {
            "qa": f"{API_V1_PREFIX}/qa",
            "ai_chat": f"{API_V1_PREFIX}/ai-chat",
            "session_config": f"{API_V1_PREFIX}/sessions/{{session_id}}/config",
            "user": f"{API_V1_PREFIX}/user",
            "model_config": f"{API_V1_PREFIX}/user",
            "space": f"{API_V1_PREFIX}/spaces",
            "space_kb": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
            "space_document": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
            "space_member": f"{API_V1_PREFIX}/spaces/{{space_id}}/members",
            "space_search": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/search",
            "deep_research": f"{API_V1_PREFIX}/spaces/{{space_id}}/deep-research",
            "evaluation": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/evaluation",
            "agent": f"{API_V1_PREFIX}/agent",
            "skills": f"{API_V1_PREFIX}/skills",
            "apps": f"{API_V1_PREFIX}/apps",
            "notifications": f"{API_V1_PREFIX}/notifications",
            "clawmate": f"{API_V1_PREFIX}/clawmate",
        }

        tag_mapping = {
            "qa": "智能问答",
            "ai_chat": "AI 聊天",
            "session_config": "会话配置",
            "user": "用户管理",
            "model_config": "模型配置",
            "space": "知识空间",
            "space_kb": "知识库管理",
            "space_document": "文档管理",
            "space_member": "空间成员",
            "space_search": "知识检索",
            "deep_research": "深度研究",
            "evaluation": "知识库测评",
            "agent": "Agent 智能体",
            "skills": "技能广场",
            "apps": "应用中心",
            "notifications": "通知",
            "clawmate": "ClawMate 终端",
        }

        for name, router in self.routers.items():
            if name in prefix_mapping:
                router_configs.append((
                    router,
                    prefix_mapping[name],
                    [tag_mapping[name]],
                ))

        return router_configs