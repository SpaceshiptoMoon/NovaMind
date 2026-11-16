"""评测归因分析引擎：五阶段 15 类错误判定（决策树，批次 E1）。

分类法（按数据流向五阶段，每类指向不同处置方）：

    源数据 S ──→ 解析入库 P ──→ 检索 R ──→ 生成 G ──→ 问题侧 Q

    S1 source_missing        源数据缺失（知识库未覆盖，进 gap 流）
    S2 source_defect         源文档本身错/过时（修源文档）
    P1 parse_failed          解析失败/降级（重解析）
    P2 parse_defect          解析质量缺陷（源对但 chunk 丢失/错乱）
    P3 chunk_fragmentation   切分问题（内容在但被切碎）
    P4 index_sync_missing    索引同步缺失（文档在、chunk 未入索引）
    R1 ranking_issue         排序问题（召回但排不进/被阈值滤掉）
    R2 mode_mismatch         检索模式失配
    R3 embedding_gap         向量缺口（在索引但语义检索不到）
    R5 permission_boundary   权限边界（被 hidden_doc_ids 挡住）
    G1 context_underuse      上下文利用不足（含答案没答出，prompt/模型）
    G2 hallucination         幻觉（答案与上下文矛盾）
    Q1 case_label_error      用例标注错误（假阴性）
    Q2 case_out_of_scope     用例超范围/歧义
    Q3 query_quality         query 表述问题（归一化后可命中）

与线上点踩归因（kb-ops A1 四分法）的词表映射：S1↔content_gap、
R1/R2/R3↔retrieval_failure——测试集批量归因与线上单点归因同词表汇入质检。

判定链成本分层：L0-L3 重放（零 LLM）→ 任务表/归一化重搜（零 LLM）→
Q2/G 链 LLM 判定（仅失败用例触发）；P2/S2 深检由 attribution_deep_check
开关控制。失败方向安全：任何判定异常降级到下一级或兜底，绝不影响评测本身。
"""
from __future__ import annotations

import json
import re
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.features.evaluation.schemas.evaluation_schema import EvaluationConfig

logger = get_logger(__name__)

# 生成侧失败线（10 分制及格线，与 _build_recommendations 的低生成线同源）
GENERATION_FAIL_SCORE = 5.0
# 命中 chunk 碎片占比超过该线判切分问题（与 _RECOMMEND_FRAGMENT_RATIO 同量级）
_FRAGMENT_RATIO_THRESHOLD = 0.3

ATTR_STAGE_BY_CATEGORY: dict[str, str] = {
    "source_missing": "S",
    "source_defect": "S",
    "parse_failed": "P",
    "parse_defect": "P",
    "chunk_fragmentation": "P",
    "index_sync_missing": "P",
    "ranking_issue": "R",
    "mode_mismatch": "R",
    "embedding_gap": "R",
    "permission_boundary": "R",
    "context_underuse": "G",
    "hallucination": "G",
    "case_label_error": "Q",
    "case_out_of_scope": "Q",
    "query_quality": "Q",
}

ATTRIBUTION_SUGGESTIONS: dict[str, str] = {
    "source_missing": "知识库未覆盖该问题——确认企业内是否有对应文档未入库（催收），或需要新创作（进运营缺口流）",
    "source_defect": "源文档内容本身过时/错误——定位到文档做复审或版本替换",
    "parse_failed": "文档解析失败或走了降级路径——重解析或更换解析器配置",
    "parse_defect": "源文档正确但解析后内容丢失/错乱（表格碎、双栏乱、跨页断）——检查解析配置后重解析",
    "chunk_fragmentation": "内容在但被切碎，上下文不完整——增大切分块或改语义切分后重切",
    "index_sync_missing": "文档存在但 chunk 未生成或未同步进索引——重建索引/补解析",
    "ranking_issue": "内容已召回但未进入返回窗口——建议开启 Rerank、调整检索权重或增大 top_k",
    "mode_mismatch": "内容可召回但当前检索模式不适合该类问题——建议切换 search_mode",
    "embedding_gap": "目标来源已在索引中但语义检索不到——检查 embedding 模型适配性或补充相近措辞",
    "permission_boundary": "目标内容被知识库权限过滤挡在检索之外——检查文档可见性配置",
    "context_underuse": "上下文包含答案所需信息但模型未答出——调整生成 prompt 或更换模型",
    "hallucination": "答案与提供的上下文矛盾——模型忠实度问题，检查模型选择与 prompt 约束",
    "case_label_error": "答案语义上正确但被判失败——修正测试集标注，防止假阴性污染指标",
    "case_out_of_scope": "问题超出知识库定位或本身歧义——修正用例或移出测试集",
    "query_quality": "query 表述与文档词表不匹配（归一化后可命中）——优化用例表述或检索改写配置",
}

