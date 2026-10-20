"""本地工作区数据模型：RunnerDevice（伴生 runner 设备注册）。

WorkspaceBinding（会话↔工作区绑定）属 P1，随写入能力一起落地。
"""
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, String

from novamind.core.database.base import BaseModel


class RunnerDevice(BaseModel):
    """伴生 runner 设备：一次配对一条记录，device_key 哈希作重连凭证"""

    __tablename__ = "runner_devices"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False, comment="属主用户ID")
    name = Column(String(100), nullable=False, default="未命名设备", comment="用户可改的设备别名")
    device_key_hash = Column(String(128), nullable=False, comment="持久密钥哈希（重连凭证，绝不存明文）")
    os_type = Column(String(20), nullable=False, default="unknown", comment="windows/darwin/linux")
    version = Column(String(30), nullable=False, default="0.0.0", comment="runner 版本号")
    status = Column(String(20), nullable=False, default="offline", comment="online/offline/revoked")
    last_seen_at = Column(DateTime, nullable=True, comment="最后活跃时间")

    __table_args__ = (
        Index("idx_runner_devices_user", "user_id"),
        {"comment": "伴生 runner 设备注册表"},
    )

    def __repr__(self) -> str:
        return f"<RunnerDevice(id={self.id}, name='{self.name}', status='{self.status}')>"
