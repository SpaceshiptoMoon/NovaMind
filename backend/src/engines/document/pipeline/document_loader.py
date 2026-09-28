"""文档解析管道：DocumentLoader（按扩展名路由解析器） + DocumentProcessor（编排解析 / 切分 / 元数据） + DocumentRegistry（解析器注册表）。"""
import asyncio
from pathlib import Path

from novamind.engines.document.integrations.deepdoc import (
    DeepDocEngine,
    DeepDocParser,
    DeepDocParseResult,
    strip_position_tags,
)
from novamind.engines.document.pipeline.tagged_rechunk import (
    build_tagged_text,
    rechunk_with_structure,
)
from novamind.engines.document.splitters.base_splitter import BaseSplitter
from novamind.engines.document.splitters.fixed_size_splitter import FixedSizeSplitter
from novamind.engines.document.splitters.markdown_splitter import MarkdownSplitter
from novamind.engines.document.splitters.recursive_splitter import RecursiveCharacterSplitter
from novamind.engines.document.splitters.semantic_splitter import SemanticSplitter
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
            # PDF通常使用较小的块大小
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
        ocr_enabled: bool = False,
    ) -> str:
        """Reader-only：读取文件并合并为全文，不做切分。

        支持的文件类型由 DocumentRegistry 注册表决定：
        pdf, docx, txt, html, md, markdown 等。

        Args:
            file_path: 文件路径。

        Returns:
            文件的完整文本内容；文字层为空且 ocr_enabled 时的 PDF 走 OCR 兜底。

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

        if not full_text.strip() and ocr_enabled and extension == "pdf":
            full_text = await self._ocr_pdf_text(file_path)


        logger.info(
            "文档全文读取完成",
            filename=file_path.name,
            extension=extension,
            paragraphs=len(documents),
            char_count=len(full_text),
            ocr_enabled=ocr_enabled,
        )
        return full_text

    async def _ocr_pdf_text(self, file_path: Path) -> str:
        """Fallback OCR for scanned PDFs when text extraction returns empty."""
        return await asyncio.to_thread(self._ocr_pdf_text_sync, file_path)

    @staticmethod
    def _ocr_pdf_text_sync(file_path: Path) -> str:
        """扫描版 PDF 的 OCR 兜底（fitz + Tesseract）；缺 Tesseract 抛错，页级失败记 WARNING 跳过。"""
        try:
            import fitz
        except Exception:
            logger.warning("PDF OCR fallback unavailable", filename=file_path.name, reason="fitz_not_installed")
            return ""

        # fitz.get_textpage_ocr() 底层依赖系统级 Tesseract 二进制。此前 Tesseract 缺失时
        # 每页 OCR 抛异常被下方页循环的 try/except 静默吞成空串，扫描版 PDF 入库为空且无报错。
        # 这里前置检查并把缺失上抛为 RuntimeError，让任务 FAILED 且消息可见。
        import shutil
        if not shutil.which("tesseract"):
            raise RuntimeError(
                "PDF OCR 需要 Tesseract 系统二进制，当前未安装在 PATH；"
                "无法对扫描版 PDF 做 OCR。请安装 Tesseract 或在 KB 配置中关闭 ocr_enabled"
            )

        page_texts: list[str] = []
        try:
            with fitz.open(file_path) as pdf:
                for page in pdf:
                    try:
                        textpage = page.get_textpage_ocr()
                        text = page.get_text(textpage=textpage).strip()
                    except Exception as exc:
                        logger.warning(
                            "PDF OCR page failed",
                            filename=file_path.name,
                            page_number=page.number + 1,
                            error=str(exc),
                        )
                        text = ""
                    if text:
                        page_texts.append(text)
        except Exception as exc:
            logger.warning("PDF OCR fallback failed", filename=file_path.name, error=str(exc))
            return ""

        return "\n\n".join(page_texts)

    async def split_text(
        self,
        text: str,
        strategy: str = 'recursive',
        **kwargs,
    ) -> list[str]:
        """Splitter-only：对纯文本按指定策略切分，返回 chunk 文本列表。

        不读取文件，只做切分。

        Args:
            text: 要切分的全文文本。
            strategy: 切分策略（'recursive' / 'semantic' / 'fixed_size' / 'markdown'）。
            **kwargs: 策略特定参数（chunk_size / similarity_threshold 等），逐策略透传。

        Returns:
            切分后的文本块列表（纯文本，非 dict）。

        Raises:
            ValueError: 策略名未注册。
        """
        # 从注册表中获取切分器类
        splitter_class = DocumentRegistry.get_splitter_class(strategy)
        if splitter_class is None:
            raise ValueError(
                f"Unknown strategy: {strategy}. "
                f"Supported: {DocumentRegistry.get_available_strategies()}"
            )

        # 根据不同策略创建实例
        if strategy == 'recursive':
            chunk_size = kwargs.get('chunk_size', 500)
            chunk_overlap = kwargs.get('chunk_overlap', 50)
            min_chunk_size = kwargs.get('min_chunk_size', 50)
            splitter = splitter_class(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chunk_size=min_chunk_size,
            )
        elif strategy == 'semantic':
            max_chunk_size = kwargs.get('max_chunk_size', 1000)
            similarity_threshold = kwargs.get('similarity_threshold', 0.7)
            batch_size = kwargs.get('batch_size', 20)
            splitter = splitter_class(
                embedding_client=self.embedding_client,
                max_chunk_size=max_chunk_size,
                similarity_threshold=similarity_threshold,
                batch_size=batch_size,
            )
        elif strategy == 'fixed_size':
            chunk_size = kwargs.get('chunk_size', 500)
            chunk_overlap = kwargs.get('chunk_overlap', 0)
            splitter = splitter_class(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
        elif strategy == 'markdown':
            max_chunk_size = kwargs.get('max_chunk_size', 1000)
            min_chunk_size = kwargs.get('min_chunk_size', 50)
            splitter = splitter_class(
                max_chunk_size=max_chunk_size,
                min_chunk_size=min_chunk_size,
            )
        else:
            splitter = splitter_class(**kwargs)

        # 对全文进行切分 — 将文本包装为单页文档
        documents = [{"text": text, "content": text, "source": "", "metadata": {}}]
        chunks = await splitter.split(documents)
        chunk_texts = [
            chunk.get("content") or chunk.get("text", "")
            for chunk in chunks
            if (chunk.get("content") or chunk.get("text", "")).strip()
        ]

        # 提取纯文本内容

        logger.info(
            "文本切分完成",
            strategy=strategy,
            char_count=len(text),
            chunk_count=len(chunk_texts),
        )
        return chunk_texts

    async def parse_document(
        self,
        file_path: str | Path,
        parsing_config: dict[str, object] | None = None,
        splitting_config: dict[str, object] | None = None,
    ) -> tuple[str, list[str]]:
        """解析文档并切分，返回 (full_text, chunks) 二元组；完整元数据请用 parse_document_result。

        Args:
            file_path: 文件路径。
            parsing_config: 解析配置（strategy / deepdoc_parser_id / ocr_enabled 等）。
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
            parsing_config: 解析配置（strategy / parser_id / pdf_mode / ocr_enabled 等）。
            splitting_config: 切分配置（strategy/chunk_size 等，无 embedding 时回退）。

        Returns:
            DeepDocParseResult：full_text 为无坐标标记全文，chunks 按配置重切，
            metadata 含 split_strategy / chunk_structure 等。

        Raises:
            ValueError: 文件类型不支持或切分策略名未注册。
        """
        parsing_config = dict(parsing_config or {})
        splitting_config = dict(splitting_config or {})
        parsing_strategy = str(parsing_config.get("strategy", "default"))
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
            if split_strategy not in ("recursive", "fixed_size", "markdown"):
                split_strategy = "recursive"
            tagged_rechunked = await self.split_text(
                rechunk_source_text,
                strategy=split_strategy,
                chunk_size=splitting_config.get("chunk_size", 1000),
                chunk_overlap=splitting_config.get("chunk_overlap", 100),
                min_chunk_size=splitting_config.get("min_chunk_size", 500),
                max_chunk_size=splitting_config.get("max_chunk_size", 2000),
                similarity_threshold=splitting_config.get("similarity_threshold", 0.7),
                batch_size=splitting_config.get("batch_size", 20),
            )
            clean_chunks, chunk_structure, structure_source = rechunk_with_structure(
                tagged_rechunked, sentinel_map
            )
            parse_result = DeepDocParseResult(
                full_text=strip_position_tags(parse_result.full_text),
                chunks=clean_chunks,
                metadata={
                    **parse_result.metadata,
                    "split_strategy": split_strategy,
                    "deepdoc_rechunked": True,
                    "chunk_structure": chunk_structure,
                    "chunk_structure_source": structure_source,
                    "tagged_rechunk_encoded_entries": encoded_count,
                    "tagged_rechunk_degraded_entries": degraded_count,
                },
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
            ocr_enabled=parsing_config.get("ocr_enabled", False),
            splitting_strategy=splitting_config.get("strategy", "recursive"),
            splitting_chunk_size=splitting_config.get("chunk_size", 1000),
            splitting_chunk_overlap=splitting_config.get("chunk_overlap", 100),
        )
        full_text = await self.read_full_text(
            file_path,
            ocr_enabled=bool(parsing_config.get("ocr_enabled", False)),
        )
        chunks = await self.split_text(
            full_text,
            strategy=str(splitting_config.get("strategy", "recursive")),
            chunk_size=splitting_config.get("chunk_size", 1000),
            chunk_overlap=splitting_config.get("chunk_overlap", 100),
            min_chunk_size=splitting_config.get("min_chunk_size", 500),
            max_chunk_size=splitting_config.get("max_chunk_size", 2000),
            similarity_threshold=splitting_config.get("similarity_threshold", 0.7),
            batch_size=splitting_config.get("batch_size", 20),
        )
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
            metadata={
                "parser": "default",
                "file_type": file_type,
                "split_strategy": str(splitting_config.get("strategy", "recursive")),
            },
        )

    async def load_with_strategy(self, file_path: str | Path, strategy: str | None = 'recursive',
                          **kwargs) -> list[dict[str, str]]:
        """按指定策略构建切分器并加载切分文档（兼容旧调用的组合入口）。

        Args:
            file_path: 文件路径。
            strategy: 切分策略（'recursive' / 'semantic' / 'fixed_size' / 'markdown'）。
            **kwargs: 策略特定参数，逐策略透传。

        Returns:
            切分后的文档块列表。

        Raises:
            ValueError: 策略名未注册。
        """
        # 从注册表中获取切分器类
        splitter_class = DocumentRegistry.get_splitter_class(strategy)
        if splitter_class is None:
            raise ValueError(f"Unknown strategy: {strategy}. Supported: {DocumentRegistry.get_available_strategies()}")
        
        # 根据不同策略创建实例
        if strategy == 'recursive':
            chunk_size = kwargs.get('chunk_size', 500)
            chunk_overlap = kwargs.get('chunk_overlap', 50)
            min_chunk_size = kwargs.get('min_chunk_size', 50)
            splitter = splitter_class(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                min_chunk_size=min_chunk_size,
            )
        elif strategy == 'semantic':
            max_chunk_size = kwargs.get('max_chunk_size', 1000)
            similarity_threshold = kwargs.get('similarity_threshold', 0.7)
            batch_size = kwargs.get('batch_size', 20)  # 批处理大小
            splitter = splitter_class(
                embedding_client=self.embedding_client,  # 使用共享的客户端实例
                max_chunk_size=max_chunk_size,
                similarity_threshold=similarity_threshold,
                batch_size=batch_size
            )
        elif strategy == 'fixed_size':
            chunk_size = kwargs.get('chunk_size', 500)
            chunk_overlap = kwargs.get('chunk_overlap', 0)
            splitter = splitter_class(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
        elif strategy == 'markdown':
            max_chunk_size = kwargs.get('max_chunk_size', 1000)
            min_chunk_size = kwargs.get('min_chunk_size', 50)
            splitter = splitter_class(
                max_chunk_size=max_chunk_size,
                min_chunk_size=min_chunk_size
            )
        else:
            # 对于其他可能注册的切分器，尝试通用初始化方法
            splitter = splitter_class(**kwargs)
        
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
