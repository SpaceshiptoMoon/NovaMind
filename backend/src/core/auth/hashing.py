"""密码哈希工具：Argon2id（异步包装防事件循环阻塞）。"""
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
    """验证密码是否匹配（Argon2id，同步版本供特殊场景使用）。

    Args:
        plain_password: 用户输入的明文密码。
        hashed_password: 库中存储的 Argon2 哈希。

    Returns:
        匹配返回 True；任一入参为空、格式错误或不匹配一律返回 False（认证场景不抛异常）。
    """
    if not plain_password or not hashed_password:
        return False
    try:
        return ph.verify(hashed_password, plain_password)
    except Exception:
        # 认证场景下任何异常（密码不匹配、哈希格式错误、参数不兼容等）都视为验证失败
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（Argon2id，同步版本供特殊场景使用）。

    Args:
        password: 明文密码。

    Returns:
        Argon2id 哈希字符串（含盐与参数）。
    """
    return ph.hash(password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    """异步验证密码（Argon2 计算下放线程池，不阻塞事件循环）。

    Args:
        plain_password: 用户输入的明文密码。
        hashed_password: 库中存储的 Argon2 哈希。

    Returns:
        匹配返回 True；不匹配或格式异常返回 False。
    """
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


async def get_password_hash_async(password: str) -> str:
    """异步生成密码哈希（Argon2 计算下放线程池，不阻塞事件循环）。

    Args:
        password: 明文密码。

    Returns:
        Argon2id 哈希字符串（含盐与参数）。
    """
    return await asyncio.to_thread(get_password_hash, password)

