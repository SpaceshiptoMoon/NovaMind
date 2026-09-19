"""Wiki 去重（dedup）与批级目录规划（taxonomy）测试。

移植 WeKnora wiki_ingest_dedup 相关用例：bigram 相似度、floor 0.08 预筛、
top-K 填充、exact-title 确定性归并、跨 item 错配拒绝、类型前缀校验、
批内 identity 收敛；taxonomy 的路径清洗/树渲染/分配解析。
"""
import pytest

from novamind.features.knowledge_space.services.wiki_dedup import (
    DEDUP_CANDIDATE_TOP_K,
    DedupCandidate,
    dedup_pair_score,
    exact_identity_target,
    grams_per_surface,
    merge_extracted_identity,
    merge_reject_reason,
    normalize_identity_title,
    prefer_identity_display_name,
    select_dedup_candidate_pages,
    slug_base_tokens,
    stabilize_extracted_items,
    surface_grams,
)
from novamind.features.knowledge_space.services.wiki_taxonomy import (
    CATEGORY_MAX_DEPTH,
    clean_category_path,
    format_existing_taxonomy,
    parse_taxonomy_assignments,
)


@pytest.mark.unit
class TestSimilarityPrimitives:
    def test_surface_grams_basic(self):
        assert surface_grams("") == set()
        assert surface_grams("a") == {"a"}
        assert surface_grams("abc") == {"ab", "bc"}
        # 大小写与标点剔除
        assert surface_grams("Acme Corp.") == surface_grams("acmecorp")

    def test_surface_grams_cjk(self):
        """CJK bigram 近似词"""
        g = surface_grams("检索增强生成")
        assert "检索" in g and "增强" in g and "生成" in g

    def test_slug_base_tokens(self):
        assert slug_base_tokens("entity/beijing-nongshang-yinxing") == {
            "beijing", "nongshang", "yinxing",
        }
        assert slug_base_tokens("concept/rag") == {"rag"}
        assert slug_base_tokens("") == set()
        assert slug_base_tokens("plain-slug") == {"plain", "slug"}

    def test_exact_title_match_signal(self):
        """Acme Corp vs Acme Corporation bigram 重叠 ≥ floor（WeKnora 调参案例）"""
        score = dedup_pair_score(
            grams_per_surface(["Acme Corporation"]),
            slug_base_tokens("entity/acme-corporation"),
            grams_per_surface(["Acme Corp"]),
            slug_base_tokens("entity/acme-corp"),
        )
        assert score >= 0.08

    def test_zero_signal_pair(self):
        """城镇登记失业人员 vs 中华优秀传统文化 应零信号（WeKnora 幻觉配对案例）"""
        a = surface_grams("城镇登记失业人员")
        b = surface_grams("中华优秀传统文化")
        inter = a & b
        assert len(inter) / max(1, len(a | b)) < 0.08


