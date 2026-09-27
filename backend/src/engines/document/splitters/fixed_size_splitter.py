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
        """按固定步长滑动窗口切分单篇文本，窗口步长为 chunk_size - chunk_overlap。

        chunk_overlap 为 0 退化为等宽切块；overlap > 0 时相邻块共享尾部内容。
        末块不足 chunk_size 时整块输出并终止——末块绝不与 overlap 组合回退起点，
        否则 start 永远停在 len(text) - overlap 处死循环（overlap > 0 必触发，
        滑动窗口把内存吃爆）。
        """
        if self.chunk_size <= 0:
            # 非法配置（0/负数）不挂死：整篇单块返回。chunk_size<=0 时窗口
            # 不前进，与 overlap 死循环同根。
            return [text] if text else []
        overlap = self.chunk_overlap if self.chunk_overlap < self.chunk_size else 0
        if len(text) <= self.chunk_size:
            return [text]

        chunks = []
        start_idx = 0

        while start_idx < len(text):
            # 计算结束位置
            end_idx = start_idx + self.chunk_size

            # 到达文本末尾：剩余不足一块，整块输出后终止（不计 overlap）
            if end_idx >= len(text):
                chunks.append(text[start_idx:])
                break

            # 提取文本块
            chunks.append(text[start_idx:end_idx])

            # 更新起始位置，考虑重叠（局部变量，不改写调用方可见的实例配置）
            start_idx = end_idx - overlap

        return chunks