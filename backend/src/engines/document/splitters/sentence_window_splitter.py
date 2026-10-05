"""句子窗口切分器：每句一个检索单元，检索期按 chunk_index±window 扩窗拼上下文。"""
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.sentence_segment import split_sentences


class SentenceWindowSplitter(BaseSplitter):
    """句子窗口切分器，按句切分并携带窗口参数元数据。

    与 recursive 等聚拢式切分的本质区别：检索单元是单句（embedding 精度高），
    上下文完整性由检索期扩窗补偿（拿 chunk_index±window 的邻居句拼接）。
    因此本切分器只负责产出句序列 + 在每条 chunk 的 meta 里写窗口参数
    （expansion_type/expansion_window_size），供 build_es_chunks 白名单拾取。
    短句不合并——合并会破坏「每句一单元」的纯窗口语义；块数=句数的 embedding
    成本是该策略的已知代价（KB 配置页文案提示）。
    """

    def __init__(self, window_size: int = 2, max_sentence_length: int = 1000):
        """初始化句子窗口切分器。

        Args:
            window_size: 检索期每侧扩展句数（0 = 不扩窗）；仅作为元数据随
                chunk 落库，切分本身不消费该值——窗口是检索期行为，写入
                chunk 自描述元数据而非依赖 KB 配置回查（配置可能已改，与
                已索引结构失配）。
            max_sentence_length: 单句硬切上限（字符数）。
        """
        super().__init__()
        self.window_size = window_size
        self.max_sentence_length = max_sentence_length

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """按句切分文档列表，每条 chunk 携带窗口参数元数据。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表，每项额外携带 meta 键：
            ``{"expansion_type": "sentence_window", "expansion_window_size": w}``。
        """
        split_docs = []

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'unknown')

            sentences = split_sentences(text, self.max_sentence_length)

            for i, sentence in enumerate(sentences):
                split_docs.append({
                    'text': sentence,
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_sw_chunk_{i}",
                    'type': doc_type,
                    'meta': {
                        'expansion_type': 'sentence_window',
                        'expansion_window_size': self.window_size,
                    },
                })

        return split_docs
