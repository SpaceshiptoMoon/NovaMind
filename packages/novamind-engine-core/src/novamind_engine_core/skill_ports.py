"""技能引擎中立枚举/值（批次 6a-4 新增，批次 6b 迁入 ``novamind-engine-core``）。

历史背景：``ReviewStatus`` 原定义在 ``features/skill/models/skill.py``（宿主 ORM 模型）。
``skill_checker.py``（技能引擎核心模块，批次 6e 迁 ``novamind-skill-engine``）import 自该
ORM 模型——这是引擎对宿主 feature ORM 的导入边，批次 6 物理抽包前必须切断。

本模块提供引擎自用的中立枚举 ``ReviewStatus``，不依赖宿主 ORM / ``features.*``。
宿主 ``skill/models/skill.py`` 改为从本模块 import 并 re-export，ORM 列
``default=ReviewStatus.PENDING`` 仍引用同一枚举类（``skill.models.skill.ReviewStatus
IS shared.skill_ports.ReviewStatus``），SQLAlchemy 映射与既有 ``from
skill.models.skill import ReviewStatus`` 的导入方零改动。

依赖方向：本模块仅依赖 stdlib ``enum``，零宿主 feature/setting/core 边。
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