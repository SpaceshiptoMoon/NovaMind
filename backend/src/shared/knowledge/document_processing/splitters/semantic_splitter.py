import numpy as np
from typing import List, Dict
from novamind.shared.knowledge.document_processing.splitters.base_splitter import BaseSplitter
from novamind.shared.ai_models.base_model import BaseEmbedding


class SemanticSplitter(BaseSplitter):
    """语义切分器，基于语义相似度进行文本切分"""

    def __init__(self, embedding_client: BaseEmbedding, 
                 max_chunk_size: int = 1000, 
                 similarity_threshold: float = 0.7,
                 batch_size: int = 20):
        """
        初始化语义切分器
        :param embedding_client: 嵌入模型客户端
        :param max_chunk_size: 最大块大小
        :param similarity_threshold: 相似度阈值，低于此值则切分
        :param batch_size: 批处理大小，用于批量生成嵌入向量
        """
        super().__init__()
        self.embedding_client = embedding_client
        self.max_chunk_size = max_chunk_size
        self.similarity_threshold = similarity_threshold
        self.batch_size = batch_size

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
            
            chunks = await self._split_text_semantically(text)
            
            for i, chunk in enumerate(chunks):
                split_docs.append({
                    'text': chunk,
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_sem_chunk_{i}",
                    'type': doc_type
                })
        
        return split_docs

    async def _split_text_semantically(self, text: str) -> List[str]:
        """
        基于语义的文本切分
        :param text: 输入文本
        :return: 切分后的文本块列表
        """
        # 首先使用递归字符切分器进行初步切分
        from novamind.shared.knowledge.document_processing.splitters.recursive_splitter import RecursiveCharacterSplitter
        
        # 使用较小的块大小进行初步切分，以确保不超过最大限制
        preliminary_splitter = RecursiveCharacterSplitter(
            chunk_size=min(self.max_chunk_size, 500),
            chunk_overlap=50
        )
        
        preliminary_chunks = await preliminary_splitter._split_text(text)
        
        if len(preliminary_chunks) <= 1:
            return preliminary_chunks
        
        # 使用批次向量化获取所有块的嵌入向量
        embeddings = await self.embedding_client.generate_embeddings_batch(preliminary_chunks, self.batch_size)
        
        # 计算相邻块的相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            # 将numpy数组转换为列表以确保兼容性
            emb1 = np.array(embeddings[i]).reshape(1, -1)
            emb2 = np.array(embeddings[i+1]).reshape(1, -1)
            
            # 计算余弦相似度
            cosine_sim = (emb1 @ emb2.T)[0][0] / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            similarities.append(cosine_sim)
        
        # 根据相似度阈值确定切分点
        chunks = []
        current_chunk = ""
        
        for i, chunk_text in enumerate(preliminary_chunks):
            if i == 0:
                # 第一个块直接添加
                current_chunk = chunk_text
            else:
                # 检查是否应该切分
                similarity = similarities[i-1]
                
                # 如果相似度低于阈值，或者当前块加上新块会超过最大大小，则切分
                if similarity < self.similarity_threshold or len(current_chunk + chunk_text) > self.max_chunk_size:
                    if current_chunk.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = chunk_text
                else:
                    # 否则合并到当前块
                    current_chunk += " " + chunk_text
        
        # 添加最后一个块
        if current_chunk.strip():
            chunks.append(current_chunk.strip())
        
        return chunks