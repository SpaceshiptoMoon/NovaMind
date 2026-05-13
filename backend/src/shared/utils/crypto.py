"""
AES-256-CBC 加解密工具

用于 API Key 的加密存储和解密读取
"""
import asyncio
import base64
import hashlib
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.backends import default_backend


def _get_encryption_key() -> bytes:
    """从配置获取加密密钥，派生为 32 字节 AES 密钥"""
    from src.setting.yaml_config import get_config

    config = get_config()
    raw_key = config.security.encryption_key

    if not raw_key:
        raise ValueError("未配置加密密钥（security.encryption_key），请在 YAML 配置中设置")

    # 使用 SHA-256 派生固定 32 字节密钥
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def encrypt_api_key(plain_text: str, key: Optional[str] = None) -> str:
    """
    AES-256-CBC 加密

    Args:
        plain_text: 明文 API Key
        key: 加密密钥（可选，默认从配置读取）

    Returns:
        Base64 编码的密文（格式：Base64(IV + 密文)）
    """
    if not plain_text:
        return ""

    # 获取密钥
    if key:
        aes_key = hashlib.sha256(key.encode("utf-8")).digest()
    else:
        aes_key = _get_encryption_key()

    # 生成随机 IV（16 字节）
    iv = os.urandom(16)

    # PKCS7 填充
    padder = crypto_padding.PKCS7(128).padder()
    padded_data = padder.update(plain_text.encode("utf-8")) + padder.finalize()

    # AES-256-CBC 加密
    cipher = Cipher(
        algorithms.AES(aes_key),
        modes.CBC(iv),
        backend=default_backend(),
    )
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded_data) + encryptor.finalize()

    # 返回 Base64(IV + 密文)
    return base64.b64encode(iv + ciphertext).decode("utf-8")


def decrypt_api_key(cipher_text: str, key: Optional[str] = None) -> str:
    """
    AES-256-CBC 解密

    Args:
        cipher_text: Base64 编码的密文（格式：Base64(IV + 密文)）
        key: 加密密钥（可选，默认从配置读取）

    Returns:
        明文 API Key
    """
    if not cipher_text:
        return ""

    # 获取密钥
    if key:
        aes_key = hashlib.sha256(key.encode("utf-8")).digest()
    else:
        aes_key = _get_encryption_key()

    # Base64 解码
    raw_data = base64.b64decode(cipher_text)

    # 提取 IV（前 16 字节）和密文
    iv = raw_data[:16]
    ciphertext = raw_data[16:]

    # AES-256-CBC 解密
    cipher = Cipher(
        algorithms.AES(aes_key),
        modes.CBC(iv),
        backend=default_backend(),
    )
    decryptor = cipher.decryptor()
    padded_data = decryptor.update(ciphertext) + decryptor.finalize()

    # PKCS7 去填充
    unpadder = crypto_padding.PKCS7(128).unpadder()
    plain_data = unpadder.update(padded_data) + unpadder.finalize()

    return plain_data.decode("utf-8")


def mask_api_key(api_key: str) -> str:
    """
    脱敏 API Key

    Args:
        api_key: 明文或密文 API Key

    Returns:
        脱敏后的字符串（如 sk-****xxxx）
    """
    if not api_key:
        return ""

    # 如果是明文 key，直接脱敏
    if len(api_key) <= 8:
        return "****"

    # 显示前 3 个字符 + **** + 后 4 个字符
    return f"{api_key[:3]}****{api_key[-4:]}"


async def encrypt_api_key_async(plain_text: str, key: Optional[str] = None) -> str:
    """异步 AES-256-CBC 加密，不阻塞事件循环"""
    return await asyncio.to_thread(encrypt_api_key, plain_text, key)


async def decrypt_api_key_async(cipher_text: str, key: Optional[str] = None) -> str:
    """异步 AES-256-CBC 解密，不阻塞事件循环"""
    return await asyncio.to_thread(decrypt_api_key, cipher_text, key)
