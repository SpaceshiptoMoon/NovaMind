"""
时间工具模块

统一使用中国时区（Asia/Shanghai, UTC+8）
所有数据库存储、日志显示均使用中国时间
"""

from datetime import datetime, timezone, timedelta

# 中国时区 UTC+8
CHINA_TZ = timezone(timedelta(hours=8))


def now_china() -> datetime:
    """获取当前中国时间（带时区信息）"""
    return datetime.now(CHINA_TZ)
