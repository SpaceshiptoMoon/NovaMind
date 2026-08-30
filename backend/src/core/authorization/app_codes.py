"""应用代码注册表（应用级权限门禁）。

三级权限模型的应用层：可被管理员禁用的应用清单及其 API 路由前缀。
前缀来自各 feature manifest 的 ``API_V1_PREFIX`` 挂载路径，两处需同步维护
（新增 feature 或改挂载前缀时更新 ``GATED_APP_PREFIXES``）。

注意：知识空间（spaces）、深研究、测评不进应用门禁——前两者属空间功能，
内容权限由空间成员角色控制；通知/个人设置人人可用。
"""


class AppCode:
    """可门禁的应用代码（封闭枚举，与前端侧边栏过滤共用）。"""

    QA = "qa"
    AGENT = "agent"
    SKILL = "skill"
    APP = "app"  # 应用中心：简历挖掘等
    CLAWMATE = "clawmate"

    ALL = [QA, AGENT, SKILL, APP, CLAWMATE]


# 应用代码 → 该应用的 API 路由前缀（含 manifest 挂载的 API_V1_PREFIX）
GATED_APP_PREFIXES: dict[str, tuple[str, ...]] = {
    AppCode.QA: (
        "/api/v1/qa",
        "/api/v1/ai-chat",
        "/api/v1/sessions",
    ),
    AppCode.AGENT: ("/api/v1/agent",),
    AppCode.SKILL: ("/api/v1/skills",),
    AppCode.APP: ("/api/v1/apps",),
    AppCode.CLAWMATE: ("/api/v1/clawmate",),
}


def match_app_code(path: str) -> str | None:
    """按路径段边界匹配应用代码。

    ``/api/v1/agent`` 与 ``/api/v1/agent/1`` 命中 agent；``/api/v1/agentx``
    不命中（防前缀误匹配）。
    """
    for code, prefixes in GATED_APP_PREFIXES.items():
        for p in prefixes:
            if path == p or path.startswith(p + "/"):
                return code
    return None


__all__ = ["AppCode", "GATED_APP_PREFIXES", "match_app_code"]