# 换模式重放的候选顺序（hybrid 系优先；与原 service 常量同源）
_REPLAY_FALLBACK_MODES = ["content_hybrid", "question_hybrid", "all_hybrid", "content_bm25", "question_bm25"]

# LLM 判定的 JSON 提取兜底（模型输出可能带 markdown 围栏或前后杂文）
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _chunk_matches_expected(chunk: dict[str, Any], expected: set[str]) -> bool:
    """单条检索结果是否命中期望来源（chunk_id 或 document_id 相等即命中）。"""
    if str(chunk.get("chunk_id", "")) in expected:
        return True
    doc_id = chunk.get("document_id")
    if doc_id is None and isinstance(chunk.get("source"), dict):
        doc_id = chunk["source"].get("document_id")
    return doc_id is not None and str(doc_id) in expected


class AttributionAnalyzer:
    """失败用例归因判定器（检索 miss 链 + 生成侧链，决策树全链路）。

    依赖注入而非自取：检索端口（重放）/DB 会话（任务表判定）/LLM 客户端
    （Q2 与生成侧链）全部由调用方传入——汇总段执行流里就地装配，测试可全 mock。
    """

    def __init__(
        self,
        *,
        svc: Any,
        session: Any = None,
        llm_client: Any = None,
        es_client: Any = None,
        prompt_manager: Any = None,
    ):
        self.svc = svc
        self.session = session
        self.llm_client = llm_client
        self.es_client = es_client
        if prompt_manager is None:
            from novamind.shared.prompts.prompt_manager import PromptManager

            prompt_manager = PromptManager()
        self.prompts = prompt_manager

    # ========== 入口 ==========

    async def diagnose_case(
        self,
        *,
        case_detail: dict[str, Any],
        raw_case: dict[str, Any],
        test_set_obj: Any,
        config: EvaluationConfig,
        user_id: int,
    ) -> dict[str, Any] | None:
        """对一条失败用例判根因：先定环节，再走对应判定链。

        Args:
            case_detail: 评估明细（_evaluate_single_case 产物，含 retrieval/
                generated_answer/generation_scores/retrieved_chunks）。
            raw_case: 原始用例（含 contexts/expected_sources）。
            test_set_obj: 测试集 ORM（归属域）。
            config: 任务配置（deep_check 开关在 config 上）。
            user_id: 任务发起人（检索重放权限域）。

        Returns:
            {stage, category, evidence, confidence}；判不出（如无 LLM 的
            生成侧）返回 None。全程异常安全，绝不影响评测主流程。
        """
        try:
            retrieval = case_detail.get("retrieval") or {}
            if retrieval.get("skipped"):
                # gold-only 用例：跳过检索环节，直接生成侧链
                return await self._diagnose_generation(
                    case_detail, raw_case, test_set_obj, config, user_id
                )
            if not retrieval.get("hit"):
                return await self._diagnose_miss(
                    case_detail, raw_case, test_set_obj, config, user_id
                )
            if self._generation_failed(case_detail):
                return await self._diagnose_generation(
                    case_detail, raw_case, test_set_obj, config, user_id
                )
            return None  # 检索命中且生成正常——成功用例不归因
        except Exception as e:
            logger.warning("归因判定异常（跳过）", question=str(case_detail.get("question"))[:50], error=str(e))
            return None

    @staticmethod
    def _generation_failed(case_detail: dict[str, Any]) -> bool:
        """生成侧失败：任一核心维度低于及格线（10 分制）。"""
        scores = case_detail.get("generation_scores") or {}
        for key in ("correctness", "quality", "overall"):
            value = scores.get(key)
            if isinstance(value, tuple):
                value = value[0]
            if isinstance(value, (int, float)) and value < GENERATION_FAIL_SCORE:
                return True
        return False

    @staticmethod
    def _result(category: str, evidence: str, confidence: str = "high") -> dict[str, Any]:
        stage = ATTR_STAGE_BY_CATEGORY.get(category, "?")
        return {
            "stage": stage,
            "category": category,
            "evidence": evidence,
            "confidence": confidence,
            "suggestion": ATTRIBUTION_SUGGESTIONS.get(category, ""),
        }

    # ========== 检索 miss 链（L0 → S1） ==========

    async def _diagnose_miss(
        self,
        case_detail: dict[str, Any],
        raw_case: dict[str, Any],
        test_set_obj: Any,
        config: EvaluationConfig,
        user_id: int,
    ) -> dict[str, Any] | None:
        question = case_detail.get("question") or raw_case.get("question") or ""
        expected_sources = raw_case.get("expected_sources") or []
        expected = {str(s) for s in expected_sources}

        # L0 权限旁路
        chunks = await self._replay(test_set_obj, user_id, question, config, bypass=True)
        if expected and any(_chunk_matches_expected(c, expected) for c in chunks):
            return self._result("permission_boundary", "权限旁路重放命中目标来源")

        # L1 扩窗 + 去阈值
        wide_k = max(config.top_k * 3, 15)
        chunks = await self._replay(test_set_obj, user_id, question, config, top_k=wide_k, threshold=0.0)
        if expected and any(_chunk_matches_expected(c, expected) for c in chunks):
            return self._result("ranking_issue", f"扩窗重放（top_k={wide_k}，阈值 0）命中目标来源")

        # L2 换候选模式
        for mode in _REPLAY_FALLBACK_MODES:
            if mode == config.search_mode:
                continue
            chunks = await self._replay(test_set_obj, user_id, question, config, mode=mode, threshold=0.0)
            if expected and any(_chunk_matches_expected(c, expected) for c in chunks):
                return self._result("mode_mismatch", f"切换检索模式 {mode} 后命中目标来源")

        # Q3 query 表述：归一化重搜（零 LLM）
        from novamind.features.knowledge_ops.services.query_reformulate_detector import (
            normalize_query,
        )

        normalized = normalize_query(question)
        if normalized and normalized != question:
            chunks = await self._replay(
                test_set_obj, user_id, normalized, config, mode="content_bm25", threshold=0.0
            )
            if any(_chunk_matches_expected(c, expected) for c in chunks):
                return self._result("query_quality", "query 归一化后 BM25 重放命中目标来源")

        # L3 索引存在性直查
        source_in_index = await self._es_source_in_index(test_set_obj, expected_sources)
        if source_in_index:
            return self._result("embedding_gap", "目标来源已在索引中，但各级重放均未召回")

        # P1/P4：ES 无 chunk → 查解析任务状态（期望源是文档 ID 才可定位）
        doc_ids = [int(s) for s in expected_sources if str(s).isdigit()]
        if doc_ids:
            pipeline = await self._diagnose_pipeline(doc_ids)
            if pipeline is not None:
                return pipeline

        # Q2 超范围（LLM 拦截，判不出/无 LLM 则落到 S1 兜底）
        out_of_scope = (
            await self._llm_scope_check(question, test_set_obj) if self.llm_client else False
        )
        if out_of_scope:
            return self._result("case_out_of_scope", "LLM 判定问题超出知识库定位或本身歧义", "medium")

        return self._result(
            "source_missing", "各级重放与索引直查均未找到目标内容，判定知识库未覆盖", "medium"
        )

    async def _diagnose_pipeline(self, doc_ids: list[int]) -> dict[str, Any] | None:
        """P1/P4 判定：按文档最新任务行区分解析失败与索引同步缺失。

        Returns:
            归因 dict；文档都不存在或无可判任务行时 None（落 S1 兜底）。
        """
        if self.session is None:
            return None
        try:
            from novamind.features.knowledge_space.models.document import Document
            from novamind.features.knowledge_space.models.document_task import (
                DocumentTask,
                TaskStatus,
            )
            from sqlalchemy import func, select

            rows = (
                await self.session.execute(
                    select(Document.id, DocumentTask.status).join(
                        DocumentTask, DocumentTask.document_id == Document.id
                    ).where(
                        Document.id.in_(doc_ids),
                        Document.deleted_at.is_(None),
                        DocumentTask.id.in_(
                            select(func.max(DocumentTask.id))
                            .where(DocumentTask.document_id.in_(doc_ids))
                            .group_by(DocumentTask.document_id)
                            .scalar_subquery()
                        ),
                    )
                )
            ).all()
            if not rows:
                return None  # 文档不存在 → S1
            statuses = {status for _, status in rows}
            if TaskStatus.FAILED in statuses:
                return self._result("parse_failed", "文档最新解析任务失败", "high")
            if statuses & {TaskStatus.PENDING, TaskStatus.PROCESSING}:
                return self._result("parse_failed", "文档解析尚未完成（任务排队/执行中）", "high")
            return self._result(
                "index_sync_missing", "文档解析已完成但 chunk 未进入检索索引", "high"
            )
        except Exception as e:
            logger.warning("P1/P4 任务表判定失败（跳过）", error=str(e))
            return None

    async def _es_source_in_index(self, test_set_obj: Any, expected_sources: list[str]) -> bool:
        """期望来源是否存在于 ES 索引（文档 ID 直查 / chunk_exists）。"""
        if not expected_sources:
            return False
        try:
            if self.es_client is None:
                from novamind.shared.storage.client_factory import get_elasticsearch_client

                self.es_client = await get_elasticsearch_client()
            for source in expected_sources:
                if str(source).isdigit():
                    if (
                        await self.es_client.get_document_chunks(
                            test_set_obj.space_id, int(source)
                        )
                    ).get("total", 0) > 0:
                        return True
                elif await self.es_client.chunk_exists(test_set_obj.space_id, str(source)):
                    return True
            return False
        except Exception as e:
            logger.warning("ES 索引直查失败（按不在索引处理）", error=str(e))
            return False

    # ========== 生成侧链（G1 → G2 三分） ==========

    async def _diagnose_generation(
        self,
        case_detail: dict[str, Any],
        raw_case: dict[str, Any],
        test_set_obj: Any,
        config: EvaluationConfig,
        user_id: int,
    ) -> dict[str, Any] | None:
        question = case_detail.get("question") or ""
        expected_answer = case_detail.get("expected_answer") or ""
        generated = case_detail.get("generated_answer")
        if not generated or not self.llm_client:
            # 无答案可判（enable_generation 关）或无 LLM——生成侧归因不可用
            return None

        gold_chunks = [
            {"chunk_id": f"gold_{i}", "content": c, "score": 1.0}
            for i, c in enumerate(raw_case.get("contexts") or [])
        ]
        retrieved = case_detail.get("retrieved_chunks") or []

        # G1 gold 替换重生成：有 gold contexts 时，换正确上下文答案是否变好
        if gold_chunks:
            regenerated = await self._generate_answer(question, gold_chunks)
            if regenerated:
                improved = await self._llm_answer_improved(question, expected_answer, generated, regenerated)
                if improved:
                    # 上下文次优：碎片率高判切分问题，否则并回排序问题
                    if self._fragment_ratio(retrieved or gold_chunks) > _FRAGMENT_RATIO_THRESHOLD:
                        return self._result(
                            "chunk_fragmentation", "gold 上下文替换后答案改善，且命中 chunk 碎片占比高"
                        )
                    return self._result(
                        "ranking_issue", "gold 上下文替换后答案改善（召回上下文次优的生成侧表现）"
                    )

        # G2 语义比对：答案其实对（标注错误拦截）
        if await self._llm_semantic_match(question, expected_answer, generated):
            return self._result("case_label_error", "LLM 判定生成答案与期望语义一致", "medium")

        # G2 忠实度：答案与上下文矛盾（幻觉）
        context_chunks = retrieved or gold_chunks
        if context_chunks and await self._llm_contradicts_context(generated, context_chunks):
            return self._result("hallucination", "LLM 判定答案与提供的上下文矛盾", "medium")

        # G2 充分性：上下文是否包含回答所需信息
        sufficient = (
            await self._llm_context_sufficient(question, expected_answer, context_chunks)
            if context_chunks
            else None
        )
        if sufficient is False:
            # 上下文不含答案：deep_check 时进一步判「解析切丢 P2」vs「源文档本来没有 S2」
            if config.attribution_deep_check and context_chunks:
                parse_defect = await self._llm_source_compare(question, expected_answer, context_chunks)
                if parse_defect:
                    return self._result(
                        "parse_defect", "源文档应含该信息但解析/切分后丢失（LLM 对照判定）", "low"
                    )
            return self._result(
                "source_defect", "上下文未包含回答所需信息——源文档内容过时或不完整", "medium"
            )
        if sufficient is True:
            return self._result("context_underuse", "上下文包含答案所需信息但模型未答出", "medium")
        # 充分性判不出 → 不强行归因（失败方向安全：缺能力优于错结论）
        return None

    @staticmethod
    def _fragment_ratio(chunks: list[dict[str, Any]]) -> float:
        """命中 chunk 的碎片占比（短 chunk 计数/总数，零 LLM）。"""
        if not chunks:
            return 0.0
        seen: set[str] = set()
        short = total = 0
        for c in chunks:
            cid = str(c.get("chunk_id", ""))
            if cid in seen:
                continue
            seen.add(cid)
            total += 1
            if len(c.get("content", "")) < 50:
                short += 1
        return short / total if total else 0.0

    # ========== 重放与生成 ==========

    async def _replay(
        self,
        test_set_obj: Any,
        user_id: int,
        question: str,
        config: EvaluationConfig,
        *,
        mode: str | None = None,
        top_k: int | None = None,
        threshold: float | None = None,
        bypass: bool = False,
    ) -> list[dict[str, Any]]:
        """变体重放一次检索（未指定参数沿用任务配置）。"""
        from novamind.features.knowledge_space.schemas.search_schema import (
            SearchMode,
            SearchRequest,
        )

        request = SearchRequest(
            query=question,
            search_mode=SearchMode(mode or config.search_mode),
            top_k=top_k or config.top_k,
            score_threshold=config.score_threshold if threshold is None else threshold,
        )
        result = await self.svc.search(
            space_id=test_set_obj.space_id,
            kb_id=test_set_obj.kb_id,
            user_id=user_id,
            request=request,
            bypass_document_permission=bypass,
        )
        return result.get("results", []) or []

    async def _generate_answer(self, question: str, chunks: list[dict[str, Any]]) -> str | None:
        """基于给定上下文生成回答（gold 替换重生成用，复用评测同款模板）。"""
        context_text = "\n\n".join(f"[{i + 1}] {c.get('content', '')}" for i, c in enumerate(chunks))
        try:
            prompt = self.prompts.format_prompt("eval_generate_answer", context_text=context_text, question=question)
            return await self.llm_client.generate_text(prompt=prompt, max_tokens=1024, temperature=0.3)
        except Exception as e:
            logger.warning("归因重生成失败（跳过）", error=str(e))
            return None

    # ========== LLM 判定（每步失败降级，不阻断） ==========

    async def _llm_json(self, template_key: str, **variables: str) -> dict[str, Any] | None:
        """跑一个判定 prompt 并解析 JSON 输出；失败返回 None（调用方按降级处理）。"""
        try:
            prompt = self.prompts.format_prompt(template_key, **variables)
            raw = await self.llm_client.generate_text(prompt=prompt, max_tokens=512, temperature=0.0)
            if not raw:
                return None
            match = _JSON_OBJECT_RE.search(raw)
            if not match:
                return None
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception as e:
            logger.warning("归因 LLM 判定失败（降级）", template=template_key, error=str(e))
            return None

    async def _llm_scope_check(self, question: str, test_set_obj: Any) -> bool:
        """Q2：问题是否超出知识库定位或本身歧义。"""
        verdict = await self._llm_json(
            "eval_attr_scope_check",
            question=question[:500],
            kb_name=str(getattr(test_set_obj, "name", ""))[:100],
        )
        return bool(verdict and verdict.get("out_of_scope") is True)

    async def _llm_answer_improved(
        self, question: str, expected: str, original: str, regenerated: str
    ) -> bool:
        """G1：替换上下文后的答案是否明显更符合期望。"""
        verdict = await self._llm_json(
            "eval_attr_answer_compare",
            question=question[:500],
            expected=expected[:1000],
            original=original[:1000],
            regenerated=regenerated[:1000],
        )
        return bool(verdict and verdict.get("regenerated_better") is True)

    async def _llm_semantic_match(self, question: str, expected: str, generated: str) -> bool:
        """Q1：生成答案与期望答案是否语义一致。"""
        verdict = await self._llm_json(
            "eval_attr_semantic_match",
            question=question[:500],
            expected=expected[:1000],
            generated=generated[:1000],
        )
        return bool(verdict and verdict.get("semantically_equivalent") is True)

    async def _llm_contradicts_context(self, generated: str, chunks: list[dict[str, Any]]) -> bool:
        """D2：答案是否与上下文矛盾（幻觉的快速判定）。"""
        context_text = "\n\n".join(f"[{i + 1}] {c.get('content', '')[:400]}" for i, c in enumerate(chunks[:5]))
        verdict = await self._llm_json(
            "eval_attr_faithfulness_check", generated=generated[:1000], context_text=context_text[:3000]
        )
        return bool(verdict and verdict.get("contradicts") is True)

    async def _llm_context_sufficient(
        self, question: str, expected: str, chunks: list[dict[str, Any]]
    ) -> bool | None:
        """G2：上下文是否包含回答该问题所需的信息（None=判不出）。"""
        context_text = "\n\n".join(f"[{i + 1}] {c.get('content', '')[:400]}" for i, c in enumerate(chunks[:5]))
        verdict = await self._llm_json(
            "eval_attr_context_sufficiency",
            question=question[:500],
            expected=expected[:1000],
            context_text=context_text[:3000],
        )
        if verdict is None or "sufficient" not in verdict:
            return None
        return bool(verdict.get("sufficient"))

    async def _llm_source_compare(
        self, question: str, expected: str, chunks: list[dict[str, Any]]
    ) -> bool:
        """P2 深检：问题所需信息是否疑似存在于源文档但被解析/切分丢失。"""
        context_text = "\n\n".join(f"[{i + 1}] {c.get('content', '')[:400]}" for i, c in enumerate(chunks[:5]))
        verdict = await self._llm_json(
            "eval_attr_source_compare",
            question=question[:500],
            expected=expected[:1000],
            context_text=context_text[:3000],
        )
        return bool(verdict and verdict.get("info_cut_by_parsing") is True)
