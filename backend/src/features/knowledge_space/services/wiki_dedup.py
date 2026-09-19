"""Wiki 候选去重（dedup）——移植自 WeKnora wiki_ingest_dedup.go

目标：新抽取的实体/概念若与 KB 内已有页面指同一现实事物，归并到已有页
而非新建第二页。三层机制：

1. **相似度预筛**（select_dedup_candidate_pages）：char-bigram Jaccard 与
   slug kebab-token Jaccard 取 max，快速缩小 LLM 候选集。MySQL 无 pg_trgm，
   纯 Python 计算（单 KB 页面量级 + 单文档 ingest 持锁串行，可承受）。
   语料超过 HARD_LIMIT 时退化为仅 exact-title 归并（保守不误并）。
2. **exact-title 确定性归并**（exact_identity_target）：同类型+归一化标题
   完全一致直接绑到已有页，免 LLM。
3. **LLM 语义判断**（dedup prompt，逐 item 候选分组）+ 双守卫
   （merge_reject_reason）：目标必须在**该条目自己的**候选集内 + 类型前缀
   一致——防弱模型跨 item 错配（WeKnora 观测案例：entity/tencent-open →
   entity/hiring-agent，无任何相似信号却被配对）。

与 WeKnora 的分歧（有意）：WeKnora 用 Redis claim 让跨批并发 worker 收敛
到同一 slug；NovaMind 的 ingest 有 per-KB Redis 锁串行化（同一时刻只有
一个文档在生成），批内 dict 足够，不移植 Redis claim。
"""
import re
from typing import Dict, Iterable, List, Sequence, Set, Tuple

# 每个 item 的候选上限（相似度预筛 top-K）
DEDUP_CANDIDATE_TOP_K = 5
# 相似度地板：达到即无条件入选候选（无论 top-K 是否用满）
DEDUP_CANDIDATE_SCORE_FLOOR = 0.08
# 语料规模地板：不超过此数跳过预筛全量进 prompt（预筛只在大 KB 有收益，
# 小语料全量喂反而召回最好）
DEDUP_SMALL_CORPUS_BYPASS = 25
# 语料规模硬顶：超过则跳过 LLM dedup 全流程（只做 exact-title），防 O(P×N)
# 卡死任务。MySQL 无 trigram 索引下的保守兜底。
DEDUP_CORPUS_HARD_LIMIT = 5000

_SLUG_BASE_SPLIT = re.compile(r"[-_.\s]+")


def jaccard(a: Set[str], b: Set[str]) -> float:
    """集合 Jaccard 相似度（移植 WeKnora searchutil.Jaccard）"""
    if not a and not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    inter = sum(1 for x in a if x in b)
    union = len(a) + len(b) - inter
    if union == 0:
        return 0.0
    return inter / union


def surface_grams(s: str) -> Set[str]:
    """char-bigram 集合：小写、剔除非字母数字后按字符二元组切分。

    CJK 下 bigram 近似词；Latin 下捕捉词干重叠（corporation ↔ corp）。
    单字符退 1-gram 保留信号。str.isalnum 覆盖 Go 版
    unicode.IsLetter/IsDigit 语义（含 CJK）。
    """
    if not s:
        return set()
    cleaned = "".join(ch for ch in s.lower() if ch.isalnum())
    if not cleaned:
        return set()
    if len(cleaned) == 1:
        return {cleaned}
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def slug_base_tokens(slug: str) -> Set[str]:
    """slug 基段（"/" 后）kebab token 集合。

    "entity/beijing-nongshang-yinxing" → {"beijing","nongshang","yinxing"}。
    中文页面的拼音 slug 与 surface 名称是正交信号空间。
    """
    if not slug:
        return set()
    base = slug.split("/", 1)[1] if "/" in slug else slug
    return {t for t in _SLUG_BASE_SPLIT.split(base.lower()) if t}


def grams_per_surface(surfaces: Iterable[str]) -> List[Set[str]]:
    return [g for g in (surface_grams(s) for s in surfaces) if g]


