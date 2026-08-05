"""
记忆安全扫描

在记忆写入前检测潜在的注入攻击和数据泄露模式。
"""
import re
from typing import List, Tuple

# 注入攻击模式：(正则, 威胁 ID)
_INJECTION_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # 指令注入
    (re.compile(r'ignore\s+(all\s+)?previous\s+instructions?', re.IGNORECASE), 'instruction_injection'),
    (re.compile(r'forget\s+(all\s+)?(your\s+)?(previous|above|prior)\s+(instructions?|rules?|memory|context)', re.IGNORECASE), 'instruction_injection'),
    (re.compile(r'you\s+are\s+now\s+a?\s*(different|new|evil|malicious|unrestricted)', re.IGNORECASE), 'role_hijack'),
    (re.compile(r'system\s*:\s*', re.IGNORECASE), 'system_prefix_injection'),
    (re.compile(r'do\s+not\s+tell\s+the\s+user', re.IGNORECASE), 'deception_hide'),
    (re.compile(r'system\s+prompt\s+override', re.IGNORECASE), 'sys_prompt_override'),
    (re.compile(r'disregard\s+(your|all|any)\s+(instructions?|rules?|guidelines?)', re.IGNORECASE), 'disregard_rules'),
    (re.compile(r'act\s+as\s+if\s+you\s+have\s+no\s+(restrictions?|limits?|rules?)', re.IGNORECASE), 'bypass_restrictions'),
    # 数据泄露
    (re.compile(r'(exfiltrate|steal|leak|send\s+(all\s+)?(data|memory|conversation))', re.IGNORECASE), 'exfiltration'),
    (re.compile(r'(curl|wget|fetch)\s+.*\$(KEY|TOKEN|SECRET|PASSWORD|API_KEY)', re.IGNORECASE), 'exfil_curl'),
    (re.compile(r'(curl|wget|fetch)\s+https?://\S+', re.IGNORECASE), 'exfil_network'),
    (re.compile(r'cat\s+\.env|cat\s+credentials|cat\s+\.netrc', re.IGNORECASE), 'read_secrets'),
]

# 不可见 Unicode 范围
_INVISIBLE_UNICODE_RANGES = [
    (0x200B, 0x200D),  # Zero-width space, joiner, non-joiner
    (0x2060, 0x2060),  # Word joiner
    (0xFEFF, 0xFEFF),  # BOM
    (0x202A, 0x202E),  # RTL/LTR overrides
]


class MemorySecurityScanResult:
    """安全扫描结果"""

    def __init__(self, is_safe: bool, threats: List[str] = None):
        self.is_safe = is_safe
        self.threats = threats or []

    def __bool__(self) -> bool:
        return self.is_safe


def scan_memory_content(content: str) -> MemorySecurityScanResult:
    """扫描记忆内容是否安全"""
    if not content:
        return MemorySecurityScanResult(is_safe=True)

    threats = []

    # 模式匹配
    for pattern, threat_id in _INJECTION_PATTERNS:
        if pattern.search(content):
            threats.append(threat_id)

    # 不可见 Unicode 检测
    for char in content:
        cp = ord(char)
        for start, end in _INVISIBLE_UNICODE_RANGES:
            if start <= cp <= end:
                threats.append('invisible_unicode')
                break
        if 'invisible_unicode' in threats:
            break

    if threats:
        return MemorySecurityScanResult(is_safe=False, threats=threats)
    return MemorySecurityScanResult(is_safe=True)
