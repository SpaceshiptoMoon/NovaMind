"""新版识别服务（kb-ops B2）：上传完成时判定同 KB 内是否存在疑似旧版。

判定保守（只建议不自动，安全硬规则）：仅当 (a) 归一化文件名高相似
（去扩展名/版本号后缀后完全一致或高相似），且 (b) 旧版仍是 active
（已 superseded/archived 的不再重复建议），才生成 new_version 建议。
阈值可配，默认保守；判据全部文件名级——chunk 级相似判定成本高且
文件名已是主信号，v1 不做（D 批次按误报率评估）。

失败方向安全：判定失败仅记日志，绝不影响上传主流程。
"""
from __future__ import annotations

import re

from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)

# 归一化文件名相似度阈值（0~1）：仅判定「去扩展名后完全一致」v1 口径——
# 字符相似度对文件名误报率高（"报告v1" vs "报告v2" 差异小但可能是不同文档），
# 完全一致（同文改名/同名校验场景）零误报，符合保守原则。
DEFAULT_FILENAME_SIMILARITY_THRESHOLD = 1.0

# 文件名归一化时剔除的版本号/日期后缀模式（v2、final、2024、20240101 等）
_VERSION_SUFFIX_PATTERN = re.compile(
    r"[\s_\-.]*("
    r"v\d+|final|draft|copy|备份|新版|旧版|最新"
    r"|\d{8}|\d{4}[-_.]\d{1,2}[-_.]\d{1,2}"
    r")$",
    re.IGNORECASE,
)


def normalize_filename(filename: str) -> str:
    """文件名归一化：去扩展名、去版本号/日期后缀、转小写、去空白。

    「退货政策v2.pdf」「退货政策_final.PDF」都归一到「退货政策」；
    归一化后一致即视为疑似新旧版本（v1 口径，零误报优先）。
    """
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    stem = stem.strip().lower()
    # 迭代剔除多级后缀（退货政策_v2_final → 退货政策）
    while True:
        stripped = _VERSION_SUFFIX_PATTERN.sub("", stem).strip()
        if stripped == stem or not stripped:
            break
        stem = stripped
    return stem


async def detect_new_version_suggestions(
    *,
    space_id: int,
    kb_id: int,
    new_doc_id: int,
) -> list[int]:
    """对新上传文档做新版判定，生成建议（幂等），返回新建建议 ID 列表。

    候选旧版 = 同 KB 内、active、文件名归一化一致、id 更小的文档
    （id 小 = 先上传 = 旧版；同 id 自身排除）。多候选全建（管理员自行裁决）。
    """
    try:
        from sqlalchemy import and_, select

        from novamind.core.database.database import get_db_session
        from novamind.features.knowledge_ops.repository.suggestion_repository import (
            STATUS_OPEN,
            SUGGESTION_NEW_VERSION,
            SuggestionRepository,
        )
        from novamind.features.knowledge_space.models.document import (
            Document,
            DocumentLifecycleStatus,
        )

        async with get_db_session() as session:
            new_doc = (await session.execute(
                select(Document).where(Document.id == new_doc_id)
            )).scalar_one_or_none()
            if new_doc is None or new_doc.deleted_at is not None:
                return []

            target = normalize_filename(new_doc.filename)
            if not target:
                return []

            # 候选：同 KB、active、存在更早上传的同归一化名文档
            rows = (await session.execute(
                select(Document.id, Document.filename)
                .where(and_(
                    Document.kb_id == kb_id,
                    Document.space_id == space_id,
                    Document.id != new_doc_id,
                    Document.id < new_doc_id,
                    Document.deleted_at.is_(None),
                    Document.lifecycle_status == DocumentLifecycleStatus.ACTIVE,
                ))
                .order_by(Document.id.desc())
                .limit(20)
            )).all()

            # 归一化过滤（SQL 内做不了归一化，行数有限取回内存过滤）
            candidates = [
                (r.id, r.filename) for r in rows
                if normalize_filename(r.filename) == target
            ]
            if not candidates:
                return []

            repo = SuggestionRepository(session)
            created_ids: list[int] = []
            for old_id, old_name in candidates:
                suggestion = await repo.upsert_open_suggestion(
                    space_id=space_id,
                    kb_id=kb_id,
                    suggestion_type=SUGGESTION_NEW_VERSION,
                    old_doc_id=old_id,
                    new_doc_id=new_doc_id,
                    score=10000,  # 文件名归一化完全一致 = 满分
                    reason=f"文件名「{old_name}」与新文档「{new_doc.filename}」归一化后一致，疑似同一内容的新旧版本",
                )
                if suggestion is not None:
                    created_ids.append(suggestion.id)
            await session.commit()
            if created_ids:
                logger.info(
                    "新版识别建议已生成",
                    kb_id=kb_id, new_doc_id=new_doc_id, suggestions=created_ids,
                )
            return created_ids
    except Exception as e:
        # 旁路语义：判定失败不影响上传主流程
        logger.warning(
            "新版识别判定失败（已忽略）", kb_id=kb_id, new_doc_id=new_doc_id, error=str(e)
        )
        return []
