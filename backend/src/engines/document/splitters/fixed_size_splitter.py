"""固定大小切分器：按字符数 / 重叠量切分。"""

from novamind.engines.document.splitters.base_splitter import BaseSplitter


class FixedSizeSplitter(BaseSplitter):
    """固定大小切分器，按固定大小切分文本，不考虑语义边界"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 0):
        """初始化固定大小切分器。

        Args:
            chunk_size: 单块最大字符数（硬上限）。
            chunk_overlap: 相邻块重叠字符数，须小于 chunk_size 否则退化为无重叠。
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """按固定字符数切分文档列表，不做语义边界判断。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表，doc_id 按 ``{原doc_id}_fixed_chunk_{序号}`` 编号。
        """
        split_docs = []

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'unknown')

            chunks = self._split_text_fixed_size(text)

            for i, chunk in enumerate(chunks):
                split_docs.append({
                    'text': chunk.strip(),  # 移除首尾空白
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_fixed_chunk_{i}",
                    'type': doc_type
                })

        return split_docs

    def _split_text_fixed_size(self, text: str) -> list[str]:
        """按固定步长滑动窗口切分单篇文本，窗口步长为 chunk_size - chunk_overlap。"""
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start_idx = 0

        while start_idx < len(text):
            # 计算结束位置
            end_idx = start_idx + self.chunk_size
            
            # 如果到达文本末尾，调整结束位置
            if end_idx > len(text):
                end_idx = len(text)
            
            # 提取文本块
            chunk = text[start_idx:end_idx]
            chunks.append(chunk)
            
            # 更新起始位置，考虑重叠
            start_idx = end_idx - self.chunk_overlap
            
            # 确保不会无限循环（当重叠大于或等于块大小时）
            if self.chunk_overlap >= self.chunk_size:
                start_idx = end_idx

        return chunks