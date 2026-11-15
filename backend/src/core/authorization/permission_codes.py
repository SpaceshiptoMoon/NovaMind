"""系统功能权限码枚举。管理员只能组合这些预定义权限到角色，不可新增。"""


class SystemPermission:
    """系统功能权限码常量集（封闭集合，管理员只能将其组合到角色，不可新增）。"""

    USER_MANAGE = "user.manage"
    ROLE_MANAGE = "role.manage"

    # skill.review/skill.config/agent.manage_system 已随 2026-11-15 工作台剥离移除；
    # DB 存量行由一次性清理脚本回收
    ALL = [USER_MANAGE, ROLE_MANAGE]


# 预置角色 → 权限映射（三级全局模型：admin / viewer；最高管理员由 users.is_super_admin 标记区分，
# 不单独设角色。editor 角色已废弃，存量用户由 startup._deprecate_editor_role 迁移至 viewer）
PRESET_ROLE_PERMISSIONS = {
    "admin": SystemPermission.ALL,
    "viewer": [],
}
