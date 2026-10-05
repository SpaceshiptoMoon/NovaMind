"""父子分块切分器：子块小粒度入库参与召回，父块大上下文检索期回带。"""
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter


class ParentChildSplitter(BaseSplitter):
    """父子分块切分器，两级切分并携带父子关系元数据。

    两级语义：
    - 父块：大上下文容器（parent_chunk_size），只作检索期回带内容、不参与
      召回（检索侧 must_not chunk_role=parent），因此父块间 overlap 固定 0——
      父间重叠会让同一内容出现在两个父块的子块里，embedding 翻倍且回带歧义。
    - 子块：在父块内部按 recursive 语义切分（chunk_size/chunk_overlap），
      overlap 仅在父块内生效，子块绝不跨父块边界。

    输出交错排列 [父0, 子0_0, ..., 父1, 子1_0, ...]，chunk_index 升序即阅读序。
    父块绝对指针（parent_chunk_id）不在切分期生成——最终 chunk_id 由
    build_es_chunks 的 enumerate 决定，切分期只带相对槽位 parent_slot，
    由管道两遍式解析为绝对 id。
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100,
                 parent_chunk_size: int = 2000):
        """初始化父子分块切分器。

        Args:
            chunk_size: 子块最大字符数（embedding/召回单位）。
            chunk_overlap: 子块间重叠字符数，仅在父块内部生效。
            parent_chunk_size: 父块最大字符数（回带上下文单位），须 >= chunk_size。

        Raises:
            ValueError: parent_chunk_size 小于 chunk_size 时（配置矛盾——父块
                必须能装下至少一个完整子块）。
        """
        super().__init__()
        if parent_chunk_size < chunk_size:
            raise ValueError(
                f"parent_chunk_size ({parent_chunk_size}) 必须大于等于 chunk_size ({chunk_size})"
            )
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.parent_chunk_size = parent_chunk_size

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """两级切分文档列表，父块与子块交错输出并携带关系元数据。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表。父块 meta 为
            ``{"chunk_role": "parent", "parent_slot": k}``；子块 meta 为
            ``{"chunk_role": "child", "parent_slot": k}``（k 为父块在文档内
            0 基序数，供 build_es_chunks 两遍式解析绝对指针）。
        """
        split_docs = []

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'unknown')

            # 父块边界：递归切分（段落→句子→词层级），overlap=0、禁用合并
            #（min_chunk_size=0——顶层合并会把相邻父块的子块搅在一起，且
            # merge_small_chunks 的重编号会打断 parent_slot 指针）。
            parent_splitter = RecursiveCharacterSplitter(
                chunk_size=self.parent_chunk_size,
                chunk_overlap=0,
                min_chunk_size=0,
            )
            parent_texts = await parent_splitter._split_text(text)
            # BaseSplitter 契约：纯空白输入产出零 chunk（与 recursive 顶层
            # 过滤、delimiter 的 strip 过滤同语义），不产出「空白父块+空白子块」。
            parent_texts = [pt for pt in parent_texts if pt.strip()]

            # 子块切分：每个父块独立实例化，overlap 不跨父块边界
            child_splitter = RecursiveCharacterSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                min_chunk_size=0,
            )

            for slot, parent_text in enumerate(parent_texts):
                split_docs.append({
                    'text': parent_text,
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_pc_chunk_p{slot}",
                    'type': doc_type,
                    'meta': {'chunk_role': 'parent', 'parent_slot': slot},
                })
                child_texts = await child_splitter._split_text(parent_text)
                child_texts = [ct for ct in child_texts if ct.strip()]
                for j, child_text in enumerate(child_texts):
                    split_docs.append({
                        'text': child_text,
                        'source': source,
                        'page': original_page,
                        'doc_id': f"{original_doc_id}_pc_chunk_p{slot}c{j}",
                        'type': doc_type,
                        'meta': {'chunk_role': 'child', 'parent_slot': slot},
                    })

        return split_docs
