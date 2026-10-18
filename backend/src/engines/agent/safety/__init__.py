# Agent safety: 危险操作检测 + 异步审批（E4 + E5）
"""engines/agent/safety：危险操作检测 + 审批 hook + 审批注册表 + 运行中插话队列。"""
from novamind.engines.agent.safety.approval import ApprovalHook, ApprovalRejectedError
from novamind.engines.agent.safety.approval_registry import ApprovalRegistry
from novamind.engines.agent.safety.patterns import detect_dangerous_code
from novamind.engines.agent.safety.steering import SteeringQueue

__all__ = [
    "ApprovalHook",
    "ApprovalRejectedError",
    "ApprovalRegistry",
    "SteeringQueue",
    "detect_dangerous_code",
]