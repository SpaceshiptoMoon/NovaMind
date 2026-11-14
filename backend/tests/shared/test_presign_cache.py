"""预签名 URL 缓存回归测试（shared/storage/url_signing 层）。

验证不变量：
1. 有效性：同桶同对象同 expires 的签名复用，底层 get_file_url 只调一次；
2. 一致性：URL 在缓存窗口内稳定（浏览器 HTTP 缓存可命中）；短 expires 不缓存；
3. 失败方向：签名失败（S3Error）不缓存且原样上抛，下次重试；
4. TTL 语义：回填 TTL = expires - 安全余量。
"""
import json

import pytest
from minio.error import S3Error
from novamind.shared.storage.url_signing import (
    PRESIGN_CACHE_MARGIN,
    presigned_get_url,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class FakeMinioClient:
    """MinioClient 鸭子替身：计数签名调用，可注入故障。"""

    def __init__(self):
        self.calls = 0
        self.fail = False

    async def get_file_url(self, bucket_name, object_name, expires=3600):
        self.calls += 1
        if self.fail:
            raise S3Error(code="NoSuchKey", message="missing", resource=object_name,
                          request_id="r", host_id="h", response=None)
        return f"https://minio/{bucket_name}/{object_name}?sig={self.calls}"


@pytest.fixture
def mc(fake_redis):
    return FakeMinioClient()


async def test_signed_once_and_url_stable(mc, fake_redis):
    first = await presigned_get_url(mc, "bkt", "frames/a.jpg", 3600)
    second = await presigned_get_url(mc, "bkt", "frames/a.jpg", 3600)

    assert first == second, "URL 必须稳定，否则浏览器缓存永不命中"
    assert mc.calls == 1
    assert json.loads(fake_redis.store["presign:bkt:frames/a.jpg:3600"]) == first


async def test_backfill_ttl_keeps_margin(mc, fake_redis):
    await presigned_get_url(mc, "bkt", "f/a.jpg", 3600)
    assert fake_redis.ttls["presign:bkt:f/a.jpg:3600"] == 3600 - PRESIGN_CACHE_MARGIN


async def test_short_expires_not_cached(mc, fake_redis):
    await presigned_get_url(mc, "bkt", "f/short.jpg", 300)
    assert mc.calls == 1
    assert "presign:bkt:f/short.jpg:300" not in fake_redis.store


async def test_different_objects_not_shared(mc, fake_redis):
    await presigned_get_url(mc, "bkt", "f/a.jpg", 3600)
    await presigned_get_url(mc, "bkt", "f/b.jpg", 3600)
    assert mc.calls == 2


async def test_sign_failure_not_cached_and_raises(mc, fake_redis):
    mc.fail = True
    with pytest.raises(S3Error):
        await presigned_get_url(mc, "bkt", "f/missing.jpg", 3600)
    assert "presign:bkt:f/missing.jpg:3600" not in fake_redis.store

    mc.fail = False
    url = await presigned_get_url(mc, "bkt", "f/missing.jpg", 3600)
    assert url.startswith("https://minio/"), "失败后重试应正常签名"
