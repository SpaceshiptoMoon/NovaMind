"""递归切分器：按分隔符优先级分层（段落→句子→词），同级片段贪心聚拢后兜底固定大小。"""
import re

from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.chunk_merge import merge_small_chunks


class RecursiveCharacterSplitter(BaseSplitter):
    """递归字符切分器，按不同级别的分隔符切分文本"""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100,
                 separators: list[str] | None = None, min_chunk_size: int = 500):
        """初始化切分器。

        Args:
            chunk_size: 单块最大字符数（硬上限）。
            chunk_overlap: 相邻块之间的重叠字符数，缓解切分边界处上下文断裂。
                注意：仅在最末级硬切（无分隔符可用）时生效，走分隔符切出的
                块之间零重叠——与 LangChain 的 overlap 语义不同。
            separators: 分隔符列表，按优先级从粗到细排序；缺省为中文标点优先的
                通用序列。带尾随空格的英文句读（``'. '`` 等）排在裸符号之前，
                避免小数点/缩写被误切。
            min_chunk_size: 最小块大小阈值，小于此值的碎块与相邻块合并；
                0 表示禁用合并。上限自动夹取到 ``chunk_size // 2``，防止
                min > max 的配置矛盾导致合并条件永不满足。
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # min_chunk_size 只用于事后合并的触发阈值，超过 chunk_size 的一半就失去
        # 意义（合并结果几乎必然超限而跳过）；夹取而非抛错，容忍存量配置漂移。
        self.min_chunk_size = min(min_chunk_size, chunk_size // 2)

        if separators is None:
            # 中文句末标点 → 英文句读（带空格）→ 裸符号 → 逗号（中文在前）→
            # 换行 → 空格 → 空串。换行排在逗号之后：对列表/表格类文本，
            # 行是比行内标点更强的语义边界，先按行断保住行完整性。
            self.separators = [
                "\n\n", "。", "！", "？", ". ", "! ", "? ", ".", "!", "?",
                "，", ",", "\n", " ", "",
            ]
        else:
            self.separators = separators

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """切分文档列表，并对同页碎块做小碎块合并。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表，doc_id 按 ``{原doc_id}_chunk_{序号}`` 重新编号。
        """
        split_docs = []

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'unknown')

            chunks = await self._split_text(text)

            for i, chunk in enumerate(chunks):
                split_docs.append({
                    'text': chunk,
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_chunk_{i}",
                    'type': doc_type
                })

        # 对同一页的所有分块做小碎块合并
        if self.min_chunk_size > 0:
            split_docs = merge_small_chunks(
                split_docs, self.min_chunk_size, self.chunk_size
            )
            # 重新编号
            for i, doc in enumerate(split_docs):
                doc['doc_id'] = f"{doc['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{i}"

        return split_docs

    async def _split_text(self, text: str) -> list[str]:
        """按分隔符优先级递归切分单篇文本，同级片段贪心聚拢到 chunk_size。

        切分后不直接保留裸片段，而是把同级小片段贪心装填到接近 chunk_size，
        避免"句长 80 字 × chunk_size 1000"类文本被切成均块仅 ~160 字的
        系统性欠填充（欠填充导致 embedding 数量膨胀、单块上下文不足）。
        """
        if len(text) <= self.chunk_size:
            return [text]

        # 选择当前使用的分隔符
        separator = self.separators[0]
        for sep in self.separators:
            if sep in text:
                separator = sep
                break

        # 使用选定的分隔符分割文本
        # 自带分隔符路径（捕获组保回标点）：片段含句读符号，聚拢时直接拼接；
        # 其余路径 split 会丢弃分隔符，聚拢时必须补回，否则词/段落粘连
        #（如空格路径 "abc def" 会粘成 "abcdefghi"）。
        if separator == "":
            texts = list(text)
            joiner = ""
        elif separator in ('. ', '! ', '? ', '。', '！', '？', '，'):
            raw_parts = re.split(f'({re.escape(separator)})', text)
            # 捕获组切分总是奇数长度 [seg, sep, seg, ..., seg]；
            # 按 seg+sep 配对保回标点，尾段（最后一片）不得丢弃
            texts = [
                raw_parts[i] + (raw_parts[i + 1] if i + 1 < len(raw_parts) else '')
                for i in range(0, len(raw_parts), 2)
            ]
            joiner = ""
        else:
            texts = text.split(separator)
            joiner = separator

        # 超限片段递归下沉到更细分隔符；达标片段贪心装填聚拢
        final_texts: list[str] = []
        # 装填缓冲：累积同级片段直到再加一片会超 chunk_size
        buffer = ""

        def _flush_buffer() -> None:
            nonlocal buffer
            if buffer:
                final_texts.append(buffer)
                buffer = ""

        for t in texts:
            if len(t) <= self.chunk_size:
                if not t.strip():
                    continue
                # 装得下就并入缓冲（补回被 split 丢弃的分隔符）；装不下先冲刷
                # 已装内容再开新缓冲。空缓冲 + 单片段超限理论不可达
                #（len(t) <= chunk_size），此分支保证冲刷逻辑不依赖该假设。
                joined_len = len(buffer) + len(joiner) + len(t)
                if joined_len <= self.chunk_size or not buffer:
                    buffer = t if not buffer else buffer + joiner + t
                else:
                    _flush_buffer()
                    buffer = t
            else:
                _flush_buffer()
                next_separators = self.separators[self.separators.index(separator) + 1:]
                if next_separators:
                    next_splitter = RecursiveCharacterSplitter(
                        chunk_size=self.chunk_size,
                        chunk_overlap=self.chunk_overlap,
                        separators=next_separators,
                        min_chunk_size=0,  # 子切分器不做合并，由顶层统一合并
                    )
                    final_texts.extend(await next_splitter._split_text(t))
                else:
                    step = max(self.chunk_size - self.chunk_overlap, 1)
                    for i in range(0, len(t), step):
                        chunk = t[i:i + self.chunk_size]
                        if chunk.strip():
                            final_texts.append(chunk)

        _flush_buffer()
        return final_texts
