"""视频叙事文档业务服务：合成编排（拉块→引擎→落库）与读取。

触发入口两处：kb 配置开启时视频解析完成自动入队；按需 API 显式触发。
引擎（engines/video_narrative）只管合成；块来源、落库、状态机归本服务。
"""

from novamind.core.database.base import Base  # noqa: F401  # 确保元数据已注册
from novamind.features.knowledge_space.models.video_narrative import (
    VideoNarrative,
    VideoNarrativeStatus,
)
from novamind.shared.logging import get_logger
from novamind.shared.utils.time_utils import now_china

logger = get_logger(__name__)


class VideoNarrativeService:
    """视频叙事文档服务：合成、落库、读取、检索回链。"""

    def __init__(self, session, llm_client=None, llm_model: str = ""):
        """请求级会话 + 合成用 LLM 客户端（引擎直收）。

        Args:
            session: 异步数据库会话。
            llm_client: LLM 客户端实例（引擎直收；None 仅支持读取）。
            llm_model: 合成用模型名（落库记录）。
        """
        self.session = session
        self.llm_client = llm_client
        self.llm_model = llm_model

    # ========== 合成编排 ==========

    async def synthesize(self, *, space_id: int, kb_id: int, document_id: int,
                         batch_size: int = 12) -> dict:
        """拉取视频块 → 引擎合成 → 落库（覆盖式，每文档一份）。

        Returns:
            {"status": "completed"|"failed", "chunks_used": int, "error": str|None}
        """
        from novamind.engines.video_narrative import (
            NarrativeBlock,
            VideoNarrativeSynthesizer,
        )
        from novamind.shared.storage.client_factory import get_elasticsearch_client

        await self._upsert_running(space_id, kb_id, document_id)
        try:
            wrapper = await get_elasticsearch_client()
            es = wrapper.es_client
            # ES 索引按空间维度命名（space_{space_id}），与检索/入库同键——不能用 kb_id
            idx = wrapper.generate_index_name(space_id)
            r = await es.search(index=idx, body={
                "query": {"term": {"document_id": document_id}},
                "size": 1000, "sort": [{"chunk_index": "asc"}],
                "_source": ["chunk_index", "content", "metadata"],
            })
            blocks = []
            for hit in r["hits"]["hits"]:
                src = hit["_source"]
                meta = src.get("metadata") or {}
                t0 = meta.get("start_time")
                t1 = meta.get("end_time")
                blocks.append({
                    "chunk_index": src.get("chunk_index"),
                    "t0": float(t0) if t0 is not None else None,
                    "t1": float(t1) if t1 is not None else None,
                    "text": (src.get("content") or "").strip(),
                })
            # 时间锚缺失的块：按 chunk_index 序补均匀时间轴（0-100 归一），保证可合成
            known = [b for b in blocks if b["t0"] is not None and b["t1"] is not None]
            for i, b in enumerate(blocks):
                if b["t0"] is None and known:
                    b["t0"] = round(100.0 * i / max(1, len(blocks)), 1)
                    b["t1"] = round(100.0 * (i + 1) / max(1, len(blocks)), 1)
            blocks = [b for b in blocks if b["text"]]

            engine = VideoNarrativeSynthesizer(self.llm_client, batch_size=batch_size)
            nblocks = [
                NarrativeBlock(start_time=b["t0"], end_time=b["t1"],
                               text=b["text"], chunk_index=b["chunk_index"])
                for b in blocks
            ]
            doc = await engine.synthesize(nblocks)

            await self._save_record(
                space_id=space_id, kb_id=kb_id, document_id=document_id,
                status=VideoNarrativeStatus.COMPLETED,
                overview=doc.overview,
                chapters=[{
                    "title": ch.title, "start_time": ch.start_time,
                    "end_time": ch.end_time, "summary": ch.summary,
                    "chunk_indices": ch.chunk_indices,
                } for ch in doc.chapters],
                content_md=doc.to_markdown(f"视频叙事文档（文档 {document_id}）"),
            )
            logger.info(
                "视频叙事文档合成完成", document_id=document_id,
                chapters=len(doc.chapters), blocks_used=len(nblocks),
            )
            return {"status": "completed", "chunks_used": len(nblocks), "error": None}
        except Exception as exc:
            await self._save_record(
                space_id=space_id, kb_id=kb_id, document_id=document_id,
                status=VideoNarrativeStatus.FAILED, error_message=str(exc),
            )
            logger.warning("视频叙事文档合成失败", document_id=document_id, error=str(exc))
            return {"status": "failed", "chunks_used": 0, "error": str(exc)}

    # ========== 读取与检索回链 ==========

    async def get_by_document(self, document_id: int) -> VideoNarrative | None:
        from sqlalchemy import select
        r = await self.session.execute(
            select(VideoNarrative).where(VideoNarrative.document_id == document_id)
        )
        return r.scalar_one_or_none()

    async def get_completed_with_chapters(self, document_id: int) -> dict | None:
        """检索回链用：已完成叙事的章节列表（含 chunk_indices 与摘要）。"""
        record = await self.get_by_document(document_id)
        if record is None or record.status != VideoNarrativeStatus.COMPLETED:
            return None
        chapters = record.chapters if isinstance(record.chapters, list) else []
        return {
            "overview": record.overview,
            "llm_model": record.llm_model,
            "chapters": chapters,
        }

    # ========== 内部 ==========

    async def _upsert_running(self, space_id: int, kb_id: int, document_id: int) -> VideoNarrative:
        from sqlalchemy import select
        r = await self.session.execute(
            select(VideoNarrative).where(VideoNarrative.document_id == document_id)
        )
        record = r.scalar_one_or_none()
        if record is None:
            record = VideoNarrative(
                space_id=space_id, kb_id=kb_id, document_id=document_id,
                status=VideoNarrativeStatus.RUNNING, llm_model=self.llm_model,
                created_at=now_china(), updated_at=now_china(),
            )
            self.session.add(record)
        else:
            record.status = VideoNarrativeStatus.RUNNING
            record.llm_model = self.llm_model
            record.error_message = None
            record.updated_at = now_china()
        await self.session.commit()
        return record

    async def _save_record(self, *, space_id: int, kb_id: int, document_id: int,
                           status: int, overview: str | None = None,
                           chapters: list | None = None,
                           content_md: str | None = None,
                           error_message: str | None = None) -> None:
        from sqlalchemy import select
        r = await self.session.execute(
            select(VideoNarrative).where(VideoNarrative.document_id == document_id)
        )
        record = r.scalar_one_or_none()
        if record is None:
            record = VideoNarrative(
                space_id=space_id, kb_id=kb_id, document_id=document_id,
                created_at=now_china(), updated_at=now_china(),
            )
            self.session.add(record)
        record.status = status
        record.overview = overview
        record.chapters = chapters
        record.content_md = content_md
        record.error_message = error_message
        record.updated_at = now_china()
        await self.session.commit()
