"""
路由管理器模块
负责管理和注册所有应用路由
支持 API 版本控制
"""
from typing import List, Dict
from fastapi import APIRouter

# API 版本前缀
API_V1_PREFIX = "/api/v1"


class RouterManager:
    """路由管理器"""

    def __init__(self):
        self.routers: Dict[str, APIRouter] = {}
        self._register_routers()

    def _register_routers(self):
        """注册所有路由（延迟导入，避免启动时加载全部依赖）"""
        # 功能模块路由
        from src.features.qa.api.qa_routes import router as qa_router
        from src.features.qa.api.ai_chat_routes import router as ai_chat_router
        from src.features.qa.api.session_config_routes import router as session_config_router
        from src.features.user.api.user_routes import router as user_router
        from src.features.user.api.model_config_routes import router as model_config_router
        from src.core.middleware.health_check import router as health_router

        # 知识空间模块路由
        from src.features.knowledge_space.api.space_router import router as space_router
        from src.features.knowledge_space.api.knowledge_base_routes import router as knowledge_base_router
        from src.features.knowledge_space.api.document_routes import router as document_router
        from src.features.knowledge_space.api.member_routes import router as member_router
        from src.features.knowledge_space.api.search_routes import router as search_router

        # 深度研究模块路由
        from src.features.deep_research.api.routes import router as deep_research_router

        # 测评模块路由
        from src.features.evaluation.api.routes import router as evaluation_router

        # Agent 模块路由
        from src.features.agent.api.routes import router as agent_router

        # 技能广场路由
        from src.features.skill.api.routes import router as skill_router

        # 应用中心路由
        from src.features.app.api.routes import router as app_router

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
        })

    def get_router(self, name: str) -> APIRouter:
        """获取指定的路由"""
        return self.routers.get(name)

    def get_all_routers(self) -> List[tuple]:
        """
        获取所有路由及其配置

        Returns:
            List[tuple]: 路由配置列表，每个元素为 (router, prefix, tags)
        """
        router_configs = []

        # 系统路由（无版本前缀）
        router_configs.append((self.routers.get("health"), "", ["健康检查"]))

        # 功能路由（带 v1 版本前缀）
        prefix_mapping = {
            "qa": f"{API_V1_PREFIX}/qa",
            "ai_chat": f"{API_V1_PREFIX}/ai-chat",
            "session_config": f"{API_V1_PREFIX}/sessions/{{session_id}}/config",
            "user": f"{API_V1_PREFIX}/user",
            "model_config": f"{API_V1_PREFIX}/user",
            # 知识空间模块（嵌套路由，注意顺序和前缀）
            "space": f"{API_V1_PREFIX}/spaces",
            "space_kb": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
            "space_document": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases",
            "space_member": f"{API_V1_PREFIX}/spaces/{{space_id}}/members",
            "space_search": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/search",
            # 深度研究模块
            "deep_research": f"{API_V1_PREFIX}/spaces/{{space_id}}/deep-research",
            # 测评模块
            "evaluation": f"{API_V1_PREFIX}/spaces/{{space_id}}/knowledge-bases/{{kb_id}}/evaluation",
            # Agent 模块
            "agent": f"{API_V1_PREFIX}/agent",
            # 技能广场
            "skills": f"{API_V1_PREFIX}/skills",
            # 应用中心
            "apps": f"{API_V1_PREFIX}/apps",
        }

        tag_mapping = {
            "qa": "智能问答",
            "ai_chat": "AI 聊天",
            "session_config": "会话配置",
            "user": "用户管理",
            "model_config": "模型配置",
            # 知识空间模块
            "space": "知识空间",
            "space_kb": "知识库管理",
            "space_document": "文档管理",
            "space_member": "空间成员",
            "space_search": "知识检索",
            # 深度研究模块
            "deep_research": "深度研究",
            # 测评模块
            "evaluation": "知识库测评",
            # Agent 模块
            "agent": "Agent 智能体",
            # 技能广场
            "skills": "技能广场",
            # 应用中心
            "apps": "应用中心",
        }

        for name, router in self.routers.items():
            if name in prefix_mapping:
                router_configs.append((
                    router,
                    prefix_mapping[name],
                    [tag_mapping[name]]
                ))

        return router_configs