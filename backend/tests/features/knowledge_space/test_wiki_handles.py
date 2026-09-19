"""HandleTable（wiki 管道句柄表）单元测试。

对齐 WeKnora modelcontext.HandleTable：chunk 句柄（c000/c001）与 slug 句柄
（ref-1/ref-2）的双向映射、复用、未知名柄处理、正文 decode。
"""
import pytest

from novamind.features.knowledge_space.services.wiki_handles import HandleTable


@pytest.mark.unit
class TestHandleTable:
    def test_register_sequential(self):
        """同前缀按序分配：c000, c001, c002…"""
        h = HandleTable(prefix="c", start=0, width=3)
        assert h.register("uuid-a") == "c000"
        assert h.register("uuid-b") == "c001"
        assert h.register("uuid-c") == "c002"

    def test_register_reuse_same_real(self):
        """同一真实 ID 重复注册复用同一句柄"""
        h = HandleTable(prefix="ref-", start=1, width=1)
        first = h.register("entity/a")
        again = h.register("entity/a")
        assert first == again == "ref-1"

    def test_slug_handles_start_at_one(self):
        """slug 句柄从 ref-1 起（对齐 WeKnora ref- 编号约定）"""
        h = HandleTable(prefix="ref-", start=1, width=1)
        assert h.register("entity/x") == "ref-1"
        assert h.register("concept/y") == "ref-2"

    def test_resolve_roundtrip(self):
        """resolve 是 register 的逆运算"""
        h = HandleTable(prefix="c", start=0, width=3)
        handle = h.register("chunk-uuid-1")
        assert h.resolve(handle) == "chunk-uuid-1"

    def test_resolve_unknown_returns_none(self):
        """未知/空句柄返回 None（调用方丢弃，不投毒）"""
        h = HandleTable(prefix="c", start=0, width=3)
        h.register("chunk-1")
        assert h.resolve("c999") is None
        assert h.resolve("") is None
        assert h.resolve(None) is None

    def test_resolve_strips_whitespace(self):
        """模型输出偶带首尾空白，resolve 容忍"""
        h = HandleTable(prefix="c", start=0, width=3)
        handle = h.register("chunk-1")
        assert h.resolve(f" {handle} ") == "chunk-1"

    def test_decode_text_wiki_links(self):
        """wiki 链接句柄还原：[[ref-N|显示名]] → [[real|显示名]]"""
        h = HandleTable(prefix="ref-", start=1, width=1)
        h.register("entity/a")
        h.register("concept/b")
        out = h.decode_text(
            "见 [[ref-1|A]] 与 [[ref-2|B]]。",
            r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]",
        )
        assert out == "见 [[entity/a|A]] 与 [[concept/b|B]]。"

    def test_decode_text_unknown_handle_preserved(self):
        """未映射句柄原样保留——交给白名单校验当死链剔除"""
        h = HandleTable(prefix="ref-", start=1, width=1)
        h.register("entity/a")
        text = "有效 [[ref-1|A]]，幻觉 [[ref-7|X]]。"
        out = h.decode_text(text, r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
        assert out == "有效 [[entity/a|A]]，幻觉 [[ref-7|X]]。"

    def test_decode_text_no_links_noop(self):
        """无链接文本原样返回"""
        h = HandleTable(prefix="ref-", start=1, width=1)
        h.register("entity/a")
        text = "纯文本，没有链接。"
        assert h.decode_text(text, r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]") == text

    def test_decode_text_empty(self):
        h = HandleTable(prefix="ref-", start=1, width=1)
        assert h.decode_text("", r"\[\[") == ""

    def test_cite_handle_format(self):
        """引文句柄 c000 三位零填充（对齐 WeKnora chunk handle 约定）"""
        h = HandleTable(prefix="c", start=0, width=3)
        handles = [h.register(f"chunk-{i}") for i in range(12)]
        assert handles[0] == "c000"
        assert handles[9] == "c009"
        assert handles[10] == "c010"
        assert h.resolve("c010") == "chunk-10"
