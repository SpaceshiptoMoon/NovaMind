"""
技能审查中立枚举 ReviewStatus，供 skill_checker 与宿主 ORM 共享。

宿主 skill/models/skill.py 从此 import 并 re-export，保持 ORM 列 default 引用同一性。
"""
from __future__ import annotations

from enum import IntEnum

__all__ = ["ReviewStatus"]


class ReviewStatus(IntEnum):
    """安全审查状态（技能引擎与宿主共享的中立枚举）。

    值与原 ``skill.models.skill.ReviewStatus`` 逐字一致，保证 DB 已存数据兼容：
    PENDING=0 / APPROVED=1 / SUSPICIOUS=2 / REJECTED=3。
    """

    PENDING = 0
    APPROVED = 1
    SUSPICIOUS = 2
    REJECTED = 3