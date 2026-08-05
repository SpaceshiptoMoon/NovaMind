"""技能审查中立枚举（feature 间端口，下沉 ``features/skill/ports.py``）。

历史背景：``ReviewStatus`` 原定义在 ``features/skill/models/skill.py``（宿主 ORM 模型）。
``skill_checker.py`` import 自该 ORM 模型——这是引擎对宿主 feature ORM 的导入边，
批次 6 物理抽包时切断。

本模块提供 ``ReviewStatus`` 中立枚举，不依赖宿主 ORM / ``features.*`` 之外的对象。
宿主 ``skill/models/skill.py`` 改为从本模块 import 并 re-export，ORM 列
``default=ReviewStatus.PENDING`` 仍引用同一枚举类（``skill.models.skill.ReviewStatus
IS features.skill.ports.ReviewStatus``），SQLAlchemy 映射与既有 ``from
skill.models.skill import ReviewStatus`` 的导入方零改动。

依赖方向：本模块仅依赖 stdlib ``enum``，零宿主 core/setting 边。
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