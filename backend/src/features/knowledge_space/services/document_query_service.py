"""文档查询服务（从 document_service.py 巨石抽出的 CRUD/查询职责）。

集中承载文档的读取、下载与级联删除：
- ``count_kb_documents`` / ``get_kb_documents`` / ``get_document``：列表与单查
- ``get_document_chunks``：从 Elasticsearch 取分块（分页）
- ``download_document`` / ``get_parsed_text`` / ``get_document_frames``：MinIO 下载与预签名
- ``delete_document``：级联删 DB + ES 分块 + MinIO 文件 + 失效搜索缓存

构造器精简为 ``(session, minio_client, es_client)``——查询/下载/删除不触碰模型配置，
任务编排由 ``DocumentTaskService``、上传由 ``DocumentUploadService``、管道执行由
``document_pipeline.execute_document_pipeline`` 分别承担。
"""

from typing import Any
import re

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.knowledge_space.exceptions import (
    DocumentAlreadyProcessingError,
    DocumentNotFoundError,
    KnowledgeBaseNotFoundError,
    SpaceAccessDeniedError,
)
from novamind.features.knowledge_space.models.document import Document
from novamind.features.knowledge_space.repository.document_repository import DocumentRepository
from novamind.features.knowledge_space.repository.knowledge_base_repository import (
    KnowledgeBaseRepository,
)
from novamind.features.knowledge_space.repository.member_repository import MemberRepository
from novamind.features.knowledge_space.services.permission_service import SpaceAccessChecker
from novamind.shared.storage.elasticsearch_client import ElasticsearchClient
from novamind.shared.storage.minio_client import MinioClient
from sqlalchemy.ext.asyncio import AsyncSession

# figure 文件名白名单：上传侧 _upload_figure_images_to_minio 产出
# figure_{safe_id}_{page}.png（safe_id 已把非 [a-zA-Z0-9_-] 归一为 _）。
# 代理端点据此拒绝路径穿越（../、反斜杠、%2e 等编码形态在路由参数解码后
# 不匹配本模式即 404）。
_FIGURE_FILE_NAME_RE = re.compile(r"figure_[A-Za-z0-9_.-]+\.png")


# MD 全文/chunk content 里 figure 链接的捕获组（短文件名 figure_xxx.png）。
# 读取端点用它在返回前把短文件名替换为即时预签名 URL（存储侧始终是短路径）。
_FIGURE_LINK_RE = re.compile(r"\]\((figure_[A-Za-z0-9_.-]+\.png)\)")


def resolve_figure_object_name(storage: dict, figure_file: str) -> str | None:
    """把 figure 短文件名还原成完整 MinIO object name（纯函数）。

    ``storage`` 是 document.storage JSON；锚点 ``figures_object_dir`` 由解析
    管道在上传 figure 时写入。文件名不在白名单或锚点缺失返回 None
    （含旧文档未重解析、路径穿越攻击两种情况，调用方统一按 404 处理）。
    """
    if not isinstance(storage, dict):
        return None
    if not figure_file or not _FIGURE_FILE_NAME_RE.fullmatch(figure_file):
        return None
    figures_dir = str(storage.get("figures_object_dir") or "")
    if not figures_dir:
        return None
    return f"{figures_dir}/{figure_file}"


