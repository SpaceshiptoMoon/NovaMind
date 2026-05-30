"""
敏感数据脱敏工具

用于上下文压缩摘要前脱敏 API Key、Token、密码等敏感数据，
防止泄露到持久化的 agent_context_summaries 表。
"""
import re
from typing import List, Tuple

# 敏感数据模式：(正则, 替换模板)
_SENSITIVE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # API Key / Token / Secret 格式
    (re.compile(r'(api[_-]?key|apikey|access[_-]?token|secret[_-]?key|auth[_-]?token)\s*[:=]\s*["\']?[\w\-]{8,}["\']?', re.IGNORECASE), '[REDACTED]'),
    # Bearer Token
    (re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.IGNORECASE), 'Bearer [REDACTED]'),
    # 长字符串形式的 key（44+ 字符的 base64 或 hex）
    (re.compile(r'(sk-|sk_live_|pk_live_|rk-)[A-Za-z0-9]{20,}', re.IGNORECASE), '[REDACTED_KEY]'),
    # password = / password: 格式
    (re.compile(r'(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']{4,}["\']?', re.IGNORECASE), r'\1=[REDACTED]'),
    # connection string
    (re.compile(r'(mongodb|mysql|postgres|redis)://[^\s]+', re.IGNORECASE), r'\1://[REDACTED]'),
    # 私钥块
    (re.compile(r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----[\s\S]*?-----END\s+(RSA\s+)?PRIVATE\s+KEY-----', re.IGNORECASE), '[REDACTED_PRIVATE_KEY]'),
]


def redact_sensitive_text(text: str) -> str:
    """脱敏文本中的敏感数据"""
    if not text:
        return text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text
