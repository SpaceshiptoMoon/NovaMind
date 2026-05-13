import datetime
import uuid
from decimal import Decimal
from enum import Enum
from sqlalchemy import Column, DateTime
from sqlalchemy.orm import DeclarativeBase, declared_attr
from sqlalchemy.ext.asyncio import AsyncEngine

from src.shared.utils.time_utils import now_china


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 风格的声明式基类"""
    pass


def _get_china_now() -> datetime.datetime:
    """获取当前中国时间（UTC+8）"""
    return now_china()


class BaseModel(Base):
    __abstract__ = True
    created_at = Column(DateTime, default=_get_china_now, nullable=False)
    updated_at = Column(DateTime,
                       default=_get_china_now,
                       onupdate=_get_china_now,  # 注意：仅在 ORM 实例更新时触发，批量 session.execute(update(...)) 需手动设置此字段
                       nullable=False)

    @declared_attr
    def __tablename__(cls) -> str:
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
    """创建所有数据库表"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