class DocumentQueryService:
    """文档查询服务：读取、下载与级联删除（不触发解析、不编排任务）。"""

    def __init__(
        self,
        session: AsyncSession,
        minio_client: MinioClient,
        es_client: ElasticsearchClient,
    ):
        self.session = session
        self.doc_repo = DocumentRepository(session)
        self.kb_repo = KnowledgeBaseRepository(session)
        self.member_repo = MemberRepository(session)
        self.permission_service = SpaceAccessChecker()
        self.minio_client = minio_client
        self.es_client = es_client
        self.logger = get_logger(__name__)

    async def count_kb_documents(
        self,
        kb_id: int,
        status: int | None = None,
        keyword: str | None = None,
    ) -> int:
        """统计知识库中的文档数量"""
        return await self.doc_repo.count_by_kb(kb_id=kb_id, status=status, keyword=keyword)

    async def get_filename_map(self, document_ids: list[int]) -> dict[int, str]:
        """按 document_id 批量取 ``Documents.filename``，供任务列表回填真实文件名。

        将「路由层直接 new DocumentRepository」的层级泄漏收敛到 service；
        返回 ``{document_id: filename}``，无记录的 id 不出现在映射中。
        """
        if not document_ids:
            return {}
        return await self.doc_repo.get_filename_map_by_ids(document_ids)

    async def delete_document(
        self,
        kb_id: int,
        document_id: int,
        user_id: int,
    ) -> bool:
        """
        删除文档

        权限规则：
        - EDITOR 及以上角色可删除自己上传的文档
        - ADMIN 可删除任意文档

        Args:
            kb_id: 知识库 ID
            document_id: 文档 ID
            user_id: 操作用户 ID

        Returns:
            是否成功

        Raises:
            DocumentNotFoundError: 文档不存在
            SpaceAccessDeniedError: 无权删除文档
        """
        # 1. 权限检查：验证成员身份和角色
        kb = await self.kb_repo.get_by_id(kb_id)
        if not kb:
            raise KnowledgeBaseNotFoundError(kb_id)

        member = await self.member_repo.get_by_space_and_user(kb.space_id, user_id)
        if not member or not member.is_active():
            raise SpaceAccessDeniedError(kb.space_id, user_id, "无权删除此知识库的文档")
        if not self.permission_service.can_delete_document(member):
            raise SpaceAccessDeniedError(kb.space_id, user_id, "需要编辑者或更高权限才能删除文档")

        # 2. 获取文档
        document = await self.doc_repo.get_by_id(document_id)
        if not document or document.kb_id != kb_id:
            raise DocumentNotFoundError(document_id)

        # 2.5 有活跃处理任务时拒绝删除
        from novamind.features.knowledge_space.repository.document_task_repository import (
            DocumentTaskRepository,
        )

        _task_repo = DocumentTaskRepository(self.session)
        active_task = await _task_repo.get_active_by_document_id(document_id)
        if active_task:
            raise DocumentAlreadyProcessingError(document_id)

        # 3. 细粒度权限检查：EDITOR 只能删除自己的文档，ADMIN 可删除任意文档
        if not self.permission_service.can_delete_any_document(member):
            if document.uploader_id != user_id:
                raise SpaceAccessDeniedError(
                    kb.space_id,
                    user_id,
                    "只能删除自己上传的文档，删除他人文档需要管理员权限",
                )

        # 3.5 wiki 来源回收（对齐 WeKnora cleanupWikiOnKnowledgeDelete，best-effort）：
        # 先写 tombstone 防「删除 vs 生成中」竞态，再同步对账（唯一来源页软删、
        # 多来源页剥引用），并入队异步 retract 任务兜底。任何失败不阻断文档删除。
        try:
            from novamind.features.knowledge_space.services.wiki_retract_service import (
                WikiRetractService,
                write_tombstone,
            )
            from novamind.features.knowledge_space.tasks.wiki_tasks import enqueue_wiki_retract

            await write_tombstone(kb_id, document_id)
            retract_svc = WikiRetractService(self.session, kb_id=kb_id, space_id=document.space_id)
            result = await retract_svc.reconcile_document_removal(document_id)
            if result["deleted"] or result["stripped"]:
                self.logger.info(
                    "wiki 来源回收完成",
                    kb_id=kb_id, document_id=document_id,
                    deleted=len(result["deleted"]), stripped=len(result["stripped"]),
                )
            await enqueue_wiki_retract(kb_id, document.space_id, document_id)
        except Exception as e:
            self.logger.warning(
                "wiki 来源回收失败（不影响文档删除）", kb_id=kb_id, document_id=document_id, error=str(e),
            )

        # 4. 删除文档记录（先数据库操作，确保事务一致性）
        await self.doc_repo.delete(document_id)

        # 5. 更新知识库统计（使用行锁保证原子性）
        await self.session.commit()

        # 6. 失效该知识库的搜索缓存
        try:
            from novamind.shared.storage.client_factory import get_redis_client

            cache = await get_redis_client()
            await cache.delete_by_pattern(f"search:{kb_id}:*", batch_size=100)
        except Exception as cache_err:
            self.logger.warning("搜索缓存失效失败", kb_id=kb_id, error=str(cache_err))

        # 6.5 被软删 wiki 页的 ES 向量清理（best-effort，对齐 WeKnora
        # deleteChunkForPage）：同步路径直接清，不依赖异步 retract 兜底。
        # slug 在步骤 3.5 的对账结果里（include_deleted 才查得到软删页）。
        try:
            from novamind.features.knowledge_space.repository.wiki_repository import (
                WikiPageRepository,
            )
            from novamind.features.knowledge_space.services.wiki_es_sync import (
                WikiEsSyncService,
            )

            wiki_page_repo = WikiPageRepository(self.session)
            wiki_sync = WikiEsSyncService(self.session, self.es_client)
            for slug in result["deleted"]:
                page = await wiki_page_repo.get_by_slug(kb_id, slug, include_deleted=True)
                if page:
                    await wiki_sync.delete_page(document.space_id, page.id)
        except Exception as wiki_es_err:
            self.logger.warning(
                "wiki 页 ES 向量清理失败（异步 retract 兜底）",
                kb_id=kb_id, document_id=document_id, error=str(wiki_es_err),
            )

        # 7. 清理外部存储（DB 事务提交后再执行，失败不影响数据一致性）
        try:
            await self.es_client.delete_document_chunks(
                space_id=document.space_id,
                document_id=document_id,
            )
        except Exception as e:
            self.logger.warning(
                "删除 ES 分块数据失败（数据已从 DB 删除）", document_id=document_id, error=str(e)
            )

        try:
            storage_info = document.get_storage_info()
            if storage_info.get("minio_bucket") and storage_info.get("minio_object_name"):
                # 先清视频帧目录（{base_object}_frames/ 前缀）：delete_document 只删主对象，
                # 不删帧，删文档后帧成 MinIO 孤儿。先于主对象删除，确保帧一并清理。
                try:
                    await self.minio_client.delete_objects_by_prefix(
                        storage_info["minio_bucket"],
                        f"{storage_info['minio_object_name']}_frames/",
                    )
                except Exception as frame_err:
                    self.logger.warning(
                        "删除视频帧前缀失败（继续删主对象）",
                        document_id=document_id, error=str(frame_err),
                    )
                # 同时清理 PDF figure 图片目录（{base_object}_figures/ 前缀）
                try:
                    await self.minio_client.delete_objects_by_prefix(
                        storage_info["minio_bucket"],
                        f"{storage_info['minio_object_name']}_figures/",
                    )
                except Exception as figure_err:
                    self.logger.warning(
                        "删除 PDF figure 图片前缀失败（继续删主对象）",
                        document_id=document_id, error=str(figure_err),
                    )
                # 清理解析全文目录（{base_object}_parsed/ 前缀）：parsed_text_object
                # 指向的 full_text.md 若不清理将成为 MinIO 孤儿（DB 删除后无人引用）。
                try:
                    await self.minio_client.delete_objects_by_prefix(
                        storage_info["minio_bucket"],
                        f"{storage_info['minio_object_name']}_parsed/",
                    )
                except Exception as parsed_err:
                    self.logger.warning(
                        "删除解析全文本前缀失败（继续删主对象）",
                        document_id=document_id, error=str(parsed_err),
                    )
                # 清理管道快照目录（{base_object}_artifacts/ 前缀）：切分/向量快照
                # JSON 若不清理将成为 MinIO 孤儿（含大体积向量文件）。
                try:
                    await self.minio_client.delete_objects_by_prefix(
                        storage_info["minio_bucket"],
                        f"{storage_info['minio_object_name']}_artifacts/",
                    )
                except Exception as artifacts_err:
                    self.logger.warning(
                        "删除管道快照前缀失败（继续删主对象）",
                        document_id=document_id, error=str(artifacts_err),
                    )
                await self.minio_client.delete_document(
                    bucket_name=storage_info["minio_bucket"],
                    object_name=storage_info["minio_object_name"],
                )
        except Exception as e:
            self.logger.warning(
                "删除 MinIO 文件失败（数据已从 DB 删除）", document_id=document_id, error=str(e)
            )

        self.logger.info(
            "文档删除成功",
            document_id=document_id,
            kb_id=kb_id,
            user_id=user_id,
        )

        return True

    async def get_document(
        self,
        document_id: int,
        raise_not_found: bool = False,
    ) -> Document | None:
        """
        获取文档

        Args:
            document_id: 文档 ID
            raise_not_found: 是否在文档不存在时抛出异常

        Returns:
            文档或 None
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document and raise_not_found:
            raise DocumentNotFoundError(document_id)
        return document

    async def get_kb_documents(
        self,
        kb_id: int,
        skip: int = 0,
        limit: int = 100,
        status: int | None = None,
        keyword: str | None = None,
    ) -> list[Document]:
        """
        获取知识库的文档列表

        Args:
            kb_id: 知识库 ID
            skip: 跳过数量
            limit: 返回数量
            status: 状态过滤
            keyword: 文件名模糊搜索关键词

        Returns:
            文档列表
        """
        return await self.doc_repo.get_by_kb(
            kb_id=kb_id,
            skip=skip,
            limit=limit,
            status=status,
            keyword=keyword,
        )

    async def get_document_chunks(
        self,
        space_id: int,
        document_id: int,
        skip: int = 0,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        获取文档的分块列表（从 Elasticsearch 获取，分页）

        Args:
            space_id: 空间 ID
            document_id: 文档 ID
            skip: 跳过的记录数
            limit: 返回的最大记录数

        Returns:
            ``{"items": [...], "total": int}`` — items 为当前页分块，total 为分块总数
        """
        return await self.es_client.get_document_chunks(
            space_id=space_id,
            document_id=document_id,
            skip=skip,
            limit=limit,
        )

    async def presign_figure_links(
        self, document: Document, content: str, expires: int = 21600
    ) -> str:
        """把 content 中 figure 短文件名（figure_xxx.png）替换为即时预签名 URL。

        MD/ES 存储侧始终是短路径（不可变无时效）；``<img>`` 无法携带
        Authorization 头，故在已鉴权的读取端点（parsed-text 视图 / chunks
        列表）返回前换取新鲜签名（默认 6 小时，覆盖浏览器缓存窗口），
        下载与 embedding 路径不经过本方法、保持短路径干净。

        文档无 figures_object_dir 锚点（未重解析的旧文档）、文件名不在
        白名单或单个签名失败时该链接原样保留（渲染层按裂图处理）。
        """
        if not content or "](figure_" not in content:
            return content

        figure_files = set(_FIGURE_LINK_RE.findall(content))
        url_map: dict[str, str] = {}
        for figure_file in figure_files:
            object_name = resolve_figure_object_name(
                document.get_storage_info(), figure_file
            )
            if not object_name:
                continue
            try:
                url_map[figure_file] = await self.minio_client.get_file_url(
                    self.minio_client.default_bucket, object_name, expires
                )
            except Exception as exc:
                self.logger.warning(
                    "figure 图片预签名失败（该链接保持短路径）",
                    document_id=document.id,
                    object_name=object_name,
                    error=str(exc),
                )

        if not url_map:
            return content
        return _FIGURE_LINK_RE.sub(
            lambda m: f"]({url_map.get(m.group(1), m.group(1))})", content
        )

    @staticmethod
    async def presign_media_url(chunk_type: str | None, storage_path: str) -> str | None:
        """媒体分块（image/video/audio）生成 MinIO 预签名 URL（批次 4 自路由层下沉）。

        非媒体类型或空路径返回 None；MinIO 不可用降级 None（渲染层自行回退占位）。
        """
        if chunk_type not in ("image", "video", "audio") or not storage_path:
            return None
        try:
            from novamind.shared.storage.client_factory import ClientFactory

            minio_client = await ClientFactory.get_minio_client()
            return await minio_client.get_file_url(
                minio_client.default_bucket, storage_path, 3600
            )
        except Exception:
            return None

    async def download_document(
        self,
        document_id: int,
    ) -> bytes:
        """
        下载文档

        Args:
            document_id: 文档 ID

        Returns:
            文件内容

        Raises:
            DocumentNotFoundError: 文档不存在
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            raise DocumentNotFoundError(document_id)

        storage_info = document.get_storage_info()
        return await self.minio_client.download_document(
            bucket_name=storage_info.get("minio_bucket"),
            object_name=storage_info.get("minio_object_name"),
        )

    async def get_parsed_text(self, document_id: int) -> bytes | None:
        """获取文档解析后的 Markdown 全文。

        从 MinIO 读取 document.storage["parsed_text_object"] 指向的文件。
        若文档尚未解析或解析结果不存在，返回 None。

        Args:
            document_id: 文档 ID

        Returns:
            Markdown 全文的字节数据，或 None
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            return None

        storage_info = document.get_storage_info()
        parsed_text_object = storage_info.get("parsed_text_object", "")
        if not parsed_text_object:
            return None

        try:
            content = await self.minio_client.download_document(
                bucket_name=self.minio_client.default_bucket,
                object_name=parsed_text_object,
            )
            return content
        except Exception:
            self.logger.warning(
                "解析全文下载失败",
                document_id=document_id,
                object_name=parsed_text_object,
            )
            return None

    async def get_document_frames(self, document_id: int) -> dict:
        """获取文档视频帧预签名 URL 列表。

        读取 document.storage["frames"] 中的 MinIO 路径列表，
        为每个帧生成预签名 URL。非视频文档或无帧数据时返回空列表。

        Args:
            document_id: 文档 ID

        Returns:
            {"frames": [{"index": 0, "url": "..."}, ...], "total": N}
        """
        document = await self.doc_repo.get_by_id(document_id)
        if not document:
            return {"frames": [], "total": 0}

        storage_info = document.get_storage_info()
        frame_paths = storage_info.get("frames", [])
        if not frame_paths:
            return {"frames": [], "total": 0}

        try:
            frames = []
            for idx, path in enumerate(frame_paths):
                if not path:
                    continue
                url = await self.minio_client.get_file_url(
                    bucket_name=self.minio_client.default_bucket,
                    object_name=path,
                    expires=3600,
                )
                frames.append({"index": idx, "url": url})

            return {"frames": frames, "total": len(frames)}
        except Exception:
            self.logger.warning(
                "视频帧预签名 URL 生成失败",
                document_id=document_id,
            )
            return {"frames": [], "total": 0}
