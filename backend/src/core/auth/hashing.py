import asyncio

from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码是否匹配（同步版本，供特殊场景使用）"""
    if not plain_password or not hashed_password:
        return False
    try:
        return ph.verify(hashed_password, plain_password)
    except Exception:
        # 认证场景下任何异常（密码不匹配、哈希格式错误、参数不兼容等）都视为验证失败
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（同步版本，供特殊场景使用）"""
    return ph.hash(password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """异步验证密码，不阻塞事件循环"""
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


async def get_password_hash_async(password: str) -> str:
    """异步生成密码哈希，不阻塞事件循环"""
    return await asyncio.to_thread(get_password_hash, password)

