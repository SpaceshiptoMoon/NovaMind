"""跨空间全局检索服务：消费侧一步直达的知识检索入口。

解析用户可访问空间（活跃成员空间 ∪ 公开活跃空间），按知识库 fan-out
复用单库检索段，RRF 合并后统一做文档级权限过滤与单次 LLM 回答。
继承 SearchService（同 InstrumentedSearchService 惯例）：单库检索/
客户端解析/回答生成/帧图预签名全部复用，本类只加跨库编排。

embedding 模型是空间级配置，跨空间多索引向量查询在维度不一致时不可行
——fan-out 让每个空间用自己的 embedding 查自己的索引，维度差异被天然
隔离；RRF 按名次融合，规避跨模型分数不可比。
"""

import asyncio
import time
from typing import Any

from novamind.features.knowledge_space.exceptions import EmbeddingError
from novamind.features.knowledge_space.models.knowledge_base import KnowledgeBase
from novamind.features.knowledge_space.models.knowledge_space import KnowledgeSpace
from novamind.features.knowledge_space.schemas.search_schema import (
    SEARCH_MODE_FALLBACK,
    GlobalSearchRequest,
    SearchRequest,
)
from novamind.features.knowledge_space.services.document_permission_filter import (
    get_hidden_doc_ids_map,
)
from novamind.features.knowledge_space.services.search_service import SearchService
from novamind.setting.yaml_config import get_config
from novamind.shared.ai_models.embedding import BaseEmbedding

# RRF 平滑常数：与引擎子问题融合/ES rrf_fuse 的 k=60 同量级（名次融合，
# 跨库分数不可比，只用排名）
_GLOBAL_RRF_K = 60


def _mode_str(mode: Any) -> str:
    """SearchMode 枚举/字符串统一转字符串。"""
    return str(mode.value) if hasattr(mode, "value") else str(mode)


