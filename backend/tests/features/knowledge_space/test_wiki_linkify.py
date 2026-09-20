"""Wiki linkify 自动互链测试——用例移植自 WeKnora wiki_linkify_test.go"""
import pytest
from novamind.features.knowledge_space.services.wiki_linkify import (
    compute_forbidden_spans,
    linkify_content,
)

pytestmark = pytest.mark.unit


@pytest.mark.unit
class TestLinkifyBasics:
    def test_basic_injection(self):
        out, changed = linkify_content("关于甲公司的介绍。", [("entity/jia", "甲公司")])
        assert changed
        assert out == "关于[[entity/jia|甲公司]]的介绍。"

    def test_empty_inputs(self):
        out, changed = linkify_content("", [("entity/a", "A")])
        assert out == "" and not changed
        out, changed = linkify_content("正文", [])
        assert not changed

    def test_self_slug_skipped(self):
        out, changed = linkify_content("自己页 [[x|y]] 提及甲公司。", [("entity/self", "甲公司")], self_slug="entity/self")
        assert not changed

    def test_no_match(self):
        out, changed = linkify_content("完全无关内容", [("entity/a", "甲公司")])
        assert not changed

    def test_first_occurrence_only(self):
        """每个 ref 只包首个安全命中"""
        out, changed = linkify_content("甲公司好。甲公司真好。", [("entity/jia", "甲公司")])
        assert out.count("[[entity/jia") == 1
        assert out.startswith("关于") or "[[entity/jia|甲公司]]好" in out


@pytest.mark.unit
class TestLinkifyForbiddenSpans:
    def test_fenced_code_block_protected(self):
        content = "正文提甲公司。\n\n```\n甲公司 in code\n```"
        out, changed = linkify_content(content, [("entity/jia", "甲公司")])
        assert changed
        assert out.count("[[entity/jia") == 1  # 只有正文那处
        assert "```\n甲公司 in code\n```" in out  # 代码块原样

    def test_inline_code_protected(self):
        out, changed = linkify_content("用 `甲公司` 做代号，正文说甲公司。", [("entity/jia", "甲公司")])
        assert changed
        assert "`甲公司`" in out  # 行内码原样
        assert out.count("[[entity/jia") == 1

    def test_existing_wiki_link_protected_and_used(self):
        """已有链接是禁区；其 slug 记入 used → 同 slug ref 直接跳过"""
        out, changed = linkify_content(
            "见 [[entity/jia|甲公司]] 与甲公司。", [("entity/jia", "甲公司")],
        )
        assert not changed  # slug 已被链接，ref 跳过

    def test_markdown_link_protected(self):
        out, changed = linkify_content(
            "看 [甲公司官网](https://a.com)，正文说甲公司。", [("entity/jia", "甲公司")],
        )
        assert changed
        assert "[甲公司官网](https://a.com)" in out  # md 链接原样
        assert out.count("[[entity/jia") == 1

    def test_image_protected(self):
        out, changed = linkify_content(
            "![甲公司](https://a.com/i.png) 里说甲公司。", [("entity/jia", "甲公司")],
        )
        assert "![甲公司](https://a.com/i.png)" in out

    def test_reference_definition_protected(self):
        content = "[甲公司]: https://a.com\n\n正文说甲公司。"
        out, changed = linkify_content(content, [("entity/jia", "甲公司")])
        assert out.startswith("[甲公司]: https://a.com")
        assert out.count("[[entity/jia") == 1

    def test_autolink_protected(self):
        out, changed = linkify_content(
            "访问 <https://jia.com> 了解甲公司。", [("entity/jia", "甲公司")],
        )
        assert changed
        assert "<https://jia.com>" in out
        assert out.count("[[entity/jia") == 1

    def test_no_nesting_in_replaced_link(self):
        """连续命中时后续 ref 不嵌进新造的 [[...]]"""
        out, _ = linkify_content("甲公司甲公司", [("entity/jia", "甲公司")])
        # 第二个"甲公司"不是 ref（同 slug 已用）；且第一个替换后不产生嵌套
        assert out == "[[entity/jia|甲公司]]甲公司"


@pytest.mark.unit
class TestLinkifyMatching:
    def test_longest_match_wins(self):
        """长名优先：北京邮电大学 优先于 北京"""
        out, _ = linkify_content(
            "介绍北京邮电大学的历史。",
            [("entity/bj", "北京"), ("entity/bupt", "北京邮电大学")],
        )
        assert "[[entity/bupt|北京邮电大学]]" in out
        assert "[[entity/bj" not in out

    def test_cjk_embedded_match_allowed(self):
        """CJK 视为边界：短名可嵌入长词命中（但长名优先先消费）"""
        out, _ = linkify_content(
            "北京的高校很多。",
            [("entity/bupt", "北京邮电大学"), ("entity/bj", "北京")],
        )
        assert "[[entity/bj|北京]]" in out  # 无长名匹配 → 北京正常链接

    def test_ascii_word_boundary(self):
        """ASCII 词边界：RAG 不匹配 RAGs 中的子串…… 实际 RAGs 边界合规；
        XRAG 中 X 紧邻则拒绝"""
        out, changed = linkify_content("讲讲 XRAG 架构。", [("concept/rag", "RAG")])
        assert not changed  # RAG 前面是 X（word rune）→ 边界不合法
        out, changed = linkify_content("讲讲 RAG 架构。", [("concept/rag", "RAG")])
        assert changed

    def test_cjk_pure_no_boundary_needed(self):
        """纯 CJK matchText 无边界要求"""
        out, changed = linkify_content("甲公司", [("entity/jia", "甲公司")])
        assert changed

    def test_used_slug_from_wiki_link_skips(self):
        out, _ = linkify_content(
            "A 页 [[entity/other|其他]]；甲公司很好。",
            [("entity/jia", "甲公司"), ("entity/other", "其他")],
        )
        # entity/other 已用 → 不再注入；甲公司正常注入
        assert out.count("[[entity/other") == 1
        assert "[[entity/jia|甲公司]]" in out


@pytest.mark.unit
class TestComputeForbiddenSpans:
    def test_used_slugs_collected(self):
        spans, used = compute_forbidden_spans("开头 [[entity/a|A]] 结束 [[concept/b]]")
        assert used == {"entity/a": True, "concept/b": True}

    def test_code_fence_span(self):
        spans, used = compute_forbidden_spans("x\n```\ncode\n```\ny")
        assert any(sp.start <= 2 and sp.end >= len("x\n```\ncode\n```") - 1 for sp in spans)
        assert used == {}
