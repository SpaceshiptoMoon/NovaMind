"""应用代码注册表（应用级权限门禁）。

GATED_APP_PREFIXES 前缀与各 feature manifest 的挂载前缀两处需同步维护：新增 feature 或改挂载路径时更新此表。
当前无可门禁应用（agent/skill/app 已随工作台剥离移除），表为空 = 门禁全放行。
"""


class AppCode:
    """可门禁的应用代码（封闭枚举，与前端侧边栏过滤共用）。"""

    ALL: list[str] = []


# 应用代码 → 该应用的 API 路由前缀（含 manifest 挂载的 API_V1_PREFIX）
GATED_APP_PREFIXES: dict[str, tuple[str, ...]] = {}


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
