"""分隔符切分器：按用户自定义字面量分隔符级联切段。"""
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.chunk_merge import merge_small_chunks
from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter

# 未配置分隔符时的策略默认语义：按空行切段。就近定义而非放进 features schema
# 常量区（engines 不反向依赖 features；schema 层 separators 保持 None 规范形）。
DEFAULT_SEPARATORS: list[str] = ["\n\n"]


class DelimiterSplitter(BaseSplitter):
    """分隔符切分器，按字面量分隔符把文本切段，分隔符本身不进入任何块。

    与 RecursiveCharacterSplitter 的区别：分隔符由调用方显式给定且全部生效
    （级联应用，非「首个命中即用」）；切分边界完全由分隔符与长度上限决定，
    不做句读/词语层面的二次下探。
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        min_chunk_size: int = 500,
        separators: list[str] | None = None,
    ):
        """初始化分隔符切分器。

        Args:
            chunk_size: 单块最大字符数（硬上限），超长段按此窗口硬切。
            chunk_overlap: 超长段硬切的相邻块重叠字符数，仅硬切路径生效
                （分隔符切出的段之间天然有边界，不重叠）。
            min_chunk_size: 最小块大小阈值，小于此值的碎段与相邻段合并；
                0 表示禁用合并。上限自动夹取到 ``chunk_size // 2``，防止
                min > max 的配置矛盾导致合并条件永不满足。
            separators: 分隔符列表（字面量匹配、按序级联应用、切分后丢弃）。
                None/空列表/全空串项时回落 ``DEFAULT_SEPARATORS``（空行）。
                注意项不做 strip——空白类分隔符（``"\\n\\n"``）strip 后即空串。
        """
        super().__init__()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        # min_chunk_size 只用于事后合并的触发阈值，超过 chunk_size 的一半就失去
        # 意义（合并结果几乎必然超限而跳过）；夹取而非抛错，容忍存量配置漂移。
        self.min_chunk_size = min(min_chunk_size, chunk_size // 2)

        cleaned = [sep for sep in (separators or []) if sep]
        self.separators = cleaned if cleaned else list(DEFAULT_SEPARATORS)

    async def split(self, documents: list[dict[str, str]]) -> list[dict[str, str]]:
        """按分隔符级联切段并处理超长段/碎段，分隔符不保留在任何块中。

        Args:
            documents: 原始文档列表，每项含 text/source，可选 page/doc_id/type。

        Returns:
            切分后的文档块列表，doc_id 按 ``{原doc_id}_delimiter_chunk_{序号}``
            编号；启用 min_chunk_size 合并后按新顺序重新编号。
        """
        split_docs = []
        hard_splitter = FixedSizeSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        for doc in documents:
            text = doc['text']
            source = doc['source']
            original_page = doc.get('page', 1)
            original_doc_id = doc.get('doc_id', '')
            doc_type = doc.get('type', 'unknown')

            segments = self._split_by_separators(text)
            raw: list[str] = []
            for seg in segments:
                if len(seg) > self.chunk_size:
                    # 超长段固定窗口硬切：滑动窗口不变量（overlap>=chunk_size
                    # 退化、末块整块输出防死循环）由 FixedSizeSplitter 承载
                    # 并有专项测试，复用而非复制实现。
                    raw.extend(hard_splitter._split_text_fixed_size(seg))
                else:
                    raw.append(seg)

            chunks = [c.strip() for c in raw if c.strip()]
            for i, chunk in enumerate(chunks):
                split_docs.append({
                    'text': chunk,
                    'source': source,
                    'page': original_page,
                    'doc_id': f"{original_doc_id}_delimiter_chunk_{i}",
                    'type': doc_type,
                })

        # 小碎块合并与重新编号（镜像 recursive 的顶层统一合并语义）
        if self.min_chunk_size > 0:
            split_docs = merge_small_chunks(split_docs, self.min_chunk_size, self.chunk_size)
            for i, doc in enumerate(split_docs):
                doc['doc_id'] = f"{doc['doc_id'].rsplit('_chunk_', 1)[0]}_chunk_{i}"

        return split_docs

    def _split_by_separators(self, text: str) -> list[str]:
        """按序对全部分隔符做字面量级联切分，分隔符随切分丢弃。

        级联而非 recursive 式「首个命中即用」：用户列出多个分隔符的预期是
        两者都是边界，first-match-wins 会漏掉其余分隔符的切分位置。

        Args:
            text: 待切分的单篇全文。

        Returns:
            切出的原始段列表（保留首尾空白，由上层统一清洗与丢弃空段）。
        """
        segments = [text]
        for sep in self.separators:
            segments = [piece for seg in segments for piece in seg.split(sep)]
        return segments
