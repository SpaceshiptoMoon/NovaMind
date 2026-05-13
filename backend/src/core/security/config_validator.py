"""
安全配置验证器

在应用启动时检查生产环境的安全配置是否安全
防止使用默认密钥和密码
"""

import os
import re
from dataclasses import dataclass
from typing import List, Tuple

from src.core.middleware.structured_logging import get_logger


@dataclass
class SecurityIssue:
    """安全问题"""
    level: str  # CRITICAL, WARNING, INFO
    category: str  # JWT, PASSWORD, DATABASE, etc.
    message: str
    recommendation: str
    field_path: str


class SecurityConfigValidator:
    """
    安全配置验证器

    检查以下配置：
    - JWT 密钥强度
    - 默认密码
    - 数据库连接安全
    - 敏感信息硬编码
    """

    # 不安全的默认密钥模式（全部使用全锚定匹配，避免误报）
    # 顺序很重要：短密钥检查必须在最后，避免误匹配
    INSECURE_SECRET_PATTERNS = [
        r"^your-super-secret-key$",  # 常见占位密钥
        r"^secret$",       # 全锚定
        r"^password$",     # 全锚定
        r"^admin$",        # 全锚定
        r"^test$",         # 全锚定
        r"^development$",  # 全锚定
        r"^change-me$",    # 全锚定
        r"^changeme$",     # 全锚定
        r"^default$",      # 全锚定
        r"^.{1,16}$",  # 短密钥（全锚定，必须在最后）
    ]

    # 不安全的默认密码
    INSECURE_PASSWORDS = [
        "admin",
        "***REMOVED***",
        "***REMOVED***",
        "password",
        "123456",
        "root",
        "test",
    ]

    def __init__(self):
        self.logger = get_logger(__name__)
        self.issues: List[SecurityIssue] = []

    def validate(self, config) -> List[SecurityIssue]:
        """
        验证配置安全性

        Args:
            config: AppConfig 配置对象

        Returns:
            List[SecurityIssue]: 安全问题列表
        """
        self.issues = []

        # 检查 JWT 密钥
        self._check_jwt_secret(config)

        # 检查管理员密码
        self._check_admin_password(config)

        # 检查数据库配置
        self._check_database_config(config)

        # 检查 MinIO 配置
        self._check_minio_config(config)

        # 检查 Redis 配置
        self._check_redis_config(config)

        # 检查 CORS 配置
        self._check_cors_config(config)

        # 检查环境变量
        self._check_environment()

        return self.issues

    def _check_jwt_secret(self, config) -> None:
        """检查 JWT 密钥安全性"""
        secret = config.security.secret_key

        # 检查是否为空
        if not secret:
            self.issues.append(SecurityIssue(
                level="CRITICAL",
                category="JWT",
                message="JWT 密钥未配置",
                recommendation="请设置环境变量 SECRET_KEY 或在配置文件中配置 security.secret_key",
                field_path="security.secret_key",
            ))
            return

        # 检查是否为不安全的默认值
        for pattern in self.INSECURE_SECRET_PATTERNS:
            if re.search(pattern, secret, re.IGNORECASE):
                self.issues.append(SecurityIssue(
                    level="CRITICAL",
                    category="JWT",
                    message=f"JWT 密钥使用了不安全的值: {secret[:8]}...",
                    recommendation="请使用强随机密钥，可通过以下命令生成: python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
                    field_path="security.secret_key",
                ))
                break

        # 检查密钥长度
        if len(secret) < 32:
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="JWT",
                message=f"JWT 密钥长度不足 ({len(secret)} 字符)",
                recommendation="建议使用至少 32 字符的随机密钥",
                field_path="security.secret_key",
            ))

    def _check_admin_password(self, config) -> None:
        """检查管理员密码安全性"""
        password = config.admin.password

        # 检查是否为不安全的默认密码
        for insecure_pwd in self.INSECURE_PASSWORDS:
            if password.lower() == insecure_pwd.lower():
                self.issues.append(SecurityIssue(
                    level="CRITICAL",
                    category="PASSWORD",
                    message="管理员密码使用了不安全的默认值",
                    recommendation="请在配置文件中设置强密码或设置环境变量 ADMIN_PASSWORD",
                    field_path="admin.password",
                ))
                break

        # 检查密码复杂度
        if len(password) < 8:
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="PASSWORD",
                message="管理员密码长度不足",
                recommendation="建议使用至少 8 字符的密码，包含大小写字母、数字和特殊字符",
                field_path="admin.password",
            ))

        # 检查是否包含常见模式
        if not re.search(r"[A-Z]", password):
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="PASSWORD",
                message="管理员密码未包含大写字母",
                recommendation="建议密码包含大小写字母、数字和特殊字符",
                field_path="admin.password",
            ))

    def _check_database_config(self, config) -> None:
        """检查数据库配置安全性"""
        db = config.database

        # 检查是否使用空密码
        if not db.password and config.environment == "production":
            self.issues.append(SecurityIssue(
                level="CRITICAL",
                category="DATABASE",
                message="数据库密码为空",
                recommendation="请设置数据库密码",
                field_path="database.password",
            ))

        # 检查是否使用默认用户名
        if db.user == "root" and config.environment == "production":
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="DATABASE",
                message="数据库使用 root 用户",
                recommendation="生产环境建议使用专用数据库用户",
                field_path="database.user",
            ))

    def _check_minio_config(self, config) -> None:
        """检查 MinIO 配置安全性"""
        minio = config.minio

        # 检查是否使用默认凭据
        if minio.access_key == "minioadmin" and minio.secret_key == "minioadmin":
            self.issues.append(SecurityIssue(
                level="CRITICAL",
                category="STORAGE",
                message="MinIO 使用默认凭据 minioadmin/minioadmin",
                recommendation="请在配置文件中设置 MinIO 访问密钥",
                field_path="minio.access_key/minio.secret_key",
            ))

        # 检查是否禁用 SSL
        if not minio.secure and config.environment == "production":
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="STORAGE",
                message="MinIO 未启用 SSL",
                recommendation="生产环境建议启用 SSL (minio.secure: true)",
                field_path="minio.secure",
            ))

    def _check_redis_config(self, config) -> None:
        """检查 Redis 配置安全性"""
        redis = config.redis

        if not redis.enabled:
            return

        # 检查是否未设置密码
        if not redis.password and config.environment == "production":
            self.issues.append(SecurityIssue(
                level="WARNING",
                category="CACHE",
                message="Redis 未设置密码",
                recommendation="生产环境建议设置 Redis 密码",
                field_path="redis.password",
            ))

    def _check_cors_config(self, config) -> None:
        """检查 CORS 配置安全性"""
        cors_origins = getattr(config, "cors_origins", "*")
        if isinstance(cors_origins, str):
            cors_origins = [o.strip() for o in cors_origins.split(",")]

        if "*" in cors_origins:
            if config.environment == "production":
                self.issues.append(SecurityIssue(
                    level="CRITICAL",
                    category="CORS",
                    message="CORS 配置允许所有来源（*），生产环境必须设置具体域名",
                    recommendation="设置环境变量 CORS_ORIGINS 为具体域名，如: https://app.example.com,https://admin.example.com",
                    field_path="cors_origins",
                ))
            else:
                self.issues.append(SecurityIssue(
                    level="WARNING",
                    category="CORS",
                    message="CORS 配置允许所有来源（*），生产环境请设置具体域名",
                    recommendation="上线前设置环境变量 CORS_ORIGINS 为具体域名",
                    field_path="cors_origins",
                ))

    def _check_environment(self) -> None:
        """检查环境变量"""
        # 检查敏感环境变量是否设置
        sensitive_vars = [
            ("SECRET_KEY", "JWT 密钥"),
            ("DB_PASSWORD", "数据库密码"),
            ("ADMIN_PASSWORD", "管理员密码"),
        ]

        for var_name, description in sensitive_vars:
            value = os.getenv(var_name)
            if value is None:
                self.issues.append(SecurityIssue(
                    level="INFO",
                    category="ENV",
                    message=f"环境变量 {var_name} 未设置",
                    recommendation=f"生产环境建议通过环境变量设置 {description}",
                    field_path=f"env.{var_name}",
                ))

    def get_report(self) -> str:
        """获取安全报告"""
        if not self.issues:
            return "✅ 安全配置检查通过"

        lines = ["🔒 安全配置检查报告", "=" * 50]

        # 按严重程度分组
        critical = [i for i in self.issues if i.level == "CRITICAL"]
        warning = [i for i in self.issues if i.level == "WARNING"]
        info = [i for i in self.issues if i.level == "INFO"]

        if critical:
            lines.append(f"\n🔴 严重问题 ({len(critical)})")
            for issue in critical:
                lines.append(f"  [{issue.category}] {issue.message}")
                lines.append(f"    → {issue.recommendation}")

        if warning:
            lines.append(f"\n🟡 警告 ({len(warning)})")
            for issue in warning:
                lines.append(f"  [{issue.category}] {issue.message}")
                lines.append(f"    → {issue.recommendation}")

        if info:
            lines.append(f"\n🔵 提示 ({len(info)})")
            for issue in info:
                lines.append(f"  [{issue.category}] {issue.message}")

        return "\n".join(lines)

    def has_critical_issues(self) -> bool:
        """是否存在严重问题"""
        return any(i.level == "CRITICAL" for i in self.issues)


def validate_security_config(config) -> Tuple[bool, List[SecurityIssue]]:
    """
    验证安全配置

    Args:
        config: AppConfig 配置对象

    Returns:
        Tuple[bool, List[SecurityIssue]]: (是否通过, 问题列表)
    """
    validator = SecurityConfigValidator()
    issues = validator.validate(config)

    # 生产环境严格要求
    if config.environment == "production":
        critical_issues = [i for i in issues if i.level == "CRITICAL"]
        if critical_issues:
            validator.logger.error(
                "生产环境安全配置检查失败",
                issues_count=len(critical_issues),
            )
            return False, issues

    # 非生产环境只警告
    if issues:
        validator.logger.warning(
            "安全配置检查发现问题",
            issues_count=len(issues),
        )

    return True, issues
