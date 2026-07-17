import asyncio
from typing import List, Dict, Optional, Union, Type
from pathlib import Path
from novamind.shared.knowledge.document_processing.readers.base_reader import BaseReader
from novamind.shared.knowledge.document_processing.readers.pdf_reader import PDFReader
from novamind.shared.knowledge.document_processing.readers.docx_reader import DocxReader
from novamind.shared.knowledge.document_processing.readers.txt_reader import TxtReader
from novamind.shared.knowledge.document_processing.readers.html_reader import HTMLReader
from novamind.shared.knowledge.document_processing.readers.md_reader import MarkdownReader
from novamind.shared.knowledge.document_processing.splitters.base_splitter import BaseSplitter
from novamind.shared.knowledge.document_processing.splitters.recursive_splitter import RecursiveCharacterSplitter
from novamind.shared.knowledge.document_processing.splitters.semantic_splitter import SemanticSplitter
from novamind.shared.knowledge.document_processing.splitters.fixed_size_splitter import FixedSizeSplitter
from novamind.shared.knowledge.document_processing.splitters.markdown_splitter import MarkdownSplitter
from novamind.shared.knowledge.integrations.deepdoc import DeepDocEngine, DeepDocParser, DeepDocParseResult, strip_position_tags
from novamind.shared.ai_models.base_model import BaseEmbedding
from novamind.core.middleware.structured_logging import get_logger

logger = get_logger(__name__)


class DocumentRegistry:
    """文档组件注册器，用于统一管理文档读取器和切分器"""
    
    # 注册表：文档读取器
    _readers_registry: Dict[str, Type[BaseReader]] = {}
    
    # 注册表：文档切分器
    _splitters_registry: Dict[str, Type[BaseSplitter]] = {}

    @classmethod
    def register_reader(cls, extension: str, reader_class: Type[BaseReader] = None):
        """
        注册文档读取器的装饰器/直接调用函数
        可以作为装饰器使用 @register_reader('ext') 或直接调用 register_reader('ext', ReaderClass)
        """
        def decorator(actual_reader_class: Type[BaseReader]):
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
        """注销文档读取器"""
        if extension in cls._readers_registry:
            del cls._readers_registry[extension]

    @classmethod
    def register_splitter(cls, name: str, splitter_class: Type[BaseSplitter] = None):
        """
        注册文档切分器的装饰器/直接调用函数
        可以作为装饰器使用 @register_splitter('name') 或直接调用 register_splitter('name', SplitterClass)
        """
        def decorator(actual_splitter_class: Type[BaseSplitter]):
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
        """注销文档切分器"""
        if name in cls._splitters_registry:
            del cls._splitters_registry[name]

    @classmethod
    def get_reader_class(cls, extension: str) -> Optional[Type[BaseReader]]:
        """获取指定扩展名的读取器类"""
        return cls._readers_registry.get(extension)

    @classmethod
    def get_splitter_class(cls, name: str) -> Optional[Type[BaseSplitter]]:
        """获取指定名称的切分器类"""
        return cls._splitters_registry.get(name)

    @classmethod
    def get_supported_formats(cls) -> List[str]:
        """获取支持的文件格式"""
        return list(cls._readers_registry.keys())

    @classmethod
    def get_available_strategies(cls) -> List[str]:
        """获取可用的切分策略"""
        return list(cls._splitters_registry.keys())