def dedup_pair_score(
    a_grams: List[Set[str]], a_tokens: Set[str],
    b_grams: List[Set[str]], b_tokens: Set[str],
) -> float:
    """pair 相似度 = slug token Jaccard 与各 surface 对 Jaccard 的 max。

    slug 与 name 信号空间不同（拼音 vs 原文），取 max 而非均值。
    """
    best = jaccard(a_tokens, b_tokens)
    for ag in a_grams:
        for bg in b_grams:
            v = jaccard(ag, bg)
            if v > best:
                best = v
    return best


class DedupCandidate:
    """已有页面的轻量投影（不拉 content）"""

    __slots__ = ("slug", "title", "aliases", "page_type")

    def __init__(self, slug: str, title: str, aliases: List[str], page_type: str):
        self.slug = slug
        self.title = title
        self.aliases = aliases or []
        self.page_type = page_type


def select_dedup_candidate_pages(
    new_items: Sequence[dict],
    all_pages: Sequence[DedupCandidate],
) -> List[DedupCandidate]:
    """预筛：返回与至少一个新条目可能相关的页面子集（保持输入顺序）。

    new_items 元素需含 name/slug/aliases。非 entity/concept 页无条件剔除；
    小语料跳过预筛（只做类型过滤）；返回结果保序使 prompt 稳定。
    """
    pages = [p for p in all_pages if p.page_type in ("entity", "concept")]
    if not pages:
        return []
    if not new_items or len(pages) <= DEDUP_SMALL_CORPUS_BYPASS:
        return pages

    page_feats = []
    for p in pages:
        surfaces = [p.title, *p.aliases]
        page_feats.append((slug_base_tokens(p.slug), grams_per_surface(surfaces)))

    selected: Dict[int, bool] = {}
    for it in new_items:
        name = it.get("name") or ""
        aliases = it.get("aliases") or []
        a_tokens = slug_base_tokens(it.get("slug") or "")
        a_grams = grams_per_surface([name, *aliases])
        if not a_tokens and not a_grams:
            continue

        scored = sorted(
            ((dedup_pair_score(a_grams, a_tokens, pt, pk), i) for i, (pk, pt) in enumerate(page_feats)),
            key=lambda x: -x[0],
        )
        topk_left = DEDUP_CANDIDATE_TOP_K
        for score, idx in scored:
            if score >= DEDUP_CANDIDATE_SCORE_FLOOR:
                selected[idx] = True
                continue
            # 地板之下但 top-K 预算未用满：填入最高分剩余页供 LLM「明确拒绝」，
            # 零分除外（毫无共同点只会诱导幻觉配对）
            if topk_left > 0 and score > 0:
                selected[idx] = True
                topk_left -= 1
                continue
            break

    return [p for i, p in enumerate(pages) if selected.get(i)]


def normalize_identity_title(title: str) -> str:
    """保守 identity key：去空白+小写，保留标点。

    "寓言" 与 "《寓言》" 须可区分（概念 vs 作品）；只消除模型格式漂移
    （"Acme Corp" vs "acme  corp"）。
    """
    return "".join(ch for ch in (title or "").strip() if not ch.isspace()).lower()


def exact_identity_target(
    item_name: str,
    item_type: str,
    candidate_slugs: Set[str],
    pages_by_slug: Dict[str, DedupCandidate],
    own_slug: str = "",
) -> str:
    """同类型候选中归一化标题完全一致者 → 确定性归并目标（空串=无）。

    LLM 仍负责语义/别名匹配；此快速路径只覆盖「同类型页面不应有两页同
    可见标题」这一无歧义恒等约束。
    """
    identity = normalize_identity_title(item_name)
    if not identity:
        return ""
    matches = [
        slug for slug in candidate_slugs
        if (p := pages_by_slug.get(slug)) is not None
        and p.page_type == item_type
        and normalize_identity_title(p.title) == identity
        and slug != own_slug
    ]
    return sorted(matches)[0] if matches else ""


