"""预签名 URL 缓存回归测试（get_file_url 层）。

验证不变量：
1. 有效性：同桶同对象同 expires 的签名复用，底层 presigned_get_object 只调一次；
2. 一致性：URL 在缓存窗口内稳定（浏览器 HTTP 缓存可命中）；短 expires 不缓存；
3. 失败方向：签名失败（S3Error）不缓存且原样上抛，下次重试；
4. TTL 语义：回填 TTL = expires - 安全余量。
"""
import json

import pytest
from minio.error import S3Error
from novamind.shared.storage.minio_client import PRESIGN_CACHE_MARGIN, MinioClient

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeMinioSdk:
    """minio SDK 替身：计数签名调用，可注入故障。"""

    def __init__(self):
        self.calls = 0
        self.fail = False

    def presigned_get_object(self, bucket, object_name, expires_delta):
        self.calls += 1
        if self.fail:
            raise S3Error(code="NoSuchKey", message="missing", resource=object_name,
                          request_id="r", host_id="h", response=None)
        return f"https://minio/{bucket}/{object_name}?sig={self.calls}"


@pytest.fixture
def minio_svc(fake_redis):
    svc = MinioClient.__new__(MinioClient)
    svc.client = FakeMinioSdk()
    return svc


async def test_signed_once_and_url_stable(minio_svc, fake_redis):
    first = await minio_svc.get_file_url("bkt", "frames/a.jpg", 3600)
    second = await minio_svc.get_file_url("bkt", "frames/a.jpg", 3600)

    assert first == second, "URL 必须稳定，否则浏览器缓存永不命中"
    assert minio_svc.client.calls == 1
    cached = fake_redis.store["presign:bkt:frames/a.jpg:3600"]
    assert json.loads(cached) == first


async def test_backfill_ttl_keeps_margin(minio_svc, fake_redis):
    await minio_svc.get_file_url("bkt", "f/a.jpg", 3600)
    assert fake_redis.ttls["presign:bkt:f/a.jpg:3600"] == 3600 - PRESIGN_CACHE_MARGIN


async def test_short_expires_not_cached(minio_svc, fake_redis):
    await minio_svc.get_file_url("bkt", "f/short.jpg", 300)
    assert minio_svc.client.calls == 1
    assert "presign:bkt:f/short.jpg:300" not in fake_redis.store


async def test_different_objects_not_shared(minio_svc, fake_redis):
    await minio_svc.get_file_url("bkt", "f/a.jpg", 3600)
    await minio_svc.get_file_url("bkt", "f/b.jpg", 3600)
    assert minio_svc.client.calls == 2


async def test_sign_failure_not_cached_and_raises(minio_svc, fake_redis):
    minio_svc.client.fail = True
    with pytest.raises(S3Error):
        await minio_svc.get_file_url("bkt", "f/missing.jpg", 3600)
    assert "presign:bkt:f/missing.jpg:3600" not in fake_redis.store

    minio_svc.client.fail = False
    url = await minio_svc.get_file_url("bkt", "f/missing.jpg", 3600)
    assert url.startswith("https://minio/"), "失败后重试应正常签名"