class DocumentLoader:
    """文档加载器，负责根据文件类型选择合适的读取器并进行切分"""

    def __init__(self, splitter: BaseSplitter, 
                 embedding_client: BaseEmbedding):
        """
        初始化文档加载器
        :param splitter: 文档切分器，如果不提供，在load_and_split时会根据文件类型设置默认切分器
        :param embedding_client: 嵌入模型客户端，用于语义切分
        """
        self.splitter = splitter
        self.embedding_client = embedding_client 
        
        # 初始化各种读取器（从注册表获取）
        self.readers = {}
        for ext, reader_class in DocumentRegistry._readers_registry.items():
            self.readers[ext] = reader_class()

    async def _get_default_splitter_for_extension(self, extension: str) -> BaseSplitter:
        """
        根据文件扩展名获取默认的切分器
        :param extension: 文件扩展名
        :return: 默认切分器实例
        """
        if extension == 'pdf':
            # PDF通常使用较小的块大小
            return RecursiveCharacterSplitter(chunk_size=400, chunk_overlap=50)
        elif extension in ('md', 'markdown'):
            # Markdown使用专门的切分器
            return MarkdownSplitter()
        else:
            # 其他文件类型使用默认的递归字符切分器
            return RecursiveCharacterSplitter()

    async def load_and_split(self, file_path: Union[str, Path]) -> List[Dict[str, str]]:
        """
        加载并切分文档
        :param file_path: 文件路径
        :return: 切分后的文档块列表
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
        
        # 如果没有指定切分器，根据文件类型设置默认切分器
        if self.splitter is None:
            self.splitter = await self._get_default_splitter_for_extension(extension)
        
        # 切分文档
        split_documents = await self.splitter.split(documents)
        
        return split_documents

    async def load_multiple_files(self, file_paths: List[Union[str, Path]]) -> List[Dict[str, str]]:
        """
        加载并切分多个文件
        :param file_paths: 文件路径列表
        :return: 切分后的文档块列表
        """
        all_documents = []
        for file_path in file_paths:
            documents = await self.load_and_split(file_path)
            all_documents.extend(documents)
        
        return all_documents

    @staticmethod
    async def get_supported_formats() -> List[str]:
        """
        获取支持的文件格式
        :return: 支持的文件格式列表
        """
        return DocumentRegistry.get_supported_formats()


class DocumentProcessor:
    """文档处理器，提供高级文档处理功能

    支持两阶段处理：
    1. read_full_text() — 读取文件并返回全文（reader-only）
    2. split_text() — 对文本进行切分（splitter-only）
    3. load_with_strategy() — 一键读+切（为兼容旧调用保留）
    """

    def __init__(self, embedding_client: Optional[BaseEmbedding] = None):
        self.embedding_client = embedding_client
        self._deepdoc_parser = DeepDocParser()
        self._deepdoc_engine = DeepDocEngine(parser=self._deepdoc_parser)
        # 初始化各种读取器（从注册表获取）
        self._readers: Dict[str, BaseReader] = {}
        for ext, reader_class in DocumentRegistry._readers_registry.items():
            self._readers[ext] = reader_class()

    async def read_full_text(
        self,
        file_path: Union[str, Path],
        ocr_enabled: bool = False,
    ) -> str:
        """
        Reader-only：读取文件，返回合并后的全文内容（不做切分）

        支持的文件类型由 DocumentRegistry 注册表决定：
        pdf, docx, txt, html, md, markdown 等。

        :param file_path: 文件路径
        :return: 文件的完整文本内容
        :raises ValueError: 不支持的文件类型
        :raises FileNotFoundError: 文件不存在
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
        try:
            import fitz
        except Exception:
            logger.warning("PDF OCR fallback unavailable", filename=file_path.name, reason="fitz_not_installed")
            return ""

        page_texts: List[str] = []
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
    ) -> List[str]:
        """
        Splitter-only：对纯文本进行切分，返回 chunk 文本列表

        不读取文件，只做切分。

        :param text: 要切分的全文文本
        :param strategy: 切分策略 ('recursive', 'semantic', 'fixed_size', 'markdown')
        :param kwargs: 策略特定的参数
        :return: 切分后的文本块列表（纯文本，非 dict）
        :raises ValueError: 不支持的切分策略
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
        file_path: Union[str, Path],
        parsing_config: Optional[Dict[str, object]] = None,
        splitting_config: Optional[Dict[str, object]] = None,
    ) -> tuple[str, List[str]]:
        result = await self.parse_document_result(
            file_path,
            parsing_config=parsing_config,
            splitting_config=splitting_config,
        )
        return result.full_text, result.chunks

    async def parse_document_result(
        self,
        file_path: Union[str, Path],
        parsing_config: Optional[Dict[str, object]] = None,
        splitting_config: Optional[Dict[str, object]] = None,
    ) -> DeepDocParseResult:
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
            # full_text 在 layout/vision 模式下带有 ``@@<page>\t<x0>\t<x1>\t<top>\t<bottom>##``
            # 版面坐标标记，重新切分前必须剥离，否则坐标会泄漏进 chunk 正文 / embedding。
            # 位置信息已由 parser 单独写入结构化 chunk 的 metadata（position_tag/source_id），
            # 剥离 full_text 中的标记不影响位置溯源。
            clean_full_text = strip_position_tags(parse_result.full_text)
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
            rechunked = await self.split_text(
                clean_full_text,
                strategy=split_strategy,
                chunk_size=splitting_config.get("chunk_size", 1000),
                chunk_overlap=splitting_config.get("chunk_overlap", 100),
                min_chunk_size=splitting_config.get("min_chunk_size", 500),
                max_chunk_size=splitting_config.get("max_chunk_size", 2000),
                similarity_threshold=splitting_config.get("similarity_threshold", 0.7),
                batch_size=splitting_config.get("batch_size", 20),
            )
            parse_result = DeepDocParseResult(
                full_text=clean_full_text,
                chunks=rechunked,
                metadata={
                    **parse_result.metadata,
                    "split_strategy": split_strategy,
                    "deepdoc_rechunked": True,
                },
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

    async def load_with_strategy(self, file_path: Union[str, Path], strategy: Optional[str] = 'recursive',
                          **kwargs) -> List[Dict[str, str]]:
        """
        使用指定策略加载文档
        :param file_path: 文件路径
        :param strategy: 切分策略 ('recursive', 'semantic', 'fixed_size', 'markdown')
        :param kwargs: 策略特定的参数
        :return: 切分后的文档块列表
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

    async def process_directory(self, directory_path: Union[str, Path], strategy: Optional[str] = 'recursive',
                         **kwargs) -> List[Dict[str, str]]:
        """
        处理目录中的所有支持的文档
        :param directory_path: 目录路径
        :param strategy: 切分策略
        :param kwargs: 策略特定的参数
        :return: 切分后的文档块列表
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