@pytest.mark.unit
class TestSelectDedupCandidates:
    def _page(self, slug, title, aliases=None, page_type="entity"):
        return DedupCandidate(slug, title, aliases or [], page_type)

    def test_small_corpus_bypass(self):
        """语料 ≤25 跳过预筛全量返回"""
        pages = [self._page(f"entity/p{i}", f"完全无关{i}") for i in range(10)]
        items = [{"name": "新实体", "slug": "entity/new", "aliases": []}]
        assert len(select_dedup_candidate_pages(items, pages)) == 10

    def test_summary_pages_filtered(self):
        pages = [self._page("summary/1", "S", page_type="summary"),
                 self._page("entity/e1", "甲公司")]
        items = [{"name": "甲公司", "slug": "entity/jia", "aliases": []}]
        out = select_dedup_candidate_pages(items, pages)
        assert [p.slug for p in out] == ["entity/e1"]

    def test_top_k_and_floor(self):
        """地板之上无条件入选；零分不入选（>25 页语料绕开 bypass 走真预筛）"""
        pages = [
            self._page("entity/exact", "甲公司"),
            self._page("entity/near", "甲公色"),      # bigram 重叠 ≥ floor
            self._page("entity/weak", "甲国银行"),    # 与"甲公司"零共享 bigram → 零分
            self._page("entity/zero", "全然无关者"),  # 零信号
        ]
        # 30 页无关填充绕开 small-corpus bypass
        pages += [self._page(f"entity/f{i}", f"无关词{i}xyz") for i in range(30)]
        items = [{"name": "甲公司", "slug": "entity/jia", "aliases": []}]
        out = select_dedup_candidate_pages(items, pages)
        slugs = [p.slug for p in out]
        assert "entity/exact" in slugs and "entity/near" in slugs
        # 零分永不入选（毫无共同点只会诱导幻觉配对）
        assert "entity/weak" not in slugs and "entity/zero" not in slugs

    def test_topk_fill_below_floor(self):
        """小语料 bypass 之外，地板下>0 分、top-K 未满时入选；常量对齐 WeKnora"""
        # 30 页无关填充绕开 small-corpus bypass；'abc' 与 'ab' 共享 bigram {ab}，
        # Jaccard=1/2 ≥ floor 稳定入选
        filler = [self._page(f"entity/f{i}", f"无关词{i}xyz") for i in range(30)]
        pages30 = [self._page("entity/p", "abc")] + filler
        items = [{"name": "ab", "slug": "entity/q", "aliases": []}]
        out = select_dedup_candidate_pages(items, pages30)
        assert "entity/p" in [p.slug for p in out]
        assert DEDUP_CANDIDATE_TOP_K == 5

    def test_order_preserved(self):
        """返回保输入顺序（prompt 稳定性）"""
        pages = [self._page("entity/b", "甲公司"), self._page("entity/a", "甲公司")]
        items = [{"name": "甲公司", "slug": "entity/x", "aliases": []}]
        out = select_dedup_candidate_pages(items, pages)
        assert [p.slug for p in out] == ["entity/b", "entity/a"]


@pytest.mark.unit
class TestExactIdentity:
    def test_normalize_identity(self):
        assert normalize_identity_title(" Acme  Corp ") == "acmecorp"
        assert normalize_identity_title("《寓言》") == "《寓言》"  # 标点保留

    def test_exact_target_hit(self):
        pages = {"entity/acme": DedupCandidate("entity/acme", "Acme Corp", [], "entity")}
        target = exact_identity_target("acme corp", "entity", {"entity/acme"}, pages)
        assert target == "entity/acme"

    def test_exact_target_type_mismatch(self):
        """同题不同型不归并"""
        pages = {"concept/acme": DedupCandidate("concept/acme", "Acme", [], "concept")}
        target = exact_identity_target("Acme", "entity", {"concept/acme"}, pages)
        assert target == ""

    def test_exact_target_punctuation_distinguishes(self):
        """标点参与 identity：「寓言」与「《寓言》」不同页"""
        pages = {"concept/yuyan": DedupCandidate("concept/yuyan", "寓言", [], "concept")}
        assert exact_identity_target("《寓言》", "concept", {"concept/yuyan"}, pages) == ""

    def test_exact_target_excludes_self_slug(self):
        pages = {"entity/same": DedupCandidate("entity/same", "同名", [], "entity")}
        assert exact_identity_target("同名", "entity", {"entity/same"}, pages, own_slug="entity/same") == ""


@pytest.mark.unit
class TestMergeValidation:
    def test_reject_cross_item_target(self):
        """目标不在该 item 自己的候选集 → 拒绝（防跨 item 错配）"""
        reason = merge_reject_reason("entity/a", "entity/hiring", {"entity/other"})
        assert reason == "target is not a similarity candidate for this item"

    def test_reject_type_mismatch(self):
        assert merge_reject_reason("entity/a", "concept/b", {"concept/b"}).startswith("type mismatch")

    def test_reject_missing_prefix(self):
        assert merge_reject_reason("bare", "entity/b", {"entity/b"}) == "missing type prefix"
        assert merge_reject_reason("entity/a", "bare2", {"bare2"}) == "missing type prefix"

    def test_allow_valid_merge(self):
        assert merge_reject_reason("entity/acme-corp", "entity/acme", {"entity/acme"}) == ""


