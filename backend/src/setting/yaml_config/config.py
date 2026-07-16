from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus


@dataclass
class MinioConfig:
    endpoint: str = "localhost:9000"
    public_endpoint: Optional[str] = None
    access_key: str = "***REMOVED***"
    secret_key: str = "***REMOVED***"
    secure: bool = False
    region: str = "us-east-1"
    bucket_name: str = "knowledge-base"


@dataclass
class ElasticsearchConfig:
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
    type: str = "elasticsearch"


@dataclass
class SplittingConfig:
    strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50
    separator: str = "\n\n"
    min_chunk_size: int = 100
    max_chunk_size: int = 2000


@dataclass
class ParsingConfig:
    extract_images: bool = False
    extract_tables: bool = True
    ocr_enabled: bool = False
    preserve_structure: bool = True
    encoding: str = "utf-8"
    vlm_description_enabled: bool = False


@dataclass
class HybridSearchConfig:
    enabled: bool = True
    vector_weight: float = 0.7
    text_weight: float = 0.3


@dataclass
class RetrievalConfig:
    top_k: int = 5
    score_threshold: float = 0.7
    rerank_enabled: bool = False
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)


@dataclass
class KnowledgeBaseConfig:
    splitting: SplittingConfig = field(default_factory=SplittingConfig)
    parsing: ParsingConfig = field(default_factory=ParsingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)


@dataclass
class DatabaseConfig:
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
    ssl: bool = False

    @property
    def url(self) -> str:
        return (
            f"mysql+aiomysql://{self.user}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )


@dataclass
class RedisConfig:
    enabled: bool = False
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 10
    sentinel_hosts: str = ""
    sentinel_master: str = "mymaster"
    cluster_hosts: str = ""


@dataclass
class LLMConfig:
    compression_strategy: str = "summary"
    compression_threshold: int = 70000
    keep_recent_messages: int = 6
    compression_target_tokens: int = 2000
    enable_compression: bool = True
    custom_summary_prompt: Optional[str] = None


@dataclass
class RerankSettings:
    enabled: bool = False
    default_top_k: int = 3


@dataclass
class AdminConfig:
    username: str = "admin"
    email: str = "admin@example.com"
    password: str = ""
    phone: Optional[str] = None
    create_on_startup: bool = True
    reset_password_if_exists: bool = False


@dataclass
class SecurityConfig:
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    encryption_key: str = ""


@dataclass
class TavilyConfig:
    api_key: str = ""
    max_results: int = 10
    search_depth: str = "basic"
    timeout: int = 30


@dataclass
class SerpAPIConfig:
    api_key: str = ""
    max_results: int = 10
    timeout: int = 30
    engine: str = "google"


@dataclass
class DuckDuckGoConfig:
    max_results: int = 10
    timeout: int = 15


@dataclass
class ExternalSearchConfig:
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    serpapi: SerpAPIConfig = field(default_factory=SerpAPIConfig)
    duckduckgo: DuckDuckGoConfig = field(default_factory=DuckDuckGoConfig)


@dataclass
class DeepResearchModeConfig:
    depth: int = 3
    iterations: int = 5


@dataclass
class DeepResearchModesConfig:
    quick: DeepResearchModeConfig = field(
        default_factory=lambda: DeepResearchModeConfig(depth=2, iterations=3)
    )
    standard: DeepResearchModeConfig = field(
        default_factory=lambda: DeepResearchModeConfig(depth=3, iterations=5)
    )
    deep: DeepResearchModeConfig = field(
        default_factory=lambda: DeepResearchModeConfig(depth=5, iterations=7)
    )


@dataclass
class DeepResearchConfig:
    modes: DeepResearchModesConfig = field(default_factory=DeepResearchModesConfig)


@dataclass
class ProjectConfig:
    name: str = "novamind"
    version: str = "0.1.0"
    description: str = "novamind backend"


@dataclass
class TaskQueueConfig:
    max_jobs: int = 3
    job_timeout: int = 1800
    max_tries: int = 3
    retry_base_delay: int = 60
    queue_name: str = "arq:queue"


@dataclass
class SmtpConfig:
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    use_tls: bool = True


@dataclass
class AppConfig:
    environment: str = "development"
    project: ProjectConfig = field(default_factory=ProjectConfig)
    minio: MinioConfig = field(default_factory=MinioConfig)
    elasticsearch: ElasticsearchConfig = field(default_factory=ElasticsearchConfig)
    vector_db: VectorDbConfig = field(default_factory=VectorDbConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    rerank: RerankSettings = field(default_factory=RerankSettings)
    knowledge_base: KnowledgeBaseConfig = field(default_factory=KnowledgeBaseConfig)
    admin: AdminConfig = field(default_factory=AdminConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    external_search: ExternalSearchConfig = field(default_factory=ExternalSearchConfig)
    deep_research: DeepResearchConfig = field(default_factory=DeepResearchConfig)
    task_queue: TaskQueueConfig = field(default_factory=TaskQueueConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    cors_origins: str = "*"
