"""ORM 基类与公共模型混入：时间戳/软删除列，全部模型的声明根。"""
import datetime
import uuid
from decimal import Decimal
from enum import Enum

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.utils.time_utils import now_china
from sqlalchemy import Column, DateTime
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import DeclarativeBase, declared_attr

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 风格的声明式基类"""
    __table_args__ = {
        "mysql_charset": "utf8mb4",
        "mysql_collate": "utf8mb4_unicode_ci",
    }


def _get_china_now() -> datetime.datetime:
    """获取当前中国时间（UTC+8）"""
    return now_china()


class BaseModel(Base):
    """业务模型公共抽象基类：自动携带 created_at / updated_at 中国时间时间戳列与统一表名推导。"""
    __abstract__ = True
    created_at = Column(DateTime, default=_get_china_now, nullable=False)
    updated_at = Column(DateTime,
                       default=_get_china_now,
                       onupdate=_get_china_now,  # 注意：仅在 ORM 实例更新时触发，批量 session.execute(update(...)) 需手动设置此字段
                       nullable=False)

    @declared_attr
    def __tablename__(cls) -> str:
        """表名推导：类名小写 + s（未显式声明 __tablename__ 时的默认）。"""
        return cls.__name__.lower() + "s"

    def to_dict(self) -> dict:
        """
        将模型转换为字典

        使用类级别缓存避免每次调用时反射 __table__.columns

        Returns:
            包含所有列值的字典
        """
        # 缓存列名列表，避免每次反射
        if not hasattr(self.__class__, '_columns_cache'):
            self.__class__._columns_cache = [c.name for c in self.__table__.columns]

        result = {}
        for col_name in self.__class__._columns_cache:
            value = getattr(self, col_name, None)
            # 处理特殊类型
            if isinstance(value, datetime.datetime):
                value = value.isoformat()
            elif isinstance(value, datetime.date):
                value = value.isoformat()
            elif isinstance(value, Decimal):
                value = float(value)
            elif isinstance(value, uuid.UUID):
                value = str(value)
            elif isinstance(value, Enum):  # Enum 类型
                value = value.value
            result[col_name] = value
        return result


async def create_tables(engine: AsyncEngine) -> None:
    """按当前 metadata 全量建表（create_all 不做 ALTER，已有表结构变更走启动期幂等补列钩子）。

    Args:
        engine: SQLAlchemy 异步引擎（事务在其 begin 块内执行）。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


