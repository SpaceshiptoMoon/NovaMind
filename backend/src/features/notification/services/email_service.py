"""
邮件发送服务

使用 aiosmtplib 异步发送邮件。
SMTP 未配置时静默跳过（仅日志记录）。
"""
from typing import Optional

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """邮件发送服务"""

    @staticmethod
    def _get_smtp_config():
        """获取 SMTP 配置"""
        from src.setting.yaml_config import get_config
        return get_config().smtp

    @staticmethod
    async def send_email(
        to_email: str,
        subject: str,
        html_body: str,
    ) -> bool:
        """
        发送 HTML 邮件

        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            html_body: HTML 邮件正文

        Returns:
            是否发送成功
        """
        smtp_config = EmailService._get_smtp_config()

        if not smtp_config.enabled:
            logger.debug("SMTP 未启用，跳过邮件发送", to=to_email, subject=subject)
            return False

        if not smtp_config.host or not smtp_config.from_email:
            logger.warning("SMTP 配置不完整，跳过邮件发送", to=to_email)
            return False

        try:
            import aiosmtplib
            from email.mime.multipart import MIMEMultipart
            from email.mime.text import MIMEText

            message = MIMEMultipart("alternative")
            message["From"] = smtp_config.from_email
            message["To"] = to_email
            message["Subject"] = subject
            message.attach(MIMEText(html_body, "html", "utf-8"))

            await aiosmtplib.send(
                message,
                hostname=smtp_config.host,
                port=smtp_config.port,
                username=smtp_config.username or None,
                password=smtp_config.password or None,
                start_tls=smtp_config.use_tls,
            )
            logger.info("邮件发送成功", to=to_email, subject=subject)
            return True



        except ImportError:
            logger.warning("aiosmtplib 未安装，无法发送邮件。请运行: pip install aiosmtplib")
            return False
        except Exception as e:
            logger.warning("邮件发送失败", to=to_email, subject=subject, error=str(e))
            return False

    @staticmethod
    async def send_reset_email(to_email: str, reset_link: str, username: str = "") -> bool:
        """
        发送密码重置邮件

        Args:
            to_email: 收件人邮箱
            reset_link: 重置链接
            username: 用户名
        """
        html = f"""
        <div style="max-width:600px;margin:0 auto;font-family:sans-serif;">
            <h2 style="color:#333;">密码重置</h2>
            <p>你好{f' {username}' if username else ''}，</p>
            <p>你正在重置 NovaMind 账户密码。请点击下方按钮完成重置：</p>
            <p style="margin:24px 0;">
                <a href="{reset_link}"
                   style="display:inline-block;padding:12px 24px;background:#409eff;color:#fff;
                          text-decoration:none;border-radius:4px;font-size:16px;">
                    重置密码
                </a>
            </p>
            <p style="color:#999;font-size:14px;">
                此链接 30 分钟内有效。如非本人操作，请忽略此邮件。
            </p>
        </div>
        """
        return await EmailService.send_email(to_email, "NovaMind — 密码重置", html)

    @staticmethod
    async def send_notification_email(to_email: str, title: str, content: str) -> bool:
        """
        发送通用通知邮件

        Args:
            to_email: 收件人邮箱
            title: 通知标题
            content: 通知内容
        """
        html = f"""
        <div style="max-width:600px;margin:0 auto;font-family:sans-serif;">
            <h2 style="color:#333;">{title}</h2>
            <p>{content}</p>
            <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
            <p style="color:#999;font-size:12px;">此邮件由 NovaMind 系统自动发送，请勿回复。</p>
        </div>
        """
        return await EmailService.send_email(to_email, f"NovaMind — {title}", html)
