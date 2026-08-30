"""系统功能权限码枚举。管理员只能组合这些预定义权限到角色，不可新增。"""


class SystemPermission:
    USER_MANAGE = "user.manage"
    SKILL_REVIEW = "skill.review"
    SKILL_CONFIG = "skill.config"
    AGENT_MANAGE_SYSTEM = "agent.manage_system"
    ROLE_MANAGE = "role.manage"

    ALL = [USER_MANAGE, SKILL_REVIEW, SKILL_CONFIG, AGENT_MANAGE_SYSTEM, ROLE_MANAGE]


# 预置角色 → 权限映射（三级全局模型：admin / viewer；最高管理员由 users.is_super_admin 标记区分，
# 不单独设角色。editor 角色已废弃，存量用户由 startup._deprecate_editor_role 迁移至 viewer）
PRESET_ROLE_PERMISSIONS = {
    "admin": SystemPermission.ALL,
    "viewer": [],
}
