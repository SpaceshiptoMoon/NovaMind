"""arq 队列名单一出处回归测试。

回归背景：pool 创建未传 default_queue_name（enqueue 恒落 arq 默认队列），而
三处消费方 ``getattr(pool, "queue_name", "arq:queue")`` 找的属性在 ArqRedis 上
不存在（只有 default_queue_name），恒走 fallback——自定义队列名配置下
enqueue 与 purge/存活探针将操作不同队列，任务静默无人认领。

验证核心不变量：
1. get_arq_pool 创建时传配置队列名（与 worker 侧 create_embedded_worker 同源）；
2. get_queue_name 读 pool.default_queue_name（禁止不存在的 queue_name 属性名）；
3. 单例复用：二次获取不重建。
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import arq
import novamind.shared.mq as mq_module

pytestmark = pytest.mark.unit


class _RecordingArqRedis:
    """记录构造参数的最小 ArqRedis 替身。"""

    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        _RecordingArqRedis.last_kwargs = kwargs


@pytest.mark.asyncio
async def test_get_arq_pool_passes_configured_queue_name(monkeypatch):
    """pool 创建必须传配置里的队列名（enqueue 与消费两侧同源）。"""
    import novamind.setting.yaml_config as yaml_config_module
    from novamind.shared.storage import client_factory

    async def _fake_redis():
        return SimpleNamespace(redis_client=SimpleNamespace(connection_pool=object()))

    monkeypatch.setattr(client_factory, "get_redis_client", _fake_redis)
    monkeypatch.setattr(
        yaml_config_module,
        "get_config",
        lambda: SimpleNamespace(task_queue=SimpleNamespace(queue_name="custom:queue")),
    )
    monkeypatch.setattr(arq, "ArqRedis", _RecordingArqRedis)
    monkeypatch.setattr(mq_module, "_arq_pool", None)

    pool = await mq_module.get_arq_pool()

    assert _RecordingArqRedis.last_kwargs is not None
    assert _RecordingArqRedis.last_kwargs["default_queue_name"] == "custom:queue"
    # 单例：二次获取返回同一实例，不重复创建
    assert await mq_module.get_arq_pool() is pool


def test_get_queue_name_reads_default_queue_name():
    """队列名从 arq 真实属性 default_queue_name 取（queue_name 属性不存在）。"""
    pool = SimpleNamespace(default_queue_name="cfg:queue")
    assert mq_module.get_queue_name(pool) == "cfg:queue"
