"""
AES 加解密工具

当前版本：AES-256-GCM + HKDF-SHA256 密钥派生（v2）。
向后兼容：可解密旧版 AES-256-CBC + SHA-256 派生加密的数据（无前缀旧格式）。

格式：
  - 新（v2）：v2:Base64(IV 12B + ciphertext + GCM tag 16B)
  - 旧（v1）：Base64(IV 16B + ciphertext) — 仅解密，不再写入
"""
import asyncio
import base64
import hashlib
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend


_CIPHER_VERSION = "v2:"


def _hkdf_derive(raw_key: bytes) -> bytes:
    """HKDF-SHA256 派生 32 字节 AES 密钥"""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"NovaMind_v1",
        info=b"NovaMind-crypto-v1",
    ).derive(raw_key)


def _get_encryption_key_v1() -> bytes:
    """旧版 SHA-256 派生（仅用于解密旧 CBC 数据）"""
    from novamind.setting.yaml_config import get_config
    config = get_config()
    raw_key = config.security.encryption_key
    if not raw_key:
        raise ValueError("未配置加密密钥（security.encryption_key）")
    return hashlib.sha256(raw_key.encode("utf-8")).digest()


def _get_encryption_key() -> bytes:
    """获取当前版本加密密钥（HKDF 派生）"""
    from novamind.setting.yaml_config import get_config
    config = get_config()
    raw_key = config.security.encryption_key
    if not raw_key:
        raise ValueError("未配置加密密钥（security.encryption_key），请在 YAML 配置中设置")
    return _hkdf_derive(raw_key.encode("utf-8"))


def _get_aes_key(key: Optional[str] = None, v1_compat: bool = False) -> bytes:
    """
    获取 AES 密钥

    Args:
        key: 外部传入的密钥（可选）。传此参数时用 SHA-256 派生（保持调用方兼容）。
        v1_compat: 是否使用旧版 SHA-256 派生（解密旧 CBC 数据时用）。
    """
    if key:
        return hashlib.sha256(key.encode("utf-8")).digest()
    return _get_encryption_key_v1() if v1_compat else _get_encryption_key()


# ==================== 当前版本加解密（AES-256-GCM） ====================


def encrypt_api_key(plain_text: str, key: Optional[str] = None) -> str:
    """
    AES-256-GCM 加密（当前版本）

    Args:
        plain_text: 明文 API Key
        key: 外部加密密钥（可选，默认从配置读取）

    Returns:
        v2:Base64(IV + 密文 + GCM tag) 格式字符串
    """
    if not plain_text:
        return ""

    aes_key = _get_aes_key(key)

    # GCM 推荐 12 字节 IV
    iv = os.urandom(12)

    cipher = Cipher(algorithms.AES(aes_key), modes.GCM(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plain_text.encode("utf-8")) + encryptor.finalize()

    return _CIPHER_VERSION + base64.b64encode(iv + ciphertext + encryptor.tag).decode("utf-8")


def decrypt_api_key(cipher_text: str, key: Optional[str] = None) -> str:
    """
    解密 API Key（自动检测版本：v2 走 GCM，无前缀走旧版 CBC）

    Args:
        cipher_text: 密文字符串（v2:Base64 或 旧 Base64）
        key: 外部加密密钥（可选，默认从配置读取）

    Returns:
        明文 API Key
    """
    if not cipher_text:
        return ""

    is_v2 = cipher_text.startswith(_CIPHER_VERSION)
    raw_data = base64.b64decode(cipher_text[len(_CIPHER_VERSION):] if is_v2 else cipher_text)

    aes_key = _get_aes_key(key, v1_compat=not is_v2)

    if is_v2:
        # === v2: AES-256-GCM ===
        iv, rest = raw_data[:12], raw_data[12:]
        tag, ciphertext = rest[-16:], rest[:-16]
        cipher = Cipher(algorithms.AES(aes_key), modes.GCM(iv, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")
    else:
        # === v1 兼容：AES-256-CBC ===
        iv = raw_data[:16]
        ciphertext = raw_data[16:]
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded_data = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = crypto_padding.PKCS7(128).unpadder()
        plain_data = unpadder.update(padded_data) + unpadder.finalize()
        return plain_data.decode("utf-8")


# ==================== 公共辅助函数 ====================


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

    if len(api_key) <= 8:
        return "****"

    return f"{api_key[:3]}****{api_key[-4:]}"


# ==================== 异步包装器（接口不变） ====================


async def encrypt_api_key_async(plain_text: str, key: Optional[str] = None) -> str:
    """异步加密 API Key，不阻塞事件循环"""
    return await asyncio.to_thread(encrypt_api_key, plain_text, key)


async def decrypt_api_key_async(cipher_text: str, key: Optional[str] = None) -> str:
    """异步解密 API Key，不阻塞事件循环"""
    return await asyncio.to_thread(decrypt_api_key, cipher_text, key)
