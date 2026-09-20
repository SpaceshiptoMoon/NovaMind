"""Wiki 批级目录规划（taxonomy）——移植自 WeKnora wiki_ingest_taxonomy.go

对整批 entity/concept 用**一次 LLM 调用**（60 条/批，feed-forward 收敛）
分配 ≤2 级 category_path，整批落在同一棵目录树上并复用已有目录。取代
逐页并行发明 category 的做法——后者无法收敛（尤其 KB 首批无目录锚点时）。

只对尚无 category 的页面生效（reduce 应用时跳过已有目录的页面），用户
手工摆放不被覆盖。

简化（有意，标注于代码）：WeKnora 在文件夹池 >60 时用 embedding 余弦
相似度筛相关子集；NovaMind 目录规模小，直接 cap 截断。
"""
from collections.abc import Sequence
from typing import Any

from novamind.core.middleware.structured_logging import get_logger
from novamind.shared.prompts.prompt_manager import PromptManager

logger = get_logger(__name__)

# 单次规划调用的条目上限（feed-forward 分块）
TAXONOMY_PLAN_CHUNK_SIZE = 60
# 喂给 prompt 的已有目录路径池上限（超过截断——embedding 预筛的简化替代）
TAXONOMY_FOLDER_POOL_MAX = 150
# 空目录提示（对齐 WeKnora wikiTaxonomyEmptyTreeHint）
TAXONOMY_EMPTY_TREE_HINT = "（暂无目录——本知识库还没有分类，请设计一棵新目录树）"
# category_path 最大深度（对齐 types.WikiCategoryMaxDepth）
CATEGORY_MAX_DEPTH = 2


def clean_category_path(parts: Sequence[str]) -> list[str]:
    """清洗路径标签：去空白、去重、保序、截断到最大深度。"""
    cleaned: list[str] = []
    for part in parts or []:
        label = (part or "").strip()
        if not label or label in cleaned:
            continue
        if "/" in label:  # 单个标签内不允许斜杠
            for sub in label.split("/"):
                sub = sub.strip()
                if sub and sub not in cleaned:
                    cleaned.append(sub)
        else:
            cleaned.append(label)
        if len(cleaned) >= CATEGORY_MAX_DEPTH:
            return cleaned[:CATEGORY_MAX_DEPTH]
    return cleaned


def format_existing_taxonomy(paths: list[list[str]]) -> str:
    """distinct category_path 渲染为缩进目录树（供 prompt 复用）。

    ["节日","传统节日"] →
      节日
        传统节日
    同级按字典序稳定排序。
    """
    if not paths:
        return ""
    root: dict[str, Any] = {}
    for path in paths:
        node = root
        for label in path:
            if not label:
                continue
            node = node.setdefault(label, {})
    if not root:
        return ""
    lines: list[str] = []

    def _walk(node: dict[str, Any], depth: int) -> None:
        for label in sorted(node.keys()):
            lines.append(f"{'  ' * depth}{label}")
            _walk(node[label], depth + 1)

    _walk(root, 0)
    return "\n".join(lines).strip()


def parse_taxonomy_assignments(parsed: Any) -> dict[str, list[str]]:
    """解析 LLM 输出 {"assignments": [{slug, path[]}]} → {slug: path}

    parsed 为 _call_llm_json 已解析的 dict（或原始字符串——容错二次解析）。
    """
    if not parsed:
        return {}
    if isinstance(parsed, str):
        from novamind.shared.utils.llm_response import extract_json_obj
        parsed = extract_json_obj(parsed)
        if not isinstance(parsed, dict):
            return {}
    out: dict[str, list[str]] = {}
    for a in parsed.get("assignments") or []:
        if not isinstance(a, dict):
            continue
        slug = (a.get("slug") or "").strip()
        path = a.get("path")
        if slug and isinstance(path, list):
            out[slug] = clean_category_path([str(p) for p in path])
    return out


async def plan_batch_taxonomy(
    items: list[dict],
    existing_paths: list[list[str]],
    language: str,
    call_llm_json,
) -> dict[str, list[str]]:
    """批级目录规划：一次调用（分块 feed-forward）为整批分配 category_path。

    Args:
        items: [{slug, title(name), page_type, about(description)}]，仅
            entity/concept（调用方过滤）。
        existing_paths: KB 内 distinct category_path 池（调用方截断到
            TAXONOMY_FOLDER_POOL_MAX）。
        call_llm_json: 管道的 _call_llm_json（信号量约束在管道侧统一）。

    Returns:
        {slug: category_path}；规划失败返回 {}（目录缺失不阻断页面生成）。
    """
    if not items:
        return {}

    # 已有目录锚点池（cap 截断——embedding 相关性预筛的简化替代，NovaMind
    # 目录规模小、截断足够）
    existing = [list(p) for p in (existing_paths or [])][:TAXONOMY_FOLDER_POOL_MAX]

    result: dict[str, list[str]] = {}
    for start in range(0, len(items), TAXONOMY_PLAN_CHUNK_SIZE):
        chunk = items[start:start + TAXONOMY_PLAN_CHUNK_SIZE]

        tree = format_existing_taxonomy(existing) or TAXONOMY_EMPTY_TREE_HINT
        items_block = "\n".join(
            f"- slug: {it['slug']} | title: {it.get('title') or it['slug']} | "
            f"type: {it.get('page_type')} | about: {(it.get('about') or '')[:120]}"
            for it in chunk
        )
        prompt = PromptManager.format_prompt(
            "wiki_taxonomy_plan_user",
            existing_taxonomy=tree,
            items=items_block,
            language=language,
        )
        raw = await call_llm_json(prompt)
        if not raw:
            logger.warning("wiki taxonomy 规划调用失败，本块跳过", items=len(chunk))
            continue
        for slug, path in parse_taxonomy_assignments(raw).items():
            result[slug] = path
            if path:
                # feed-forward：后面的块复用前面新造的目录，保持整批同树
                existing = append_unique_tree(existing, path)
    return result


def append_unique_tree(existing: list[list[str]], path: list[str]) -> list[list[str]]:
    """把新路径加入目录池（去重）——feed-forward 用"""
    if path and path not in existing:
        existing.append(list(path))
    return existing