@pytest.mark.unit
class TestIdentityMerge:
    def test_prefer_shorter_display(self):
        name, alias = prefer_identity_display_name("孔 子", "孔子")
        assert name == "孔子" and alias == "孔 子"

    def test_merge_preserves_aliases_and_chunks(self):
        dst = {"type": "entity", "name": "Acme", "slug": "entity/acme", "aliases": ["A"],
               "description": "短", "details": "x", "cited_chunk_ids": ["c1"]}
        src = {"type": "entity", "name": "ACME", "slug": "entity/acme", "aliases": ["B"],
               "description": "更长的描述", "details": "yy", "cited_chunk_ids": ["c1", "c2"]}
        merged = merge_extracted_identity(dst, src)
        assert merged["name"] == "Acme"  # 更紧凑
        assert set(merged["aliases"]) == {"A", "B", "ACME"}
        assert merged["description"] == "更长的描述"
        assert merged["cited_chunk_ids"] == ["c1", "c2"]

    def test_stabilize_coalesces_same_identity(self):
        items = [
            {"type": "entity", "name": "Acme Corp", "slug": "entity/acme-a",
             "aliases": [], "description": "a", "details": "", "cited_chunk_ids": ["c1"]},
            {"type": "entity", "name": "acme corp", "slug": "entity/acme-b",
             "aliases": [], "description": "b", "details": "", "cited_chunk_ids": ["c2"]},
        ]
        out = stabilize_extracted_items(items, {}, {})
        assert len(out) == 1
        assert out[0]["cited_chunk_ids"] == ["c1", "c2"]

    def test_stabilize_applies_exact_then_merge(self):
        items = [
            {"type": "entity", "name": "Acme", "slug": "entity/new-acme",
             "aliases": [], "description": "", "details": "", "cited_chunk_ids": []},
            {"type": "entity", "name": "Other", "slug": "entity/other",
             "aliases": [], "description": "", "details": "", "cited_chunk_ids": []},
        ]
        out = stabilize_extracted_items(
            items,
            merge_targets={"entity/other": "entity/existing"},
            exact_targets={"entity/new-acme": "entity/existing"},
        )
        assert len(out) == 1 and out[0]["slug"] == "entity/existing"


@pytest.mark.unit
class TestTaxonomy:
    def test_clean_category_path(self):
        # "科技/公司" 标签内斜杠切分；"科技" 已存在去重；深度 2 截断
        assert clean_category_path(["人物", "人物", "科技/公司"]) == ["人物", "科技"]
        assert clean_category_path(["a", "b", "c"]) == ["a", "b"]  # 深度截断
        assert clean_category_path(["", "  "]) == []
        assert len(clean_category_path(["x", "y", "z"])) <= CATEGORY_MAX_DEPTH

    def test_format_tree_sorted(self):
        tree = format_existing_taxonomy([["节日", "传统节日"], ["人物"], ["节日"]])
        lines = tree.splitlines()
        assert lines[0] == "人物"  # 字典序：人物 < 节日
        assert "  传统节日" in tree

    def test_format_empty(self):
        assert format_existing_taxonomy([]) == ""

    def test_parse_assignments(self):
        parsed = {"assignments": [
            {"slug": "entity/zhang-san", "path": ["人物"]},
            {"slug": "concept/x", "path": ["节日", "传统节日"]},
            {"slug": "", "path": ["无效"]},
            {"slug": "entity/y", "path": "not-a-list"},
        ]}
        out = parse_taxonomy_assignments(parsed)
        assert out == {"entity/zhang-san": ["人物"], "concept/x": ["节日", "传统节日"]}

    def test_parse_assignments_bad_input(self):
        assert parse_taxonomy_assignments(None) == {}
        assert parse_taxonomy_assignments("not json") == {}
