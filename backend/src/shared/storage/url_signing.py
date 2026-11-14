"""预签名 URL 统一取用入口：同对象同 expires 的签名在窗口内复用。

缓存放在取用入口而不是 ``MinioClient.get_file_url``：客户端封装是最底层
组件，不应持有缓存策略（否则 helpers → client_factory → minio_client →
helpers 会构成静态环，被 import 无环门禁 R1 拦截）。本模块单向依赖
minio_client 与 cache.helpers。

签名是本地 HMAC 计算、对象路径不可变，缓存无一致性问题；附带收益是 URL
字符串在窗口内稳定，前端 img/audio 的浏览器 HTTP 缓存得以命中。
"""
from novamind.shared.cache.helpers import get_or_load

# 安全余量：缓存 TTL = expires - 600，保证返回的 URL 至少还有 10 分钟有效期
PRESIGN_CACHE_MARGIN = 600


async def presigned_get_url(
    minio_client,
    bucket_name: str,
    object_name: str,
    expires: int = 3600,
) -> str:
    """获取预签名 GET URL（带稳定性缓存）。

    Args:
        minio_client: MinioClient 实例（鸭子类型，仅用 get_file_url）。
        bucket_name: 桶名。
        object_name: 对象路径（不可变，是缓存键的一部分）。
        expires: 签名有效期秒数。

    Returns:
        预签名 URL；缓存窗口内同对象返回同一字符串。

    Raises:
        S3Error: 签名失败（失败结果不缓存，每次重试）。
    """
    cache_ttl = expires - PRESIGN_CACHE_MARGIN
    if cache_ttl <= 0:
        # 短签名（不足余量两倍）不值得缓存，直接签
        return await minio_client.get_file_url(bucket_name, object_name, expires)

    async def _sign() -> str:
        return await minio_client.get_file_url(bucket_name, object_name, expires)

    return await get_or_load(
        f"presign:{bucket_name}:{object_name}:{expires}", cache_ttl, _sign
    )
