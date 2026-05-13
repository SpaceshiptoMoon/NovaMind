"""
MinIO 客户端封装

提供对象存储功能，用于文件上传、下载和管理。
所有公开方法均为异步，通过 asyncio.to_thread 包装同步 MinIO SDK 调用，
避免阻塞 asyncio 事件循环。

MinIO 存储路径规范:
├── bucket: novamind-dev                            # 统一桶
│   ├── spaces/                                    # 空间目录
│   │   └── {space_id}/                            # 空间 ID
│   │       └── kbs/                               # 知识库目录
│   │           └── {kb_id}/                        # 知识库 ID
│   │               ├── documents/                  # 文档目录
│   │               │   └── {doc_id}/               # 文档 ID
│   │               │       └── {sha256(path)}.ext    # 路径哈希 + 扩展名，原始文件名存 MySQL
│   │               └── exports/                    # 导出文件
│   ├── avatars/                                   # 用户头像
│   └── temp/                                      # 临时文件
"""

import asyncio
import io
import re
from typing import Optional, BinaryIO, List, Dict, Any
from datetime import datetime, timedelta
from minio import Minio
from minio.error import S3Error

from src.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class MinioClient:
    """
    MinIO 客户端（异步）

    统一桶策略：所有文件存储在同一个桶中，通过路径前缀区分。
    所有公开方法均为 async，内部通过 asyncio.to_thread 在线程池中执行同步 MinIO 操作。

    路径规范:
    - 文档: spaces/{space_id}/kbs/{kb_id}/documents/{doc_id}/{filename}
    - 导出: spaces/{space_id}/kbs/{kb_id}/exports/{export_id}/{filename}
    - 头像: avatars/{user_id}/avatar.{ext}
    - 临时: temp/{session_id}/{filename}
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = True,
        region: str = "us-east-1",
        default_bucket: str = "knowledge-base",
    ):
        """
        初始化 MinIO 客户端

        Args:
            endpoint: MinIO 服务地址
            access_key: 访问密钥
            secret_key: 私钥
            secure: 是否使用 HTTPS（默认启用，生产环境强烈建议启用）
            region: 区域
            default_bucket: 默认桶名前缀
        """
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.secure = secure
        self.region = region
        self.default_bucket = default_bucket

        # 安全警告：未启用 SSL
        if not secure:
            logger.warning(
                "MinIO 未启用 SSL 加密，数据传输可能不安全。生产环境请启用 HTTPS。",
                endpoint=endpoint,
            )

        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )

        logger.info(
            "MinIO 客户端初始化成功",
            endpoint=endpoint,
            default_bucket=default_bucket,
            secure=secure,
        )

    # ========== 桶管理 ==========

    async def bucket_exists(self, bucket_name: str) -> bool:
        """检查存储桶是否存在"""
        try:
            return await asyncio.to_thread(self.client.bucket_exists, bucket_name)
        except S3Error as e:
            logger.error("检查存储桶失败", bucket=bucket_name, error=str(e))
            return False

    async def create_bucket(self, bucket_name: str) -> bool:
        """创建存储桶"""
        try:
            if not await self.bucket_exists(bucket_name):
                await asyncio.to_thread(self.client.make_bucket, bucket_name)
                logger.info("创建存储桶成功", bucket=bucket_name)
                return True
            return False
        except S3Error as e:
            logger.error("创建存储桶失败", bucket=bucket_name, error=str(e))
            raise

    async def ensure_bucket_exists(self, bucket_name: str) -> None:
        """确保存储桶存在"""
        if not await self.bucket_exists(bucket_name):
            await self.create_bucket(bucket_name)

    # ========== 文档上传 ==========

    def _upload_document(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        file_data: bytes,
        filename: str,
        file_hash: str = "",
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """同步上传文档（内部方法）"""
        bucket_name = self.default_bucket
        storage_name = self._generate_storage_name(file_hash, filename)
        object_name = f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

        file_stream = io.BytesIO(file_data)
        result = self.client.put_object(
            bucket_name,
            object_name,
            file_stream,
            len(file_data),
            content_type=content_type or self._get_content_type(filename),
            metadata=metadata,
        )

        logger.info(
            "上传文档成功",
            space_id=space_id,
            kb_id=kb_id,
            document_id=document_id,
            bucket=bucket_name,
            object=object_name,
            size=len(file_data),
        )

        return {
            "bucket": bucket_name,
            "object_name": object_name,
            "etag": result.etag if hasattr(result, 'etag') else None,
            "size": len(file_data),
        }

    async def upload_document(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        file_data: bytes,
        filename: str,
        file_hash: str = "",
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        异步上传文档到 MinIO

        Args:
            space_id: 空间ID
            kb_id: 知识库ID
            document_id: 文档ID
            file_data: 文件数据
            filename: 文件名
            file_hash: 文件内容 SHA-256 哈希（用于生成存储文件名）
            content_type: 内容类型
            metadata: 元数据

        Returns:
            上传结果（包含 etag、object_name、bucket）
        """
        bucket_name = self.default_bucket
        await self.ensure_bucket_exists(bucket_name)

        try:
            return await asyncio.to_thread(
                self._upload_document,
                space_id, kb_id, document_id, file_data, filename, file_hash, content_type, metadata,
            )
        except S3Error as e:
            logger.error(
                "上传文档失败",
                space_id=space_id,
                kb_id=kb_id,
                document_id=document_id,
                error=str(e)
            )
            raise

    def _upload_document_stream(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        file_stream: BinaryIO,
        file_size: int,
        filename: str,
        file_hash: str = "",
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """同步流式上传文档（内部方法）"""
        bucket_name = self.default_bucket
        storage_name = self._generate_storage_name(file_hash, filename)
        object_name = f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

        result = self.client.put_object(
            bucket_name,
            object_name,
            file_stream,
            file_size,
            content_type=content_type or self._get_content_type(filename),
            metadata=metadata,
        )

        logger.info(
            "流式上传文档成功",
            space_id=space_id,
            kb_id=kb_id,
            document_id=document_id,
            bucket=bucket_name,
            object=object_name,
            size=file_size,
        )

        return {
            "bucket": bucket_name,
            "object_name": object_name,
            "etag": result.etag if hasattr(result, 'etag') else None,
            "size": file_size,
        }

    async def upload_document_stream(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        file_stream: BinaryIO,
        file_size: int,
        filename: str,
        file_hash: str = "",
        content_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        异步流式上传文档

        Args:
            space_id: 空间ID
            kb_id: 知识库ID
            document_id: 文档ID
            file_stream: 文件流
            file_size: 文件大小
            filename: 文件名
            file_hash: 文件内容 SHA-256 哈希（用于生成存储文件名）
            content_type: 内容类型
            metadata: 元数据

        Returns:
            上传结果
        """
        bucket_name = self.default_bucket
        await self.ensure_bucket_exists(bucket_name)

        try:
            return await asyncio.to_thread(
                self._upload_document_stream,
                space_id, kb_id, document_id, file_stream, file_size, filename, file_hash, content_type, metadata,
            )
        except S3Error as e:
            logger.error(
                "流式上传文档失败",
                space_id=space_id,
                kb_id=kb_id,
                error=str(e)
            )
            raise

    # ========== 文档下载 ==========

    def _download_document(self, bucket_name: str, object_name: str) -> bytes:
        """同步下载文档（内部方法）"""
        response = self.client.get_object(bucket_name, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    async def download_document(
        self,
        bucket_name: str,
        object_name: str,
    ) -> bytes:
        """
        异步下载文档

        Args:
            bucket_name: 桶名
            object_name: 对象名

        Returns:
            文件数据
        """
        try:
            return await asyncio.to_thread(self._download_document, bucket_name, object_name)
        except S3Error as e:
            logger.error(
                "下载文档失败",
                bucket=bucket_name,
                object=object_name,
                error=str(e)
            )
            raise

    async def download_document_stream(
        self,
        bucket_name: str,
        object_name: str,
    ) -> bytes:
        """
        异步下载文档（返回完整内容）

        在线程池中完成下载和读取，避免跨线程使用连接对象。

        Args:
            bucket_name: 桶名
            object_name: 对象名

        Returns:
            文件数据
        """
        def _download_and_read():
            response = self.client.get_object(bucket_name, object_name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(_download_and_read)
        except S3Error as e:
            logger.error(
                "下载文档失败",
                bucket=bucket_name,
                object=object_name,
                error=str(e)
            )
            raise

    # ========== 文档删除 ==========

    async def delete_document(
        self,
        bucket_name: str,
        object_name: str,
    ) -> bool:
        """
        异步删除文档

        Args:
            bucket_name: 桶名
            object_name: 对象名

        Returns:
            是否删除成功
        """
        try:
            await asyncio.to_thread(self.client.remove_object, bucket_name, object_name)
            logger.info("删除文档成功", bucket=bucket_name, object=object_name)
            return True
        except S3Error as e:
            logger.error(
                "删除文档失败",
                bucket=bucket_name,
                object=object_name,
                error=str(e)
            )
            return False

    def _delete_knowledge_base_documents(self, space_id: int, kb_id: int) -> int:
        """同步删除知识库的所有文档（内部方法）"""
        bucket_name = self.default_bucket
        prefix = f"spaces/{space_id}/kbs/{kb_id}/"
        objects = self.client.list_objects(bucket_name, prefix=prefix, recursive=True)
        count = 0
        for obj in objects:
            try:
                self.client.remove_object(bucket_name, obj.object_name)
                count += 1
            except Exception as e:
                logger.warning(
                    "删除知识库单个文档失败，继续删除其余文档",
                    bucket=bucket_name,
                    object=obj.object_name,
                    error=str(e),
                )
        logger.info("删除知识库文档成功", space_id=space_id, kb_id=kb_id, deleted_count=count)
        return count

    async def delete_knowledge_base_documents(
        self,
        space_id: int,
        kb_id: int,
    ) -> int:
        """
        异步删除知识库的所有文档

        Args:
            space_id: 空间ID
            kb_id: 知识库ID

        Returns:
            删除的文件数量
        """
        try:
            return await asyncio.to_thread(
                self._delete_knowledge_base_documents, space_id, kb_id,
            )
        except S3Error as e:
            logger.error(
                "删除知识库文档失败",
                space_id=space_id,
                kb_id=kb_id,
                error=str(e)
            )
            raise

    def _delete_space_documents(self, space_id: int) -> int:
        """同步删除空间的所有文档（内部方法）"""
        bucket_name = self.default_bucket
        prefix = f"spaces/{space_id}/"
        objects = self.client.list_objects(bucket_name, prefix=prefix, recursive=True)
        count = 0
        for obj in objects:
            try:
                self.client.remove_object(bucket_name, obj.object_name)
                count += 1
            except Exception as e:
                logger.warning(
                    "删除空间单个文档失败，继续删除其余文档",
                    bucket=bucket_name,
                    object=obj.object_name,
                    error=str(e),
                )
        logger.info("删除空间文档成功", space_id=space_id, deleted_count=count)
        return count

    async def delete_space_documents(
        self,
        space_id: int,
    ) -> int:
        """
        异步删除空间的所有文档

        Args:
            space_id: 空间ID

        Returns:
            删除的文件数量
        """
        try:
            return await asyncio.to_thread(self._delete_space_documents, space_id)
        except S3Error as e:
            logger.error(
                "删除空间文档失败",
                space_id=space_id,
                error=str(e)
            )
            raise

    # ========== 头像上传 ==========

    def _upload_avatar(self, user_id: int, file_data: bytes, extension: str = "jpg") -> Dict[str, Any]:
        """同步上传用户头像（内部方法）"""
        bucket_name = self.default_bucket
        # 删除旧头像
        self._delete_avatar(bucket_name, user_id)

        object_name = f"avatars/{user_id}/avatar.{extension}"
        content_type = self._get_content_type(f"avatar.{extension}")

        file_stream = io.BytesIO(file_data)
        result = self.client.put_object(
            bucket_name,
            object_name,
            file_stream,
            len(file_data),
            content_type=content_type,
        )

        logger.info("上传头像成功", user_id=user_id, object=object_name)

        return {
            "bucket": bucket_name,
            "object_name": object_name,
            "etag": result.etag if hasattr(result, 'etag') else None,
        }

    async def upload_avatar(
        self,
        user_id: int,
        file_data: bytes,
        extension: str = "jpg",
    ) -> Dict[str, Any]:
        """
        异步上传用户头像

        Args:
            user_id: 用户ID
            file_data: 文件数据
            extension: 文件扩展名

        Returns:
            上传结果
        """
        bucket_name = self.default_bucket
        await self.ensure_bucket_exists(bucket_name)

        try:
            return await asyncio.to_thread(
                self._upload_avatar, user_id, file_data, extension,
            )
        except S3Error as e:
            logger.error("上传头像失败", user_id=user_id, error=str(e))
            raise

    def _delete_avatar(self, bucket_name: str, user_id: int) -> None:
        """删除用户的旧头像"""
        avatar_prefix = f"avatars/{user_id}/"
        try:
            objects = self.client.list_objects(bucket_name, prefix=avatar_prefix)
            for obj in objects:
                self.client.remove_object(bucket_name, obj.object_name)
        except S3Error:
            pass  # 忽略删除错误

    # ========== 临时文件 ==========

    def _upload_temp_file(self, session_id: str, file_data: bytes, filename: str) -> Dict[str, Any]:
        """同步上传临时文件（内部方法）"""
        bucket_name = self.default_bucket
        safe_filename = self._sanitize_filename(filename)
        object_name = f"temp/{session_id}/{safe_filename}"

        file_stream = io.BytesIO(file_data)
        result = self.client.put_object(
            bucket_name,
            object_name,
            file_stream,
            len(file_data),
            content_type=self._get_content_type(filename),
        )

        return {
            "bucket": bucket_name,
            "object_name": object_name,
            "etag": result.etag if hasattr(result, 'etag') else None,
        }

    async def upload_temp_file(
        self,
        session_id: str,
        file_data: bytes,
        filename: str,
    ) -> Dict[str, Any]:
        """
        异步上传临时文件

        Args:
            session_id: 会话ID
            file_data: 文件数据
            filename: 文件名

        Returns:
            上传结果
        """
        bucket_name = self.default_bucket
        await self.ensure_bucket_exists(bucket_name)

        try:
            return await asyncio.to_thread(
                self._upload_temp_file, session_id, file_data, filename,
            )
        except S3Error as e:
            logger.error("上传临时文件失败", session_id=session_id, error=str(e))
            raise

    def _cleanup_temp_files(self, session_id: str) -> int:
        """同步清理会话的临时文件（内部方法）"""
        bucket_name = self.default_bucket
        prefix = f"temp/{session_id}/"
        objects = self.client.list_objects(bucket_name, prefix=prefix)
        count = 0
        for obj in objects:
            self.client.remove_object(bucket_name, obj.object_name)
            count += 1
        return count

    async def cleanup_temp_files(self, session_id: str) -> int:
        """
        异步清理会话的临时文件

        Args:
            session_id: 会话ID

        Returns:
            删除的文件数量
        """
        try:
            return await asyncio.to_thread(self._cleanup_temp_files, session_id)
        except S3Error as e:
            logger.error("清理临时文件失败", session_id=session_id, error=str(e))
            return 0

    # ========== 工具方法 ==========

    async def get_file_url(
        self,
        bucket_name: str,
        object_name: str,
        expires: int = 3600,
    ) -> str:
        """
        异步获取文件预签名 URL

        Args:
            bucket_name: 桶名
            object_name: 对象名
            expires: URL 过期时间（秒）

        Returns:
            预签名 URL
        """
        try:
            return await asyncio.to_thread(
                self.client.presigned_get_object,
                bucket_name,
                object_name,
                timedelta(seconds=expires),
            )
        except S3Error as e:
            logger.error(
                "获取预签名 URL 失败",
                bucket=bucket_name,
                object=object_name,
                error=str(e)
            )
            raise

    async def get_file_info(
        self,
        bucket_name: str,
        object_name: str,
    ) -> Optional[Dict[str, Any]]:
        """
        异步获取文件信息

        Args:
            bucket_name: 桶名
            object_name: 对象名

        Returns:
            文件信息
        """
        try:
            stat = await asyncio.to_thread(self.client.stat_object, bucket_name, object_name)
            if stat:
                return {
                    "size": stat.size,
                    "content_type": stat.content_type,
                    "last_modified": stat.last_modified,
                    "etag": stat.etag,
                }
            return None
        except S3Error as e:
            logger.error(
                "获取文件信息失败",
                bucket=bucket_name,
                object=object_name,
                error=str(e)
            )
            raise

    async def list_files(
        self,
        bucket_name: str,
        prefix: str = "",
    ) -> List[str]:
        """
        异步列出存储桶中的文件

        Args:
            bucket_name: 桶名
            prefix: 文件前缀

        Returns:
            文件名列表
        """
        try:
            objects = await asyncio.to_thread(
                self.client.list_objects, bucket_name, prefix, True,
            )
            return [obj.object_name for obj in objects]
        except S3Error as e:
            logger.error("列出文件失败", bucket=bucket_name, error=str(e))
            raise

    # ========== 私有方法 ==========

    def _get_document_object_name(
        self,
        space_id: int,
        kb_id: int,
        document_id: int,
        filename: str,
        file_hash: str = "",
    ) -> str:
        """
        生成文档对象名

        Args:
            space_id: 空间ID
            kb_id: 知识库ID
            document_id: 文档ID
            filename: 原始文件名
            file_hash: 文件内容 SHA-256 哈希

        Returns:
            对象名（路径）
        """
        storage_name = self._generate_storage_name(file_hash, filename)
        return f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/{storage_name}"

    def _generate_storage_name(self, file_hash: str, filename: str) -> str:
        """
        生成 MinIO 存储用的文件名（不含目录路径）

        使用文件内容的 SHA-256 哈希作为文件名，避免暴露原始文件名和业务信息。
        原始文件名存储在 MySQL 的 documents 表中。

        Args:
            file_hash: 文件内容 SHA-256 哈希值
            filename: 原始文件名（仅用于提取扩展名）

        Returns:
            存储文件名，如 "a1b2c3d4e5f6...pdf"
        """
        ext = ""
        if filename and "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower()
        return f"{file_hash}.{ext}" if ext else file_hash

    def _sanitize_filename(self, filename: str) -> str:
        """
        安全化文件名

        - 移除路径遍历字符（../）
        - 移除特殊字符
        - 保留中文、字母、数字、下划线、连字符、空格和点
        """
        if not filename:
            return "unnamed"

        safe_name = filename.replace('..', '').replace('/', '_').replace('\\', '_')
        safe_name = re.sub(r'[^\w\u3400-\u9fff\uF900-\uFAFF\.\-\s]', '_', safe_name)
        safe_name = re.sub(r'_+', '_', safe_name)
        safe_name = safe_name.strip(' ._')

        if not safe_name:
            safe_name = "unnamed"

        max_length = 200
        if len(safe_name) > max_length:
            if '.' in safe_name:
                name_part, ext = safe_name.rsplit('.', 1)
                safe_name = f"{name_part[:max_length - len(ext) - 1]}.{ext}"
            else:
                safe_name = safe_name[:max_length]

        return safe_name

    def _get_content_type(self, filename: str) -> str:
        """根据文件名获取内容类型"""
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        content_types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "doc": "application/msword",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "xls": "application/ms-excel",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "ppt": "application/vnd.ms-powerpoint",
            "txt": "text/plain",
            "md": "text/markdown",
            "markdown": "text/markdown",
            "html": "text/html",
            "htm": "text/html",
            "csv": "text/csv",
            "json": "application/json",
            "xml": "application/xml",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
            "svg": "image/svg+xml",
            "ico": "image/x-icon",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "mp4": "video/mp4",
            "webm": "video/webm",
            "mov": "video/quicktime",
            "zip": "application/zip",
            "rar": "application/vnd.rar",
            "7z": "application/x-7z-compressed",
            "tar": "application/x-tar",
            "gz": "application/gzip",
        }
        return content_types.get(ext, "application/octet-stream")

    # ========== 存储路径查询方法 ==========

    @staticmethod
    def get_document_path_pattern(space_id: int, kb_id: int, document_id: int) -> str:
        """获取文档路径模式"""
        return f"spaces/{space_id}/kbs/{kb_id}/documents/{document_id}/"

    @staticmethod
    def get_kb_path_pattern(space_id: int, kb_id: int) -> str:
        """获取知识库路径模式"""
        return f"spaces/{space_id}/kbs/{kb_id}/"

    @staticmethod
    def get_space_path_pattern(space_id: int) -> str:
        """获取空间路径模式"""
        return f"spaces/{space_id}/"

    @staticmethod
    def get_avatar_path(user_id: int, extension: str = "jpg") -> str:
        """获取头像路径"""
        return f"avatars/{user_id}/avatar.{extension}"

    @staticmethod
    def get_temp_path(session_id: str, filename: str) -> str:
        """获取临时文件路径"""
        return f"temp/{session_id}/{filename}"

    # ========== 通用文件上传 ==========

    def _upload_file(self, object_name: str, file_data: bytes, content_type: str = "application/octet-stream") -> str:
        """同步通用文件上传（内部方法）"""
        bucket_name = self.default_bucket
        file_stream = io.BytesIO(file_data)
        self.client.put_object(
            bucket_name, object_name, file_stream, len(file_data), content_type=content_type,
        )
        logger.info("上传文件成功", bucket=bucket_name, object=object_name, size=len(file_data))
        return object_name

    async def upload_file(self, object_name: str, file_data: bytes, content_type: str = "application/octet-stream") -> str:
        """异步通用文件上传，返回 object_name"""
        bucket_name = self.default_bucket
        await self.ensure_bucket_exists(bucket_name)
        try:
            return await asyncio.to_thread(self._upload_file, object_name, file_data, content_type)
        except S3Error as e:
            logger.error("上传文件失败", object=object_name, error=str(e))
            raise
