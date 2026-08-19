# Agent safety: 危险操作检测（E4）
"""engines/agent/safety：危险操作检测 + 审批 hook。"""
from novamind.engines.agent.safety.approval import ApprovalHook, ApprovalRejectedError
from novamind.engines.agent.safety.patterns import detect_dangerous_code

__all__ = ["ApprovalHook", "ApprovalRejectedError", "detect_dangerous_code"]