import re
from typing import List, Dict, Optional
from novamind.shared.knowledge.document_processing.splitters.base_splitter import BaseSplitter


class RecursiveCharacterSplitter(BaseSplitter):
    """递归字符切分器，按不同级别的分隔符切分文本"""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 100,
                 separators: Optional[List[str]] = None, min_chunk_size: int = 500):
        """
        初始化切分器
        :param chunk_size: 块大小
        :param chunk_overlap: 重叠大小
        :param separators: 分隔符列表，按优先级排序
        :param min_chunk_size: 最小块大小，小于此大小的块会与相邻块合并（0 表示不限制）
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

        if separators is None:
            self.separators = ["\n\n", "。", "！", "？", ".", "!", "?", ",", ",", "\n", " ", ""]
        else:
            self.separators = separators

    async def split(self, documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        切分文档列表
        :param documents: 原始文档列表
        :return: 切分后的文档块列表
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
            split_docs = self._merge_small_chunks(split_docs)
            # 重新编号
            for i, doc in enumerate(split_docs):
                doc['doc_id'] = f"{doc['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{i}"

        return split_docs

    async def _split_text(self, text: str) -> List[str]:
        """
        实际的文本切分逻辑
        :param text: 输入文本
        :return: 切分后的文本块列表
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
        if separator == "":
            texts = list(text)
        else:
            if separator in ['. ', '? ', '! ']:
                texts = re.split(f'({re.escape(separator)})', text)
                sentences = []
                for i in range(0, len(texts) - 1, 2):
                    if i + 1 < len(texts):
                        sentences.append(texts[i] + texts[i + 1])
                    else:
                        sentences.append(texts[i])
                texts = sentences
            else:
                texts = text.split(separator)

        # 如果分割后的文本片段仍大于块大小，则使用更细粒度的分隔符继续切分
        final_texts = []
        for t in texts:
            if len(t) <= self.chunk_size:
                if t.strip():
                    final_texts.append(t)
            else:
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
                    for i in range(0, len(t), self.chunk_size - self.chunk_overlap):
                        chunk = t[i:i + self.chunk_size]
                        if chunk.strip():
                            final_texts.append(chunk)

        return final_texts

    def _merge_small_chunks(self, chunks: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        合并文本长度小于 min_chunk_size 的碎块与相邻块

        策略：从左到右扫描，小块优先向后合并（与下一个块拼接），
        如果向后合并会超过 chunk_size，则尝试向前合并（与上一个块拼接）。
        """
        if not chunks:
            return chunks

        # 提取文本用于合并计算
        texts = [c['text'] for c in chunks]

        # 用合并后的文本重建文档列表，保留第一个块的元数据
        result = []
        chunk_idx = 0
        i = 0
        while i < len(texts):
            current_text = texts[i]
            if len(current_text) < self.min_chunk_size and i + 1 < len(texts):
                combined = current_text + "\n" + texts[i + 1]
                if len(combined) <= self.chunk_size:
                    # 向后合并：两个块合成一个
                    result.append({
                        'text': combined,
                        'source': chunks[i]['source'],
                        'page': chunks[i]['page'],
                        'doc_id': f"{chunks[i]['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{chunk_idx}",
                        'type': chunks[i]['type'],
                    })
                    chunk_idx += 1
                    i += 2
                    continue
                else:
                    # 向后合并超限，尝试向前合并到最后一个结果
                    if result and len(result[-1]['text'] + "\n" + current_text) <= self.chunk_size:
                        result[-1]['text'] += "\n" + current_text
                        i += 1
                        continue
            # 不需要合并，直接保留
            result.append({
                'text': current_text,
                'source': chunks[i]['source'],
                'page': chunks[i]['page'],
                'doc_id': f"{chunks[i]['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{chunk_idx}",
                'type': chunks[i]['type'],
            })
            chunk_idx += 1
            i += 1

        return result
