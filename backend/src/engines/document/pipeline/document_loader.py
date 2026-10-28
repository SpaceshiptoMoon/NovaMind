"""文档解析管道：DocumentLoader（按扩展名路由解析器） + DocumentProcessor（编排解析 / 切分 / 元数据） + DocumentRegistry（解析器注册表）。"""
import time
from pathlib import Path

from novamind.engines.document.integrations.deepdoc import (
    DeepDocEngine,
    DeepDocParser,
    DeepDocParseResult,
    strip_position_tags,
)
from novamind.engines.document.integrations.deepdoc.core.quality import (
    build_quality_metadata,
    collect_warnings,
)
from novamind.engines.document.pipeline.splitter_factory import (
    SplitterDeps,
    build_splitter,
    extract_splitting_params,
)
from novamind.engines.document.pipeline.tagged_rechunk import (
    build_tagged_text,
    rechunk_with_structure,
)
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.delimiter_splitter import DelimiterSplitter
from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter
from novamind.engines.document.splitters.hierarchical_splitter import HierarchicalSplitter
from novamind.engines.document.splitters.markdown_splitter import MarkdownSplitter
from novamind.engines.document.splitters.parent_child_splitter import ParentChildSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter
from novamind.engines.document.splitters.semantic_splitter import SemanticSplitter
from novamind.engines.document.splitters.sentence_window_splitter import SentenceWindowSplitter
from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.shared.document.readers.base_reader import BaseReader
from novamind.shared.document.readers.docx_reader import DocxReader
from novamind.shared.document.readers.html_reader import HTMLReader
from novamind.shared.document.readers.md_reader import MarkdownReader
from novamind.shared.document.readers.pdf_reader import PDFReader
from novamind.shared.document.readers.txt_reader import TxtReader
from novamind.shared.logging import get_logger

logger = get_logger(__name__)


class DocumentRegistry:
    """文档组件注册器，用于统一管理文档读取器和切分器"""
    
    # 注册表：文档读取器
    _readers_registry: dict[str, type[BaseReader]] = {}
    
    # 注册表：文档切分器
    _splitters_registry: dict[str, type[BaseSplitter]] = {}

    @classmethod
    def register_reader(cls, extension: str, reader_class: type[BaseReader] = None):
        """注册扩展名到读取器类的映射；支持装饰器与直接调用两种用法。

        Args:
            extension: 文件扩展名（不带点）。
            reader_class: 读取器类；None 时返回装饰器。

        Returns:
            直接调用返回 reader_class 本身；装饰器用法返回 decorator 函数。
        """
        def decorator(actual_reader_class: type[BaseReader]):
            cls._readers_registry[extension] = actual_reader_class
            return actual_reader_class
        
        if reader_class is not None:
            # 直接调用方式: register_reader(ext, ReaderClass)
            cls._readers_registry[extension] = reader_class
            return reader_class
        else:
            # 装饰器方式: @register_reader(ext)
            return decorator

    @classmethod
    def unregister_reader(cls, extension: str):
        """注销文档读取器。

        Args:
            extension: 文件扩展名。

        Returns:
            无返回；未注册的扩展名静默无操作。
        """
        if extension in cls._readers_registry:
            del cls._readers_registry[extension]

    @classmethod
    def register_splitter(cls, name: str, splitter_class: type[BaseSplitter] = None):
        """注册策略名到切分器类的映射；支持装饰器与直接调用两种用法。

        Args:
            name: 切分策略名。
            splitter_class: 切分器类；None 时返回装饰器。

        Returns:
            直接调用返回 splitter_class 本身；装饰器用法返回 decorator 函数。
        """
        def decorator(actual_splitter_class: type[BaseSplitter]):
            cls._splitters_registry[name] = actual_splitter_class
            return actual_splitter_class
        
        if splitter_class is not None:
            # 直接调用方式: register_splitter(name, SplitterClass)
            cls._splitters_registry[name] = splitter_class
            return splitter_class
        else:
            # 装饰器方式: @register_splitter(name)
            return decorator

    @classmethod
    def unregister_splitter(cls, name: str):
        """注销文档切分器。

        Args:
            name: 切分策略名。

        Returns:
            无返回；未注册的策略名静默无操作。
        """
        if name in cls._splitters_registry:
            del cls._splitters_registry[name]

    @classmethod
    def get_reader_class(cls, extension: str) -> type[BaseReader] | None:
        """获取指定扩展名的读取器类。

        Args:
            extension: 文件扩展名。

        Returns:
            读取器类；未注册为 None。
        """
        return cls._readers_registry.get(extension)

    @classmethod
    def get_splitter_class(cls, name: str) -> type[BaseSplitter] | None:
        """获取指定名称的切分器类。

        Args:
            name: 切分策略名。

        Returns:
            切分器类；未注册为 None。
        """
        return cls._splitters_registry.get(name)

    @classmethod
    def get_supported_formats(cls) -> list[str]:
        """获取支持的文件格式"""
        return list(cls._readers_registry.keys())

    @classmethod
    def get_available_strategies(cls) -> list[str]:
        """获取可用的切分策略"""
        return list(cls._splitters_registry.keys())


