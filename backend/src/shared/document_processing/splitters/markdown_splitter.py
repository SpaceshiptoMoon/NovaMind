import re
from typing import List, Dict
from src.shared.document_processing.splitters.base_splitter import BaseSplitter


class MarkdownSplitter(BaseSplitter):
    """Markdown文档切分器，按Markdown结构进行切分"""

    def __init__(self, max_chunk_size: int = 1000, min_chunk_size: int = 50):
        """
        初始化Markdown切分器
        :param max_chunk_size: 最大块大小
        :param min_chunk_size: 最小块大小，小于这个值的块会被合并到前一个块
        """
        super().__init__()
        self.max_chunk_size = max_chunk_size
        self.min_chunk_size = min_chunk_size

    async def split(self, documents: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        按Markdown结构切分文档
        :param documents: 原始文档列表
        :return: 切分后的文档块列表
        """
        split_docs = []

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'markdown')
            original_title = doc.get('title', '')

            chunks = await self._split_markdown_by_structure(text, original_title)

            for i, chunk in enumerate(chunks):
                split_docs.append({
                    'text': chunk['content'].strip(),
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_md_chunk_{i}",
                    'type': doc_type,
                    'title': chunk['title'],
                    'level': chunk.get('level', 0)
                })

        return split_docs

    async def _split_markdown_by_structure(self, text: str, title: str = "") -> List[Dict[str, str]]:
        """
        根据Markdown结构切分文本
        :param text: 输入的Markdown文本
        :param title: 原始文档标题
        :return: 切分后的文本块列表
        """
        # 按标题分割文档
        parts = self._split_by_headers(text)
        
        chunks = []
        current_chunk = {"content": "", "title": title, "level": 0}
        
        for part in parts:
            part_content = part['content']
            part_title = part['title']
            part_level = part['level']
            
            # 如果当前块加上新内容超过最大大小，且当前块不是空的，则保存当前块并开始新块
            if (len(current_chunk["content"]) + len(part_content) > self.max_chunk_size 
                and current_chunk["content"].strip()):
                
                # 保存当前块
                if len(current_chunk["content"].strip()) >= self.min_chunk_size:
                    chunks.append(current_chunk)
                
                # 开始新块
                current_chunk = {
                    "content": part_content,
                    "title": part_title,
                    "level": part_level
                }
            else:
                # 否则将内容添加到当前块
                if current_chunk["content"]:
                    current_chunk["content"] += "\n\n" + part_content
                else:
                    current_chunk["content"] = part_content
                
                # 更新标题和层级（使用较高级别的标题作为块标题）
                if part_level < current_chunk["level"] or current_chunk["level"] == 0:
                    current_chunk["title"] = part_title
                    current_chunk["level"] = part_level
                elif part_level == current_chunk["level"] and not current_chunk["title"]:
                    current_chunk["title"] = part_title

        # 添加最后一个块
        if current_chunk["content"].strip() and len(current_chunk["content"].strip()) >= self.min_chunk_size:
            chunks.append(current_chunk)

        # 进一步处理过长的段落
        refined_chunks = []
        for chunk in chunks:
            if len(chunk["content"]) > self.max_chunk_size:
                # 对于过大的块，尝试按段落进一步分割
                sub_chunks = self._split_large_chunk(chunk)
                refined_chunks.extend(sub_chunks)
            else:
                refined_chunks.append(chunk)

        return refined_chunks

    def _split_by_headers(self, text: str) -> List[Dict[str, str]]:
        """
        按Markdown标题分割文本
        :param text: Markdown文本
        :return: 分割后的部分列表
        """

        
        # 找到所有标题及其内容
        parts = []
        lines = text.split('\n')
        current_part = {"content": "", "title": "", "level": 0}
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # 检查是否是标题行
            header_match = re.match(r'^(#{1,6})\s+(.+)', line)
            if header_match:
                # 保存之前的部分（如果不是第一个部分）
                if current_part["content"]:
                    parts.append(current_part)
                
                # 设置新部分的标题和层级
                level = len(header_match.group(1))
                title = header_match.group(2).strip()
                
                # 收集该标题下的所有内容
                content_lines = [line]
                i += 1
                while i < len(lines):
                    next_line = lines[i]
                    next_header_match = re.match(r'^(#{1,6})\s+', next_line)
                    if next_header_match:  # 下一行又是标题
                        break
                    content_lines.append(next_line)
                    i += 1
                
                current_part = {
                    "content": "\n".join(content_lines),
                    "title": title,
                    "level": level
                }
            else:
                # 非标题开头的内容（通常是文档开头的无标题部分）
                if not current_part["content"]:
                    current_part["content"] = line
                else:
                    current_part["content"] += "\n" + line
                i += 1
        
        # 添加最后的部分
        if current_part["content"]:
            parts.append(current_part)
        
        return parts

    def _split_large_chunk(self, chunk: Dict[str, str]) -> List[Dict[str, str]]:
        """
        进一步分割过大的块
        :param chunk: 需要分割的块
        :return: 分割后的块列表
        """
        content = chunk["content"]
        title = chunk["title"]
        level = chunk["level"]

        # 按段落分割（以双换行符为界）
        paragraphs = content.split("\n\n")
        
        chunks = []
        current_content = ""
        
        for paragraph in paragraphs:
            # 如果单个段落就很大，按句子分割
            if len(paragraph) > self.max_chunk_size:
                sentence_chunks = self._split_by_sentences(paragraph)
                for sent_chunk in sentence_chunks:
                    if len(sent_chunk) <= self.max_chunk_size:
                        chunks.append({
                            "content": sent_chunk,
                            "title": title,
                            "level": level
                        })
                    else:
                        # 如果句子也太长，按固定大小分割
                        fixed_chunks = self._split_by_fixed_size(sent_chunk)
                        for fixed_chunk in fixed_chunks:
                            chunks.append({
                                "content": fixed_chunk,
                                "title": title,
                                "level": level
                            })
            else:
                # 检查添加这个段落是否会超出大小限制
                if len(current_content + "\n\n" + paragraph) > self.max_chunk_size and current_content:
                    # 保存当前内容为一个块
                    chunks.append({
                        "content": current_content.strip(),
                        "title": title,
                        "level": level
                    })
                    # 开始新的内容
                    current_content = paragraph
                else:
                    if current_content:
                        current_content += "\n\n" + paragraph
                    else:
                        current_content = paragraph
        
        # 添加最后一个内容块
        if current_content:
            chunks.append({
                "content": current_content.strip(),
                "title": title,
                "level": level
            })
        
        # 过滤掉太小的块
        return [
            c for c in chunks 
            if len(c["content"].strip()) >= self.min_chunk_size
        ]

    def _split_by_sentences(self, text: str) -> List[str]:
        """
        按句子分割文本
        :param text: 输入文本
        :return: 句子列表
        """
        # 匹配中文和英文的句子结束标点
        sentence_endings = r'[.!?。！？]'

        
        # 重构句子，把标点符号加回去
        sentence_list = []
        matches = list(re.finditer(sentence_endings, text))
        start_idx = 0
        
        for i, match in enumerate(matches):
            sentence = text[start_idx:match.end()]
            sentence_list.append(sentence)
            start_idx = match.end()
        
        # 处理最后一部分（如果没有以句子结束符结尾的部分）
        if start_idx < len(text):
            remaining = text[start_idx:]
            if sentence_list and remaining.strip():
                sentence_list[-1] += remaining
        
        # 组合短句以达到最小长度
        combined_sentences = []
        current_sentence = ""
        
        for sentence in sentence_list:
            if len(current_sentence + " " + sentence) <= self.max_chunk_size or not current_sentence:
                if current_sentence:
                    current_sentence += " " + sentence
                else:
                    current_sentence = sentence
            else:
                combined_sentences.append(current_sentence.strip())
                current_sentence = sentence
        
        if current_sentence:
            combined_sentences.append(current_sentence.strip())
        
        return combined_sentences

    def _split_by_fixed_size(self, text: str) -> List[str]:
        """
        按固定大小分割文本
        :param text: 输入文本
        :return: 固定大小的文本块列表
        """
        if len(text) <= self.max_chunk_size:
            return [text]

        chunks = []
        start_idx = 0

        while start_idx < len(text):
            end_idx = start_idx + self.max_chunk_size
            if end_idx > len(text):
                end_idx = len(text)
            
            chunk = text[start_idx:end_idx]
            chunks.append(chunk)
            
            start_idx = end_idx

        return chunks