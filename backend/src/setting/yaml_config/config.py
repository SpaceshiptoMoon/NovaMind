"""
配置数据类
提供类型安全的配置访问
支持 MinIO、Elasticsearch
"""
from dataclasses import dataclass, field
from typing import Optional, List
from urllib.parse import quote_plus


# ==================== 存储配置 ====================

@dataclass
class MinioConfig:
    """MinIO 对象存储配置"""
    endpoint: str = "localhost:9000"
    access_key: str = "admin123"
    secret_key: str = "admin123"
    secure: bool = False
    region: str = "us-east-1"
    bucket_name: str = "knowledge-base"

@dataclass
class ElasticsearchConfig:
    """Elasticsearch 配置"""
    hosts: List[str] = field(default_factory=lambda: ["http://localhost:9200"])
    username: Optional[str] = None
    password: Optional[str] = None
    index_prefix: str = "kb"
    default_embedding_dim: int = 1024
    analyzer: str = "ik_max_word"
    verify_certs: bool = False
    ca_certs: Optional[str] = None


@dataclass
class VectorDbConfig:
    """向量数据库配置"""
    type: str = "elasticsearch"  # elasticsearch / milvus / chroma


# ==================== 知识库配置 ====================

@dataclass
class SplittingConfig:
    """文档切分配置"""
    strategy: str = "recursive"  # fixed / recursive / semantic / sentence
    chunk_size: int = 500
    chunk_overlap: int = 50
    separator: str = "\n\n"
    min_chunk_size: int = 100
    max_chunk_size: int = 2000


@dataclass
class ParsingConfig:
    """文档解析配置"""
    extract_images: bool = False
    extract_tables: bool = True
    ocr_enabled: bool = False
    preserve_structure: bool = True
    encoding: str = "utf-8"


@dataclass
class HybridSearchConfig:
    """混合检索配置"""
    enabled: bool = True
    vector_weight: float = 0.7
    text_weight: float = 0.3


@dataclass
class RetrievalConfig:
    """检索配置"""
    top_k: int = 5
    score_threshold: float = 0.7
    rerank_enabled: bool = False
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)


@dataclass
class KnowledgeBaseConfig:
    """知识库配置"""
    splitting: SplittingConfig = field(default_factory=SplittingConfig)
    parsing: ParsingConfig = field(default_factory=ParsingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)


# ==================== 基础配置 ====================

@dataclass
class DatabaseConfig:
    """MySQL 数据库配置"""
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "novamind_db"
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600
    pool_pre_ping: bool = True
    ssl: bool = False  # 是否启用 SSL 连接

    @property
    def url(self) -> str:
        """生成数据库连接 URL"""
        return f"mysql+aiomysql://{self.user}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.database}"


@dataclass
class RedisConfig:
    """Redis 缓存配置"""
    enabled: bool = False
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 10
    sentinel_hosts: str = ""       # 哨兵地址，逗号分隔（如 "host1:26379,host2:26379"）
    sentinel_master: str = "mymaster"  # 哨兵监视的主节点名称
    cluster_hosts: str = ""        # 集群地址，逗号分隔（如 "host1:6379,host2:6379"）


@dataclass
class LLMConfig:
    """LLM 压缩配置（连接凭证已迁移到数据库 user_model_configs）"""
    # 压缩配置（对应 qa_session_configs 表字段）
    compression_strategy: str = "summary"
    compression_threshold: int = 3000
    keep_recent_messages: int = 2
    compression_target_tokens: int = 500
    enable_compression: bool = True
    custom_summary_prompt: Optional[str] = None


@dataclass
class RerankSettings:
    """Rerank 重排序配置（连接凭证已迁移到数据库）"""
    enabled: bool = False
    default_top_k: int = 3


@dataclass
class AdminConfig:
    """管理员账户配置"""
    username: str = "admin"
    email: str = "admin@example.com"
    password: str = ""
    phone: Optional[str] = None
    create_on_startup: bool = True
    reset_password_if_exists: bool = False


@dataclass
class SecurityConfig:
    """安全配置"""
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    encryption_key: str = ""


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "INFO"
    format: str = "json"