class GlobalSearchService(SearchService):
    """跨空间全局检索：可访问空间解析 → 按库 fan-out → RRF 合并。"""

    async def global_search(self, user_id: int, request: GlobalSearchRequest) -> dict[str, Any]:
        """执行跨空间全局检索。

        Args:
            user_id: 触发用户（权限范围与模型凭证解析主体）。
            request: 全局检索请求。

        Returns:
            响应字典（含 space_result_counts 内部键，路由层据此逐空间落审计，
            不进响应 schema）。
        """
        start_time = time.time()
        requested_mode = _mode_str(request.search_mode)

        # 1. DB 预取（串行：请求级 session 不能并发共享；后续检索阶段零请求级 DB 依赖）
        spaces = await self.space_repo.get_accessible_spaces(user_id)
        space_by_id = {s.id: s for s in spaces}
        kbs = await self.kb_repo.get_active_by_space_ids(list(space_by_id))

        skipped_kbs: list[dict[str, Any]] = []
        max_kbs = get_config().knowledge_base.retrieval.global_search_max_kbs
        if len(kbs) > max_kbs:
            for kb in kbs[max_kbs:]:
                skipped_kbs.append(
                    {"kb_id": kb.id, "kb_name": kb.name, "space_id": kb.space_id, "reason": "fan_out_limit"}
                )
            kbs = kbs[:max_kbs]

        hidden_by_space = await get_hidden_doc_ids_map(
            self.session, user_id, list(space_by_id)
        )

        # 2. 预解析 embedding 客户端（按空间 distinct 模型串行完成；失败模型
        #    回退 BM25 而非整次全局检索失败）
        embedding_clients, unavailable_models = await self._resolve_embedding_clients(
            user_id, spaces
        )

        # 3. 并发 fan-out：单库失败只跳过该库（进 skipped_kbs），不炸全局
        outcomes = await asyncio.gather(
            *(
                self._search_one_kb(
                    kb, user_id, request, space_by_id,
                    embedding_clients, unavailable_models, requested_mode,
                )
                for kb in kbs
            ),
            return_exceptions=True,
        )
        per_kb: list[tuple[KnowledgeBase, list[dict[str, Any]]]] = []
        for kb, outcome in zip(kbs, outcomes):
            if isinstance(outcome, BaseException):
                self.logger.warning(
                    "全局检索单库失败（跳过）", kb_id=kb.id, error=str(outcome)
                )
                skipped_kbs.append(
                    {"kb_id": kb.id, "kb_name": kb.name, "space_id": kb.space_id, "reason": "error"}
                )
            else:
                per_kb.append((kb, outcome))

        # 4. RRF 合并 → 盖来源戳 → 文档级权限过滤 → 截断（先滤后裁：宁少给不给错）
        merged = self._merge_and_stamp(per_kb, space_by_id)
        merged = self._filter_by_document_permission(merged, hidden_by_space)
        merged = merged[: request.top_k]
        elapsed_ms = (time.time() - start_time) * 1000

        # 5. LLM 单次回答（合并 Top5；_generate_llm_answer 内部容错降级 answer_error）
        answer_payload: dict[str, Any] = {}
        if request.llm and request.llm.enabled and merged:
            try:
                llm_result = await self._generate_llm_answer(
                    query=request.query,
                    results=merged,
                    llm_config=request.llm,
                    user_id=user_id,
                )
                answer_payload = {
                    "answer": llm_result.get("answer"),
                    "answer_model": llm_result.get("model"),
                    "answer_elapsed_ms": llm_result.get("elapsed_ms"),
                }
                if llm_result.get("answer_error"):
                    answer_payload["answer_error"] = llm_result["answer_error"]
            except Exception as e:
                self.logger.error("全局检索 LLM 回答生成异常", error=str(e))
                answer_payload = {"answer_error": str(e)}

        # 6. 帧图预签名（复用单库链路的展示层收尾）
        await self._presign_frame_urls(merged)

        # 7. 逐空间结果计数（路由层据此逐空间落审计，运营区「最近提问」可见全局检索）
        space_result_counts: dict[int, int] = {}
        for r in merged:
            sid = r.get("space_id")
            if sid is not None:
                space_result_counts[sid] = space_result_counts.get(sid, 0) + 1

        return {
            "results": merged,
            "total": len(merged),
            "query": request.query,
            "search_mode": requested_mode,
            "top_k": request.top_k,
            "elapsed_ms": elapsed_ms,
            "searched_kbs": len(per_kb),
            "skipped_kbs": skipped_kbs,
            "space_result_counts": space_result_counts,
            **answer_payload,
        }

    async def _resolve_embedding_clients(
        self,
        user_id: int,
        spaces: list[KnowledgeSpace],
    ) -> tuple[dict[str, BaseEmbedding], set[str]]:
        """按空间 distinct 模型预解析 embedding 客户端（fan-out 前串行完成）。

        失败方向安全：解析失败（凭证缺失/失配）的模型记入不可用集，相关
        空间回退 BM25 模式，而非整次全局检索失败。

        Args:
            user_id: 凭证归属用户。
            spaces: 可访问空间列表。

        Returns:
            (模型名 → 客户端映射, 解析失败的模型名集合)。
        """
        models = {s.embedding_model for s in spaces if s.embedding_model}
        clients: dict[str, BaseEmbedding] = {}
        unavailable: set[str] = set()
        for model in models:
            try:
                clients[model] = await self._get_embedding_client(user_id, model)
            except Exception as e:
                unavailable.add(model)
                self.logger.warning(
                    "全局检索 embedding 客户端解析失败（该模型空间回退 BM25）",
                    model=model,
                    error=str(e),
                )
        return clients, unavailable

    def _resolve_mode_for_kb(
        self,
        requested_mode: str,
        kb: KnowledgeBase,
        space: KnowledgeSpace,
        unavailable_models: set[str],
    ) -> str:
        """按 KB 能力与空间 embedding 可用性回退模式（content_* 恒可达）。

        两级回退：库未启用问题生成 → SEARCH_MODE_FALLBACK 链降 content_*；
        空间无 embedding 模型或该模型客户端解析失败 → 向量/混合降 BM25。

        Args:
            requested_mode: 请求的检索模式。
            kb: 目标知识库。
            space: 目标空间（embedding 模型配置来源）。
            unavailable_models: 解析失败的 embedding 模型集合。

        Returns:
            该库实际执行的模式。
        """
        mode = requested_mode
        if mode not in kb.get_available_search_modes():
            mode = SEARCH_MODE_FALLBACK.get(mode, "content_hybrid")
        if ("vector" in mode or "hybrid" in mode) and (
            not space.embedding_model or space.embedding_model in unavailable_models
        ):
            mode = mode.replace("vector", "bm25").replace("hybrid", "bm25")
        return mode

    async def _search_one_kb(
        self,
        kb: KnowledgeBase,
        user_id: int,
        request: GlobalSearchRequest,
        space_by_id: dict[int, KnowledgeSpace],
        embedding_clients: dict[str, BaseEmbedding],
        unavailable_models: set[str],
        requested_mode: str,
    ) -> list[dict[str, Any]]:
        """单库检索任务体（fan-out 并发调用）：模式回退 → 复用单库检索段。

        向量调用期失败（配额限流/凭证失效在调用时才暴露）回退 BM25 重试
        一次——单库的 embedding 故障不该让该库在全局结果里整体缺席。
        """
        space = space_by_id[kb.space_id]
        mode = self._resolve_mode_for_kb(requested_mode, kb, space, unavailable_models)

        async def _space_lookup(space_id: int) -> KnowledgeSpace | None:
            return space_by_id.get(space_id)

        def _make_request(search_mode: str) -> SearchRequest:
            return SearchRequest(
                query=request.query,
                search_mode=search_mode,
                top_k=request.top_k,
                score_threshold=request.score_threshold,
                filters=request.filters,
                use_cache=request.use_cache,
            )

        async def _retrieve(search_mode: str):
            # 预取数据闭合：注入预构建 embedding 客户端与空间查表，检索段零请求级 DB
            embedding_client_resolver = None
            if "vector" in search_mode or "hybrid" in search_mode:
                client = embedding_clients[space.embedding_model]

                async def _prebuilt_embedding() -> BaseEmbedding | None:
                    return client

                embedding_client_resolver = _prebuilt_embedding
            return await self.retrieve_for_kb(
                kb, user_id, _make_request(search_mode),
                space_lookup=_space_lookup,
                embedding_client_resolver=embedding_client_resolver,
            )

        try:
            result = await _retrieve(mode)
        except EmbeddingError as e:
            if "vector" not in mode and "hybrid" not in mode:
                raise
            fallback_mode = mode.replace("vector", "bm25").replace("hybrid", "bm25")
            self.logger.warning(
                "全局检索向量调用失败，该库回退 BM25",
                kb_id=kb.id, mode=mode, fallback_mode=fallback_mode, error=str(e),
            )
            result = await _retrieve(fallback_mode)
        return result.results

    def _merge_and_stamp(
        self,
        per_kb: list[tuple[KnowledgeBase, list[dict[str, Any]]]],
        space_by_id: dict[int, KnowledgeSpace],
    ) -> list[dict[str, Any]]:
        """RRF 融合各库结果并盖空间/知识库来源戳。

        跨库分数来自不同 embedding/检索配置，不可直接比大小——按库内名次
        以 1/(k+rank) 累加融合（与引擎子问题融合同思路）。库内列表按 score
        降序防御性重排（引擎返回已排序，此处兜底）。合并键为 (kb_id,
        chunk_id)：chunk_id 仅库内唯一，跨库可撞名。

        Args:
            per_kb: 各库 (知识库, 结果列表)。
            space_by_id: 空间预取映射（来源名称盖戳用）。

        Returns:
            融合排序后的结果列表（已带 space_id/space_name/kb_id/kb_name）。
        """
        rrf_scores: dict[tuple[int, str], float] = {}
        stamped: dict[tuple[int, str], dict[str, Any]] = {}
        for kb, results in per_kb:
            for rank, r in enumerate(
                sorted(results, key=lambda x: -float(x.get("score") or 0.0)), 1
            ):
                key = (kb.id, str(r.get("chunk_id")))
                rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (_GLOBAL_RRF_K + rank)
                item = dict(r)
                item["kb_id"] = kb.id
                item["kb_name"] = kb.name
                item["space_id"] = kb.space_id
                item["space_name"] = space_by_id[kb.space_id].name
                stamped[key] = item
        return sorted(
            stamped.values(),
            key=lambda item: -rrf_scores[(item["kb_id"], str(item["chunk_id"]))],
        )

    @staticmethod
    def _filter_by_document_permission(
        merged: list[dict[str, Any]],
        hidden_by_space: dict[int, list[int]],
    ) -> list[dict[str, Any]]:
        """按预取的逐空间隐藏清单过滤（保序单遍，语义同单库路径的结果层过滤）。

        top_k 截断在过滤后执行：隐藏文档的 chunk 同样占据融合名次——与
        单库路径同向（宁少给不给错）。非成员的 PUBLIC 空间无成员行 → 无
        隐藏清单（文档级权限只作用于显式成员）。
        """
        hidden_sets = {sid: set(ids) for sid, ids in hidden_by_space.items() if ids}
        if not hidden_sets:
            return merged
        return [
            r
            for r in merged
            if r.get("document_id")
            not in hidden_sets.get(r.get("space_id"), frozenset())
        ]
