"""批次 6a 接缝完成度回归测试。

守护批次 6a-1 ~ 6a-5 五项「引擎抽包前遗留端口」的切断不变式，防止回退（绑定规则 #4）：

  6a-1 Logger 注入：所有引擎候选模块零 ``novamind.core.middleware.structured_logging`` import。
  6a-2 RetrievalEngine 去宿主依赖：
    - 零 ``novamind.shared.cache.redis_client`` import；
    - 零自身 feature ``novamind.features.knowledge_space.api.exceptions`` import；
    - 中立 ``rag_errors`` 异常树与宿主 ``KnowledgeSpaceError`` 树隔离（不继承 BaseAPIError）；
    - ``HostCachePort`` 结构化满足 ``CachePort`` 协议。
  6a-3 RetrievalPort 去 schema 绑定：
    - 零 ``novamind.features.knowledge_space.schemas`` import；``search`` 入参去类型化为 ``Any``。
  6a-4 skill_checker 枚举下沉：
    - 零 ``novamind.features.skill.models`` import；
    - ``skill.models.skill.ReviewStatus`` 与中立 ``features.skill.ports.ReviewStatus`` 同一对象（ORM 兼容）。
  6a-5 audio_utils 去 ClientFactory：
    - 零 ``novamind.shared.clients`` import；
    - ``upload_parsed_text_to_minio`` / ``transcribe_audio_with_dashscope`` 的 ``minio_client`` 为关键字必传注入。
  通用不变式：引擎候选零**跨 feature** ``novamind.features.<Y>`` import（自身 feature 与 adapter 层除外）。

断言方式：AST 扫描引擎候选文件收集 import 模块名（精确，不受 docstring 文本干扰）+ 运行时协议/同一性检查。
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SRC = BACKEND_ROOT / "src"


# ---------- 引擎候选文件清单 ----------

ENGINE_CANDIDATE_DIRS = [
    SRC / "shared" / "ai_models",
    SRC / "shared" / "utils",
    SRC / "shared" / "storage",
    SRC / "shared" / "document",
    SRC / "engines" / "agent",
    SRC / "engines" / "rag",
    SRC / "engines" / "eval",
    SRC / "shared" / "clients" / "search",
]

ENGINE_CANDIDATE_FILES = [
    SRC / "features" / "skill" / "services" / "skill_checker.py",
]

# 宿主装配文件（非引擎逻辑）排除：``ClientFactory`` 是宿主客户端工厂，
# 由 startup_manager 调 ``ClientFactory.configure`` 注入策略后构造 MinIO/ES/Redis
# 客户端单例，合法直接 import ``shared.cache.redis_client`` 构造 ``RedisCache``，
# 不属于 6a-2「引擎候选不得直连 redis」不变式约束范围（ddab50a 把它从
# ``shared/clients`` 迁入 ``shared/storage`` 后被候选扫描误纳入，此处显式排除）。
ENGINE_CANDIDATE_EXCLUDE = {
    SRC / "shared" / "storage" / "client_factory.py",
}


def _collect_candidates() -> list[Path]:
    """收集所有引擎候选 .py 文件（递归目录 + 单文件，排除 __pycache__/__init__.py 可选保留）。"""
    seen: set[Path] = set()
    out: list[Path] = []
    for d in ENGINE_CANDIDATE_DIRS:
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                if p in ENGINE_CANDIDATE_EXCLUDE:
                    continue
                if p not in seen:
                    seen.add(p)
                    out.append(p)
    for f in ENGINE_CANDIDATE_FILES:
        if f.is_file() and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _imports_in(path: Path) -> set[str]:
    """AST 收集文件内所有 import 的模块全名（from-import module + import 语句 name）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
    return mods


def _own_feature(path: Path) -> str | None:
    """若候选在 ``features/<X>/`` 下，返回 feature 名 X；否则 None（shared/ 候选）。"""
    try:
        parts = path.relative_to(SRC).parts
    except ValueError:
        return None
    if parts and parts[0] == "features" and len(parts) > 1:
        return parts[1]
    return None


CANDIDATES = _collect_candidates()


# ---------- 6a-1：引擎候选零 core.middleware.structured_logging import ----------