def merge_reject_reason(src_slug: str, dst_slug: str, src_candidates: Set[str]) -> str:
    """校验 LLM 提议的合并（src→dst），允许返回空串、拒绝返回原因。

    双守卫：目标必须在 src 自己的候选集内 + 类型前缀一致。
    """
    if dst_slug not in src_candidates:
        return "target is not a similarity candidate for this item"
    src_slash = src_slug.find("/")
    dst_slash = dst_slug.find("/")
    if src_slash <= 0 or dst_slash <= 0:
        return "missing type prefix"
    if src_slug[:src_slash + 1] != dst_slug[:dst_slash + 1]:
        return f"type mismatch: {src_slug[:src_slash + 1]} vs {dst_slug[:dst_slash + 1]}"
    return ""


def append_unique(values: List[str], value: str) -> List[str]:
    value = (value or "").strip()
    if value and value not in values:
        values.append(value)
    return values


def prefer_identity_display_name(dst: str, src: str) -> Tuple[str, str]:
    """同 identity 两个显示名取更紧凑者，落选者作为别名返回。

    "孔子" 优于 "孔 子"；落选形式记为 alias 不丢信号。
    """
    if not dst:
        return src, ""
    if not src or src == dst:
        return dst, ""
    if normalize_identity_title(dst) == normalize_identity_title(src):
        if len(src) < len(dst):
            return src, dst
        return dst, src
    return dst, src


def merge_extracted_identity(dst: dict, src: dict) -> dict:
    """批内同 slug 收敛：保所有别名/chunk 引用、留更丰富的描述文本。

    dst/src 为 ExtractedItem 的 dict 形态（type/name/slug/aliases/
    description/details/cited_chunk_ids）。
    """
    name, extra_alias = prefer_identity_display_name(dst.get("name") or "", src.get("name") or "")
    dst["name"] = name
    if extra_alias:
        dst["aliases"] = append_unique(dst.get("aliases") or [], extra_alias)
    for alias in src.get("aliases") or []:
        dst["aliases"] = append_unique(dst.get("aliases") or [], alias)
    if len(src.get("description") or "") > len(dst.get("description") or ""):
        dst["description"] = src["description"]
    if len(src.get("details") or "") > len(dst.get("details") or ""):
        dst["details"] = src["details"]
    merged_chunks = dst.get("cited_chunk_ids") or []
    for cid in src.get("cited_chunk_ids") or []:
        if cid not in merged_chunks:
            merged_chunks.append(cid)
    dst["cited_chunk_ids"] = merged_chunks
    return dst


def stabilize_extracted_items(
    items: List[dict],
    merge_targets: Dict[str, str],
    exact_targets: Dict[str, str],
) -> List[dict]:
    """确定性归并结果应用 + 批内 identity 收敛 + 同结果合并。

    - exact_targets（同型同题，权威）与 merge_targets（LLM 语义，非权威）
      把 item.slug 重定向到已有页 slug；
    - 重定向后同 slug 的多个 item 折叠为一个（保证据合并）；
    - 未重定向的条目按批内 (type, identity) 收敛到首个 slug（NovaMind 有
      per-KB 锁，批内 dict 即可，无需 WeKnora 的跨批 Redis claim）。
    """
    out: List[dict] = []
    by_slug: Dict[str, int] = {}
    claimed_by_identity: Dict[str, str] = {}
    for item in items:
        original_slug = item.get("slug") or ""
        authoritative = False
        target = exact_targets.get(original_slug) or ""
        if target:
            item["slug"] = target
            authoritative = True
        else:
            target = merge_targets.get(original_slug) or ""
            if target:
                item["slug"] = target

        identity = normalize_identity_title(item.get("name") or "")
        if not authoritative:
            claimed = claimed_by_identity.get(identity)
            if claimed:
                item["slug"] = claimed
            elif identity:
                claimed_by_identity[identity] = item["slug"]
        elif identity:
            claimed_by_identity[identity] = item["slug"]

        idx = by_slug.get(item["slug"])
        if idx is not None:
            out[idx] = merge_extracted_identity(out[idx], item)
            continue
        by_slug[item["slug"]] = len(out)
        out.append(item)
    return out
