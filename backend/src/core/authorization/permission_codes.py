"""系统功能权限码枚举。管理员只能组合这些预定义权限到角色，不可新增。"""


class SystemPermission:
    USER_MANAGE = "user.manage"
    SKILL_REVIEW = "skill.review"
    SKILL_CONFIG = "skill.config"
    AGENT_MANAGE_SYSTEM = "agent.manage_system"
    ROLE_MANAGE = "role.manage"

    ALL = [USER_MANAGE, SKILL_REVIEW, SKILL_CONFIG, AGENT_MANAGE_SYSTEM, ROLE_MANAGE]


# 预置角色 → 权限映射
PRESET_ROLE_PERMISSIONS = {
    "admin": SystemPermission.ALL,
    "editor": [SystemPermission.AGENT_MANAGE_SYSTEM],
    "viewer": [],
}