def test_6a1_engine_candidates_have_no_structured_logging_import():
    """6a-1：引擎候选模块不得 import 宿主 ``core.middleware.structured_logging``。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        for mod in _imports_in(p):
            if mod == "novamind.core.middleware.structured_logging" or mod.startswith(
                "novamind.core.middleware.structured_logging."
            ):
                offenders.append(f"{p.relative_to(SRC)}: {mod}")
    assert not offenders, "引擎候选残留 structured_logging import:\n" + "\n".join(offenders)


# ---------- 6a-2：RetrievalEngine 去 cache.redis_client + api.exceptions ----------

def test_6a2_engine_candidates_have_no_shared_cache_redis_client_import():
    """6a-2：引擎候选不得 import ``shared.cache.redis_client``（改走 CachePort 注入）。"""
    offenders = [
        f"{p.relative_to(SRC)}: {mod}"
        for p in CANDIDATES
        for mod in _imports_in(p)
        if mod.startswith("novamind.shared.cache.redis_client")
    ]
    assert not offenders, "引擎候选残留 shared.cache.redis_client import:\n" + "\n".join(offenders)


def test_6a2_retrieval_engine_has_no_feature_exceptions_import():
    """6a-2：RetrievalEngine 不得 import 自身 feature ``api.exceptions``（改用中立 rag_errors）。"""
    p = SRC / "engines" / "rag" / "retrieval_engine.py"
    bad = [m for m in _imports_in(p) if m.startswith("novamind.features.knowledge_space.api.exceptions")]
    assert not bad, f"retrieval_engine 残留 api.exceptions import: {bad}"


def test_6a2_rag_errors_are_neutral_and_isolated_from_host_tree():
    """6a-2：中立 rag_errors 异常树与宿主 KnowledgeSpaceError 树隔离。"""
    from novamind.engines.rag.errors import RagError, EmbeddingError, SearchError
    from novamind.features.knowledge_space.api.exceptions import (
        KnowledgeSpaceError as HostKSE,
        EmbeddingError as HostEmbeddingError,
        SearchError as HostSearchError,
    )

    # 中立继承关系
    assert issubclass(EmbeddingError, RagError)
    assert issubclass(SearchError, RagError)
    # 中立异常不继承宿主 BaseAPIError 树（否则引擎包会依赖宿主异常框架）
    assert not issubclass(EmbeddingError, HostKSE)
    assert not issubclass(SearchError, HostKSE)
    # 中立与宿主同名异常是不同类
    assert EmbeddingError is not HostEmbeddingError
    assert SearchError is not HostSearchError
    # 宿主异常码契约保留：宿主 EmbeddingError/SearchError 仍带 code
    assert HostEmbeddingError("x").code == "EMBEDDING_ERROR"
    assert HostSearchError("x").code == "SEARCH_ERROR"


def test_6a2_host_cache_port_satisfies_cache_port_protocol():
    """6a-2：HostCachePort 结构化满足中立 CachePort 协议（runtime_checkable）。"""
    from novamind.engines.rag.cache_port import CachePort
    from novamind.features.knowledge_space.adapters.cache_adapter import HostCachePort

    assert isinstance(HostCachePort(), CachePort)


def test_6a2_retrieval_engine_ctor_accepts_cache_port():
    """6a-2：RetrievalEngine 构造器接收 cache_port 注入；未注入时 _get_cache 返回 None 降级。"""
    import asyncio
    from novamind.engines.rag import RetrievalEngine

    params = inspect.signature(RetrievalEngine.__init__).parameters
    assert "cache_port" in params, "RetrievalEngine.__init__ 应含 cache_port 参数"

    eng = RetrievalEngine(es_client=None)  # cache_port 默认 None
    assert eng._cache_port is None
    assert asyncio.run(eng._get_cache()) is None  # 未注入 → no-op 降级


# ---------- 6a-3：RetrievalPort 去 SearchRequest schema 绑定 ----------

def test_6a3_retrieval_port_has_no_search_schema_import():
    """6a-3：retrieval_port 不得 import ``features.knowledge_space.schemas``（端口不绑宿主 schema）。"""
    p = SRC / "shared" / "retrieval_port.py"
    bad = [m for m in _imports_in(p) if m.startswith("novamind.features.knowledge_space.schemas")]
    assert not bad, f"retrieval_port 残留 schemas import: {bad}"


def test_6a3_retrieval_port_search_request_param_is_opaque():
    """6a-3：RetrievalPort.search 的 ``request`` 参数去类型化为 ``Any``（不绑 SearchRequest）。

    注：docstring 中作为说明文字提及 ``SearchRequest`` 是允许的（解释 host payload 来源），
    接缝不变式只在 AST 层面：无 import + 参数注解为 ``Any``。
    """
    src = (SRC / "shared" / "retrieval_port.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(src)
    search_method = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "search":
            search_method = node
            break
    assert search_method is not None, "RetrievalPort 应定义 async search"
    request_arg = next(a for a in search_method.args.args if a.arg == "request")
    # 注解应为 Name(id="Any")，而非属性/字符串 SearchRequest
    ann = request_arg.annotation
    assert isinstance(ann, ast.Name) and ann.id == "Any", "search(request) 注解应为 Any"


# ---------- 6a-4：skill_checker ReviewStatus 枚举下沉 ----------

def test_6a4_skill_checker_has_no_skill_models_import():
    """6a-4：skill_checker 不得 import ``features.skill.models``（改用中立 features.skill.ports）。"""
    p = SRC / "features" / "skill" / "services" / "skill_checker.py"
    bad = [m for m in _imports_in(p) if m.startswith("novamind.features.skill.models")]
    assert not bad, f"skill_checker 残留 skill.models import: {bad}"


def test_6a4_review_status_identity_between_neutral_and_orm():
    """6a-4：中立 ``features.skill.ports.ReviewStatus`` 与 ORM ``skill.models.skill.ReviewStatus`` 同一对象。"""
    from novamind.features.skill.ports import ReviewStatus as NeutralReviewStatus
    from novamind.features.skill.models.skill import ReviewStatus as ORMReviewStatus

    assert NeutralReviewStatus is ORMReviewStatus, "ReviewStatus 中立枚举与 ORM re-export 必须同一对象"
    # 值逐字对齐（DB 已存数据兼容）
    assert NeutralReviewStatus.PENDING == 0
    assert NeutralReviewStatus.APPROVED == 1
    assert NeutralReviewStatus.SUSPICIOUS == 2
    assert NeutralReviewStatus.REJECTED == 3


# ---------- 6a-5：audio_utils 去 ClientFactory ----------

def test_6a5_audio_utils_has_no_shared_clients_import():
    """6a-5：audio_utils 不得 import ``shared.clients``（minio_client 改构造器/参数注入）。"""
    p = SRC / "features" / "knowledge_space" / "media" / "audio" / "audio_utils.py"
    bad = [
        m
        for m in _imports_in(p)
        if m == "novamind.shared.clients" or m.startswith("novamind.shared.clients.")
    ]
    assert not bad, f"audio_utils 残留 shared.clients import: {bad}"


def test_6a5_audio_utils_minio_client_is_keyword_injected():
    """6a-5：两个函数 ``minio_client`` 为关键字必传（KEYWORD_ONLY）注入。"""
    from novamind.features.knowledge_space.media.audio.audio_utils import (
        upload_parsed_text_to_minio,
        transcribe_audio_with_dashscope,
    )

    for fn in (upload_parsed_text_to_minio, transcribe_audio_with_dashscope):
        params = inspect.signature(fn).parameters
        assert "minio_client" in params, f"{fn.__name__} 应含 minio_client 参数"
        assert (
            params["minio_client"].kind == inspect.Parameter.KEYWORD_ONLY
        ), f"{fn.__name__}.minio_client 应为 KEYWORD_ONLY"


# ---------- 通用：引擎候选零跨 feature import ----------

def test_engine_candidates_have_no_cross_feature_import():
    """通用：引擎候选不得 import **跨** feature ``novamind.features.<Y>``（自身 feature 允许）。"""
    offenders: list[str] = []
    for p in CANDIDATES:
        own = _own_feature(p)
        if own is None:
            continue  # shared/ 候选无 feature 归属，不适用本检查
        for mod in _imports_in(p):
            parts = mod.split(".")
            if len(parts) >= 3 and parts[0] == "novamind" and parts[1] == "features":
                other = parts[2]
                if other != own:
                    offenders.append(f"{p.relative_to(SRC)} (own={own}): {mod}")
    assert not offenders, "引擎候选残留跨 feature import:\n" + "\n".join(offenders)


# ---------- 冒烟：引擎候选清单非空 ----------

def test_candidate_collection_nonempty():
    """冒烟：引擎候选清单非空（守护目录路径漂移致假绿）。"""
    assert len(CANDIDATES) > 30, f"引擎候选清单过少: {len(CANDIDATES)}"