@dataclass
class CacheConfig:
    """缓存配置"""
    knowledge_space_enabled: bool = True
    knowledge_space_expire_hours: int = 1
    knowledge_space_similarity_threshold: float = 0.95
    session_enabled: bool = True
    session_expire_hours: int = 24
    vector_search_enabled: bool = True
    search_result_ttl: int = 3600


# ==================== 外部搜索配置 ====================

@dataclass
class TavilyConfig:
    """Tavily 搜索配置"""
    api_key: str = ""
    max_results: int = 10
    search_depth: str = "basic"
    timeout: int = 30


@dataclass
class SerpAPIConfig:
    """SerpAPI 搜索配置"""
    api_key: str = ""
    max_results: int = 10
    timeout: int = 30
    engine: str = "google"


@dataclass
class DuckDuckGoConfig:
    """DuckDuckGo 搜索配置"""
    max_results: int = 10
    timeout: int = 15


@dataclass
class ExternalSearchConfig:
    """外部搜索配置"""
    default_provider: str = "duckduckgo"
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    serpapi: SerpAPIConfig = field(default_factory=SerpAPIConfig)
    duckduckgo: DuckDuckGoConfig = field(default_factory=DuckDuckGoConfig)


# ==================== 深度研究配置 ====================

@dataclass
class DeepResearchModeConfig:
    """单个研究模式的配置"""
    depth: int = 3
    iterations: int = 5


@dataclass
class DeepResearchModesConfig:
    """研究模式配置集合"""
    quick: DeepResearchModeConfig = field(default_factory=lambda: DeepResearchModeConfig(depth=2, iterations=3))
    standard: DeepResearchModeConfig = field(default_factory=lambda: DeepResearchModeConfig(depth=3, iterations=5))
    deep: DeepResearchModeConfig = field(default_factory=lambda: DeepResearchModeConfig(depth=5, iterations=7))


@dataclass
class DeepResearchConfig:
    """深度研究配置"""
    modes: DeepResearchModesConfig = field(default_factory=DeepResearchModesConfig)
    cache_results: bool = True
    cache_ttl_hours: int = 24


@dataclass
class ProjectConfig:
    """项目信息配置"""
    name: str = "novamind"
    version: str = "0.1.0"
    description: str = "novamind - 智能知识库管理系统"


@dataclass
class TaskQueueConfig:
    """任务队列配置（arq）"""
    max_jobs: int = 3
    job_timeout: int = 1800
    max_tries: int = 3
    retry_base_delay: int = 60
    queue_name: str = "arq:queue"


@dataclass
class AgentConfig:
    """Agent 智能体配置"""
    max_tool_calls_per_turn: int = 10
    default_max_tokens: int = 4096
    default_context_window: int = 32768
    default_temperature: float = 0.7
    max_context_tokens: int = 8000
    mcp_connection_timeout: int = 30
    tool_result_max_chars: int = 50_000
    tool_result_preview_threshold: int = 10_000
    tool_result_preview_chars: int = 1_500
    tool_result_turn_budget: int = 100_000


@dataclass
class AppConfig:
    """应用完整配置"""
    environment: str = "development"
    debug: bool = False
    project: ProjectConfig = field(default_factory=ProjectConfig)

    # 存储配置
    minio: MinioConfig = field(default_factory=MinioConfig)
    elasticsearch: ElasticsearchConfig = field(default_factory=ElasticsearchConfig)
    vector_db: VectorDbConfig = field(default_factory=VectorDbConfig)

    # 数据库配置
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)

    # AI 模型配置
    llm: LLMConfig = field(default_factory=LLMConfig)
    rerank: RerankSettings = field(default_factory=RerankSettings)

    # 知识库配置（新增）
    knowledge_base: KnowledgeBaseConfig = field(default_factory=KnowledgeBaseConfig)

    # 管理员和安全配置
    admin: AdminConfig = field(default_factory=AdminConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # 日志和缓存配置
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    # 外部搜索配置
    external_search: ExternalSearchConfig = field(default_factory=ExternalSearchConfig)

    # 深度研究配置
    deep_research: DeepResearchConfig = field(default_factory=DeepResearchConfig)

    # Agent 智能体配置
    agent: AgentConfig = field(default_factory=AgentConfig)

    # 任务队列配置
    task_queue: TaskQueueConfig = field(default_factory=TaskQueueConfig)

    # CORS 配置
    cors_origins: str = "*"