class DocumentLoader:
    """文档加载器，负责根据文件类型选择合适的读取器并进行切分"""

    def __init__(self, splitter: BaseSplitter, 
                 embedding_client: BaseEmbedding):
        """初始化文档加载器。

        Args:
            splitter: 文档切分器；传 None 时 load_and_split 按扩展名选默认切分器。
            embedding_client: 嵌入模型客户端，semantic 切分策略必需。
        """
        self.splitter = splitter
        self.embedding_client = embedding_client 
        
        # 初始化各种读取器（从注册表获取）
        self.readers = {}
        for ext, reader_class in DocumentRegistry._readers_registry.items():
            self.readers[ext] = reader_class()

    async def _get_default_splitter_for_extension(self, extension: str) -> BaseSplitter:
        """按扩展名返回默认切分器（md 用 MarkdownSplitter，其余用递归切分器）。"""
        if extension == 'pdf':
            # PDF 版面块密度高（段落短、表格/图注多），块取 TEXT 组的 40%：
            # 400 字符约为 1/3 页正文，兼顾检索精度与块数成本
            return RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=50)
        elif extension in ('md', 'markdown'):
            # Markdown使用专门的切分器
            return MarkdownSplitter()
        else:
            # 其他文件类型使用默认的递归字符切分器
            return RecursiveCharacterSplitter()

    async def load_and_split(self, file_path: str | Path) -> list[dict[str, str]]:
        """按扩展名路由到读取器加载文档，再用切分器切分。

        Args:
            file_path: 文件路径。

        Returns:
            切分后的文档块列表。

        Raises:
            FileNotFoundError: 文件不存在。
            ValueError: 扩展名未注册读取器。
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")
        
        # 根据文件扩展名选择读取器
        extension = file_path.suffix.lower().lstrip('.')
        
        if extension not in self.readers:
            raise ValueError(f"Unsupported file type: {extension}. "
                             f"Supported types: {list(self.readers.keys())}")
        
        # 使用对应的读取器加载文档
        reader = self.readers[extension]
        documents = await reader.load_data(str(file_path))
        
        # 如果没有指定切分器，按文件类型选默认切分器——只作用于本次调用，
        # 绝不写回 self.splitter（实例级写回会让 load_multiple_files 里
        # 第一个文件的切分器污染后续所有不同类型文件）
        splitter = self.splitter
        if splitter is None:
            splitter = await self._get_default_splitter_for_extension(extension)

        # 切分文档
        split_documents = await splitter.split(documents)
        
        return split_documents

    async def load_multiple_files(self, file_paths: list[str | Path]) -> list[dict[str, str]]:
        """顺序加载并切分多个文件，结果合并为一个列表。

        Args:
            file_paths: 文件路径列表。

        Returns:
            全部文件的切分块合并列表（顺序与输入一致）。

        Raises:
            FileNotFoundError: 任一文件不存在。
            ValueError: 任一扩展名未注册读取器。
        """
        all_documents = []
        for file_path in file_paths:
            documents = await self.load_and_split(file_path)
            all_documents.extend(documents)
        
        return all_documents

    @staticmethod
    async def get_supported_formats() -> list[str]:
        """返回注册表支持的扩展名列表。"""
        return DocumentRegistry.get_supported_formats()


class DocumentProcessor:
    """文档处理器，提供高级文档处理功能

    支持两阶段处理：
    1. read_full_text() — 读取文件并返回全文（reader-only）
    2. split_text() — 对文本进行切分（splitter-only）
    3. load_with_strategy() — 一键读+切（为兼容旧调用保留）
    """

    def __init__(self, embedding_client: BaseEmbedding | None = None):
        """初始化读取器注册表与 DeepDoc 解析引擎；embedding 客户端可选，仅 semantic 切分需要，缺省时该策略回退 recursive。"""
        self.embedding_client = embedding_client
        self._deepdoc_parser = DeepDocParser()
        self._deepdoc_engine = DeepDocEngine(parser=self._deepdoc_parser)
        # 初始化各种读取器（从注册表获取）
        self._readers: dict[str, BaseReader] = {}
        for ext, reader_class in DocumentRegistry._readers_registry.items():
            self._readers[ext] = reader_class()

    async def read_full_text(
        self,
        file_path: str | Path,
    ) -> str:
        """Reader-only：读取文件并合并为全文，不做切分。

        支持的文件类型由 DocumentRegistry 注册表决定：
        pdf, docx, txt, html, md, markdown 等。

        Args:
            file_path: 文件路径。

        Returns:
            文件的完整文本内容。扫描版 PDF（文字层为空）需改用 DeepDoc 策略，
            本路径不做 OCR 兜底。

        Raises:
            ValueError: 不支持的文件类型。
            FileNotFoundError: 文件不存在。
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File does not exist: {file_path}")

        extension = file_path.suffix.lower().lstrip('.')

        reader = self._readers.get(extension)
        if reader is None:
            raise ValueError(
                f"Unsupported file type: {extension}. "
                f"Supported types: {list(self._readers.keys())}"
            )

        # 使用读取器加载文档（返回 List[Dict[str, str]]，每个 dict 代表一页/一段）
        documents = await reader.load_data(str(file_path))

        # 合并所有段落/页面为一个全文
        full_text = "\n\n".join(
            doc.get("content") or doc.get("text", "") for doc in documents
        )

        if not full_text.strip() and extension == "pdf":
            logger.warning(
                "PDF 文字层为空（疑似扫描件），默认策略无法提取内容；"
                "请在 KB 配置中将 PDF 解析策略改为 DeepDoc",
                filename=file_path.name,
            )

        logger.info(
            "文档全文读取完成",
            filename=file_path.name,
            extension=extension,
            paragraphs=len(documents),
            char_count=len(full_text),
        )
        return full_text

    async def split_text(
        self,
        text: str,
        strategy: str = 'recursive',
        **kwargs,
    ) -> list[str]:
        """Splitter-only：对纯文本按指定策略切分，返回 chunk 文本列表。

        不读取文件，只做切分。需要 per-chunk 元数据（关系指针等）的调用方
        请用 :meth:`split_text_items`。

        Args:
            text: 要切分的全文文本。
            strategy: 切分策略（'recursive' / 'semantic' / 'fixed_size' / 'markdown' / 'delimiter' / 'sentence_window' / 'parent_child' / 'hierarchical'）。
            **kwargs: 策略特定参数（chunk_size / similarity_threshold 等），逐策略透传。

        Returns:
            切分后的文本块列表（纯文本，非 dict）。

        Raises:
            ValueError: 策略名未注册。
        """
        items = await self.split_text_items(text, strategy=strategy, **kwargs)
        return [t for t, _meta in items]

    async def split_text_items(
        self,
        text: str,
        strategy: str = 'recursive',
        **kwargs,
    ) -> list[tuple[str, dict]]:
        """对纯文本按指定策略切分，返回 (chunk 文本, per-chunk 元数据) 列表。

        ``split_text`` 的孪生方法：与 recursive 等存量策略不同，sentence_window /
        parent_child 产物携带关系元数据（expansion_type / chunk_role / parent_slot），
        上游据此写进 ES chunk metadata——检索期扩窗/回带全靠它。存量策略恒空 dict。

        Args:
            text: 要切分的全文文本。
            strategy: 切分策略名（须已注册）。
            **kwargs: 策略特定参数，逐策略透传。

        Returns:
            ``[(chunk_text, meta_dict), ...]``，meta 为切分器产出的关系元数据
            （无关系的策略为空 dict）；纯空白块已过滤。

        Raises:
            ValueError: 策略名未注册。
        """
        # 装配统一走 splitter_factory（批次 2 收敛）：此前本方法与
        # load_with_strategy / split_md_text 各持一份 if/elif 装配副本，
        # 默认值已漂移；装配知识现单一归属 splitter_factory 注册表。
        splitter = build_splitter(
            strategy,
            kwargs,
            SplitterDeps(embedding_client=self.embedding_client),
        )

        # 对全文进行切分 — 将文本包装为单页文档
        documents = [{"text": text, "content": text, "source": "", "metadata": {}}]
        chunks = await splitter.split(documents)
        items = [
            (
                chunk.get("content") or chunk.get("text", ""),
                chunk.get("meta") or {},
            )
            for chunk in chunks
            if (chunk.get("content") or chunk.get("text", "")).strip()
        ]

        logger.info(
            "文本切分完成",
            strategy=strategy,
            char_count=len(text),
            chunk_count=len(items),
            meta_carrier_count=sum(1 for _t, m in items if m),
        )
        return items

    async def parse_document(
        self,
        file_path: str | Path,
        parsing_config: dict[str, object] | None = None,
        splitting_config: dict[str, object] | None = None,
    ) -> tuple[str, list[str]]:
        """解析文档并切分，返回 (full_text, chunks) 二元组；完整元数据请用 parse_document_result。

        Args:
            file_path: 文件路径。
            parsing_config: 解析配置（strategy / deepdoc_parser_id 等）。
            splitting_config: 切分配置（strategy / chunk_size / chunk_overlap 等）。

        Returns:
            (全文文本, 分块文本列表) 二元组；不含坐标等元数据。

        Raises:
            ValueError: 文件类型不支持或切分策略名未注册。
        """
        result = await self.parse_document_result(
            file_path,
            parsing_config=parsing_config,
            splitting_config=splitting_config,
        )
        return result.full_text, result.chunks

    async def parse_document_result(
        self,
        file_path: str | Path,
        parsing_config: dict[str, object] | None = None,
        splitting_config: dict[str, object] | None = None,
    ) -> DeepDocParseResult:
        """主解析入口：deepdoc 策略走 DeepDoc 引擎加哨兵重切，默认走 reader+splitter。

        Args:
            file_path: 文件路径。
            parsing_config: 解析配置（strategy / parser_id / pdf_mode 等）。
            splitting_config: 切分配置（strategy/chunk_size 等，无 embedding 时回退）。

        Returns:
            DeepDocParseResult：full_text 为无坐标标记全文，chunks 按配置重切，
            metadata 含 split_strategy / chunk_structure 等。

        Raises:
            ValueError: 文件类型不支持或切分策略名未注册。
        """
        parsing_config = dict(parsing_config or {})
        splitting_config = dict(splitting_config or {})
        # 缺失/None 归一为 default；未知策略显式拒绝而非静默落 default——
        # 脏配置（如手改持久化数据）按内置 reader 解析会让扫描件抽出 0 字符
        # 才暴露，错误方向不可追踪。external_ocr 在 pipeline 层分发，不进本方法。
        parsing_strategy = str(parsing_config.get("strategy") or "default")
        if parsing_strategy not in ("default", "deepdoc"):
            raise ValueError(
                f"Unknown parsing strategy: {parsing_strategy}. "
                f"Supported: ['default', 'deepdoc']"
            )
        file_type = Path(file_path).suffix.lower().lstrip(".")

        if parsing_strategy == "deepdoc":
            parser_id = parsing_config.get("deepdoc_parser_id")
            logger.info(
                "DeepDoc 解析开始",
                filename=Path(file_path).name,
                file_type=file_type,
                parsing_strategy=parsing_strategy,
                deepdoc_parser_id=parser_id,
                deepdoc_pdf_mode=parsing_config.get("deepdoc_pdf_mode"),
                splitting_strategy=splitting_config.get("strategy", "recursive"),
                splitting_chunk_size=splitting_config.get("chunk_size", 1000),
                splitting_chunk_overlap=splitting_config.get("chunk_overlap", 100),
            )
            if parser_id:
                parse_result = await self._deepdoc_engine.aparse_with_parser_id(
                    file_type=file_type,
                    parser_id=str(parser_id),
                    file_path=file_path,
                    parsing_config=parsing_config,
                    splitting_config=splitting_config,
                )
            else:
                parse_result = await self._deepdoc_parser.parse(
                    file_path,
                    parsing_config=parsing_config,
                    splitting_config=splitting_config,
                )
            logger.info(
                "DeepDoc 解析完成",
                filename=Path(file_path).name,
                char_count=len(parse_result.full_text),
                chunk_count=len(parse_result.chunks),
                deepdoc_parser_id=parse_result.metadata.get("parser_id", parser_id),
                deepdoc_rechunked=parse_result.metadata.get("deepdoc_rechunked", False),
            )
            # DeepDoc 内部仅做简单拼接分块（_chunk_blocks），忽略用户配置的
            # splitting strategy/overlap/min_chunk_size/max_chunk_size。
            # 对 full_text 按用户配置的 splitting 参数重新切分，以尊重配置。
            #
            # full_text 本身干净（无坐标标记）；版面坐标只存在于
            # metadata.reading_order[] 的 position_tag/bbox。原始 @@...## 标记
            # 过不了切分器（recursive 的分隔符含 "." 且 text.split() 丢分隔符），
            # 因此把每个 reading_order entry 编码为 PUA 哨兵单字符喂给切分器，
            # 切完按 ord() 找回哨兵聚合出 chunk 的页码坐标，再剥哨兵得干净正文
            #（tagged_rechunk，引用溯源数据链基础）。
            reading_order = list((parse_result.metadata or {}).get("reading_order") or [])
            tagged_text, sentinel_map, encoded_count, degraded_count = build_tagged_text(reading_order)
            if tagged_text:
                rechunk_source_text = tagged_text
            else:
                # reading_order 缺失/全空（如 plain 模式、老快照）——退化为纯文本切分
                rechunk_source_text = strip_position_tags(parse_result.full_text)
                sentinel_map = {}
                logger.info(
                    "DeepDoc reading_order 缺失，哨兵重切降级为纯文本切分",
                    filename=Path(file_path).name,
                )
            split_strategy = str(splitting_config.get("strategy", "recursive"))
            # "semantic" 策略需要 embedding_client，DeepDoc 路径暂不支持，回退到 recursive
            if split_strategy == "semantic" and self.embedding_client is None:
                logger.warning(
                    "DeepDoc 路径暂不支持 semantic 切分（无 embedding_client），回退到 recursive",
                    filename=Path(file_path).name,
                )
                split_strategy = "recursive"
            # 哨兵替身按 \n\n 连接 entry 文本，与 full_text 同构——split_text_items
            # 产出的关系元数据（parent_slot/expansion_type）随替身片段穿越哨兵
            # 聚合，由 rechunk_with_structure 按最终块透传（孤儿前递/尾部挂靠同
            # chunk_structure 规则），DeepDoc 路径与新策略不再互斥。
            tagged_split_items = await self.split_text_items(
                rechunk_source_text,
                strategy=split_strategy,
                **extract_splitting_params(splitting_config),
            )
            tagged_rechunked = [t for t, _meta in tagged_split_items]
            tagged_chunk_metas = [meta for _t, meta in tagged_split_items]
            clean_chunks, chunk_structure, structure_source, chunk_structure_meta = (
                rechunk_with_structure(tagged_rechunked, sentinel_map, tagged_chunk_metas)
            )
            result_metadata = {
                **parse_result.metadata,
                "split_strategy": split_strategy,
                "deepdoc_rechunked": True,
                "chunk_structure": chunk_structure,
                "chunk_structure_source": structure_source,
                "tagged_rechunk_encoded_entries": encoded_count,
                "tagged_rechunk_degraded_entries": degraded_count,
            }
            # 关系元数据按位对齐透出（默认分支同名键）；仅存在非空 meta 时写键，
            # 存量策略保持 metadata 形状不变。
            if any(chunk_structure_meta):
                result_metadata["chunk_structure_meta"] = chunk_structure_meta
            parse_result = DeepDocParseResult(
                full_text=strip_position_tags(parse_result.full_text),
                chunks=clean_chunks,
                metadata=result_metadata,
            )
            logger.info(
                "DeepDoc 哨兵重切完成",
                filename=Path(file_path).name,
                chunk_count=len(clean_chunks),
                structure_count=len(chunk_structure),
                encoded_entries=encoded_count,
                reading_order_count=len(reading_order),
            )
            return parse_result

        logger.info(
            "默认解析开始",
            filename=Path(file_path).name,
            file_type=file_type,
            parsing_strategy=parsing_strategy,
            splitting_strategy=splitting_config.get("strategy", "recursive"),
            splitting_chunk_size=splitting_config.get("chunk_size", 1000),
            splitting_chunk_overlap=splitting_config.get("chunk_overlap", 100),
        )
        # 质量报告收集窗口：default 路径与 deepdoc 的 metadata["quality"] 同构
        # 出账。收集范围受限：reader 实际解析在共享线程池工作线程执行，线程限
        # 定 filter 收不到其内部告警；本 async 体（事件循环线程）的告警——
        # 如扫描件「文字层为空」提示——可收集。
        default_started = time.perf_counter()
        with collect_warnings() as default_warnings:
            full_text = await self.read_full_text(
                file_path,
            )
            split_items = await self.split_text_items(
                full_text,
                strategy=str(splitting_config.get("strategy", "recursive")),
                **extract_splitting_params(splitting_config),
            )
        chunks = [t for t, _meta in split_items]
        # 关系元数据（sentence_window/parent_child 的窗口参数/父子槽位）按位对齐
        # 透传；仅当存在非空 meta 时才写键——存量策略保持 metadata 形状不变。
        # document_pipeline 按 index 对齐组装 prechunked_items，条数与 chunks 恒相等。
        chunk_structure_meta = [m for _t, m in split_items]
        result_metadata = {
            "parser": "default",
            "file_type": file_type,
            "split_strategy": str(splitting_config.get("strategy", "recursive")),
            "quality": build_quality_metadata("default", default_warnings, default_started),
        }
        if any(chunk_structure_meta):
            result_metadata["chunk_structure_meta"] = chunk_structure_meta
        logger.info(
            "默认解析完成",
            filename=Path(file_path).name,
            char_count=len(full_text),
            chunk_count=len(chunks),
            split_strategy=str(splitting_config.get("strategy", "recursive")),
        )
        return DeepDocParseResult(
            full_text=full_text,
            chunks=chunks,
            metadata=result_metadata,
        )

    async def load_with_strategy(self, file_path: str | Path, strategy: str | None = 'recursive',
                          **kwargs) -> list[dict[str, str]]:
        """按指定策略构建切分器并加载切分文档（兼容旧调用的组合入口）。

        Args:
            file_path: 文件路径。
            strategy: 切分策略（'recursive' / 'semantic' / 'fixed_size' / 'markdown' / 'delimiter' / 'sentence_window' / 'parent_child' / 'hierarchical'）。
            **kwargs: 策略特定参数，逐策略透传。

        Returns:
            切分后的文档块列表。

        Raises:
            ValueError: 策略名未注册。
        """
        splitter = build_splitter(
            strategy,
            kwargs,
            SplitterDeps(embedding_client=self.embedding_client),
        )

        loader = DocumentLoader(splitter=splitter, embedding_client=self.embedding_client)  # 使用共享的客户端实例
        return await loader.load_and_split(file_path)

    async def process_directory(self, directory_path: str | Path, strategy: str | None = 'recursive',
                         **kwargs) -> list[dict[str, str]]:
        """遍历目录下所有已注册扩展名的文件，逐个加载并切分。

        Args:
            directory_path: 目录路径。
            strategy: 切分策略。
            **kwargs: 策略特定参数，逐策略透传。

        Returns:
            全部文件的切分结果合并列表。

        Raises:
            ValueError: 路径不是目录。
        """
        directory_path = Path(directory_path)
        if not directory_path.is_dir():
            raise ValueError(f"Path is not a directory: {directory_path}")
        
        # 获取所有支持的文件
        supported_extensions = [f"*.{ext}" for ext in (await DocumentLoader.get_supported_formats())]
        files = []
        for pattern in supported_extensions:
            files.extend(directory_path.glob(pattern))
        
        all_documents = []
        for file_path in files:
            logger.info("正在处理文件", filename=file_path.name)
            documents = await self.load_with_strategy(file_path, strategy, **kwargs)
            all_documents.extend(documents)
        
        return all_documents


# 初始化默认的读取器和切分器注册
DocumentRegistry.register_reader('pdf', PDFReader)
DocumentRegistry.register_reader('docx', DocxReader)
DocumentRegistry.register_reader('txt', TxtReader)
DocumentRegistry.register_reader('html', HTMLReader)
DocumentRegistry.register_reader('md', MarkdownReader)
DocumentRegistry.register_reader('markdown', MarkdownReader)
DocumentRegistry.register_reader('csv', TxtReader)
DocumentRegistry.register_reader('json', TxtReader)

DocumentRegistry.register_splitter('recursive', RecursiveCharacterSplitter)
DocumentRegistry.register_splitter('semantic', SemanticSplitter)
DocumentRegistry.register_splitter('fixed_size', FixedSizeSplitter)
DocumentRegistry.register_splitter('markdown', MarkdownSplitter)
DocumentRegistry.register_splitter('delimiter', DelimiterSplitter)
DocumentRegistry.register_splitter('sentence_window', SentenceWindowSplitter)
DocumentRegistry.register_splitter('parent_child', ParentChildSplitter)
DocumentRegistry.register_splitter('hierarchical', HierarchicalSplitter)
