"""YAML 配置 dataclass 定义：全部配置节的强类型结构。"""
from dataclasses import dataclass, field
from urllib.parse import quote_plus


@dataclass
class FeatureFlag:
    """单个功能开关。

    预留扩展：后续可在本 dataclass 上追加更多 per-feature 标志（如只读、
    灰度比例等），而不破坏 YAML schema。当前只含 `enabled`。
    """

    enabled: bool = True


@dataclass
class FeaturesConfig:
    """功能开关集合（feature flag）。

    `flags` 键为 feature 名（与 `features/<name>/manifest.py` 的 `name` 一致），
    值为 `FeatureFlag`。未在 `flags` 中列出的 feature 默认启用——由 manifest_loader
    以 `flags.get(name, FeatureFlag()).enabled` 解析。

    YAML 形态（`features:` 段，可选）：
      features:
        example_feature:
          enabled: false
      # 或简写：example_feature: false
    """

    flags: dict[str, FeatureFlag] = field(default_factory=dict)


@dataclass
class MinioConfig:
    """minio 段：对象存储端点、凭据与桶名；public_endpoint 为外部可达的公网地址（生成预签名 URL 用）。"""
    endpoint: str = "localhost:9000"
    public_endpoint: str | None = None  # 外部服务可访问的公网地址，如 https://minio.example.com
    access_key: str = ""
    secret_key: str = ""
    secure: bool = False
    region: str = "us-east-1"
    bucket_name: str = "knowledge-base"


@dataclass
class ElasticsearchConfig:
    """elasticsearch 段：ES 集群地址、凭据、索引前缀、默认向量维度与中文分词器配置。"""
    hosts: list[str] = field(default_factory=lambda: ["http://localhost:9200"])
    username: str | None = None
    password: str | None = None
    index_prefix: str = "kb"
    default_embedding_dim: int = 1024
    analyzer: str = "ik_max_word"
    verify_certs: bool = False
    ca_certs: str | None = None


@dataclass
class VectorDbConfig:
    """vector_db 段：向量库类型（默认 elasticsearch，预留其他实现）。"""
    type: str = "elasticsearch"


@dataclass
class SplittingConfig:
    """knowledge_base.splitting 段：文档分块策略、块大小与重叠、分隔符及块大小上下限。"""
    strategy: str = "recursive"
    chunk_size: int = 500
    chunk_overlap: int = 50
    separator: str = "\n\n"
    min_chunk_size: int = 100
    max_chunk_size: int = 2000


@dataclass
class ParsingConfig:
    """knowledge_base.parsing 段：解析开关（图片/表格/结构保留/VLM 描述）与本地 whisper、视频 VLM 并发等媒体参数。"""
    extract_images: bool = False
    extract_tables: bool = True
    preserve_structure: bool = True
    encoding: str = "utf-8"
    vlm_description_enabled: bool = False
    # 本地 faster-whisper ASR 模型目录（绝对路径）。为空时回退到环境变量
    # NOVAMIND_LOCAL_WHISPER_MODEL_DIR，再为空时用默认 backend/.cache/faster-whisper/tiny
    # （仓库根缓存，与 deepdoc 同约定；Docker 形态挂载为 /app/.cache/faster-whisper）。
    local_whisper_model_dir: str | None = None
    # 本地 faster-whisper 转写 CPU 线程数。None 时按物理核自动取保守值（留至少 1
    # 物理核给事件循环）。转写期间其它请求仍卡顿就调小（如 2）；ASR 太慢可调大，
    # 但勿超过 (物理核 - 1)，否则会重新饿死事件循环。
    local_whisper_cpu_threads: int | None = None
    # 视频 VLM 逐帧/逐组描述并发数（1=串行，默认 4，范围 1~20）。长视频 60 帧串行
    # 易逼近 arq job_timeout=1800s，有界并发降时延；过高可能触发 VLM 配额限流，
    # 配合 vlm_fallback_model / vlm_skip_on_quota_error（KB 级）降级。
    video_vlm_concurrency: int = 4
    # 上传流式读取的全局字节硬顶（MB）。流式 sha256+计数边读边检，超限即断流
    # 拒收——Content-Length 缺失/chunked encoding/伪造头都靠它兜底。须 >= 各模态
    # 上限（video 默认 2000MB）。这是宿主资源旋钮：生产按盘/带宽调整，
    # 与 nginx NGINX_MAX_BODY_SIZE（请求体层）联动。
    max_upload_size_mb: int = 2048
    # worker 下载 MinIO 原件的落盘目录（绝对路径）。None 时用系统默认临时目录
    # （TEMP/TMP）。大视频（2GB 级）流式写盘需要有独立分区/大盘的部署期旋钮，
    # 避免打爆系统盘或容器可写层。
    download_tmp_dir: str | None = None
    # 分片上传暂存目录（绝对路径）。None 时用系统默认临时目录下的
    # novamind_chunk_uploads/ 子目录。与 download_tmp_dir 同理：大文件分片
    # 暂存需要独立数据盘时配置。
    chunk_upload_dir: str | None = None
    # 分片上传会话 TTL（秒）。每次 chunk PUT 续期；过期后 Redis 键自动清理，
    # .part 残留由 cron 兜底扫（TTL×2 mtime）。默认 24h 覆盖慢网络大文件。
    chunk_upload_session_ttl_sec: int = 86400
    # 单分片最大体积（MB）。防单请求巨片绕过分片意义（nginx 层另有
    # client_max_body_size 联动）。前端默认 16MB/片，此处留裕量。
    chunk_upload_max_chunk_mb: int = 32
    # 单用户并发分片上传会话数上限。防会话数堆积占用暂存盘（磁盘填充防护之一）。
    chunk_upload_max_sessions_per_user: int = 5


@dataclass
class HybridSearchConfig:
    """knowledge_base.retrieval.hybrid_search 段：混合检索开关与向量/文本得分权重。"""
    enabled: bool = True
    vector_weight: float = 0.7
    text_weight: float = 0.3


@dataclass
class RetrievalConfig:
    """knowledge_base.retrieval 段：检索条数 top_k、得分阈值、重排开关及内嵌混合检索配置。"""
    top_k: int = 5
    score_threshold: float = 0.7
    rerank_enabled: bool = False
    hybrid_search: HybridSearchConfig = field(default_factory=HybridSearchConfig)


@dataclass
class KnowledgeBaseConfig:
    """knowledge_base 段：知识库级切分、解析、检索三类配置的聚合。"""
    splitting: SplittingConfig = field(default_factory=SplittingConfig)
    parsing: ParsingConfig = field(default_factory=ParsingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)


@dataclass
class DatabaseConfig:
    """database 段：MySQL 连接参数、连接池容量/超时/回收策略与 SSL 开关。"""
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
        """拼装 aiomysql 异步连接串（密码经 URL 编码，强制 utf8mb4 字符集）。"""
        return (
            f"mysql+aiomysql://{self.user}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )


@dataclass
class RedisConfig:
    """redis 段：连接参数、连接池上限及哨兵/集群地址（单机、哨兵、集群三种部署形态互斥）。"""
    enabled: bool = False
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    max_connections: int = 10
    sentinel_hosts: str = ""
    sentinel_master: str = "mymaster"
    cluster_hosts: str = ""


@dataclass
class LLMConfig:
    """llm 段：会话上下文压缩策略、触发阈值、保留最近消息数与目标压缩 token 数。"""
    compression_strategy: str = "summary"
    compression_threshold: int = 70000
    keep_recent_messages: int = 6
    compression_target_tokens: int = 2000
    enable_compression: bool = True
    custom_summary_prompt: str | None = None


@dataclass
class RerankSettings:
    """rerank 段：全局重排开关与默认返回条数。"""
    enabled: bool = False
    default_top_k: int = 3


@dataclass
class AdminConfig:
    """admin 段：启动期初始化管理员的账号信息与创建/重置密码行为开关。"""
    username: str = "admin"
    email: str = "admin@example.com"
    password: str = ""
    phone: str | None = None
    create_on_startup: bool = True
    reset_password_if_exists: bool = False


@dataclass
class SecurityConfig:
    """security 段：JWT 签名密钥与算法、access token 有效期、数据加密密钥（API Key 加密用）。"""
    secret_key: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    encryption_key: str = ""


@dataclass
class TavilyConfig:
    """external_search.tavily 段：Tavily 搜索的 API Key、结果数、搜索深度与超时。"""
    api_key: str = ""
    max_results: int = 10
    search_depth: str = "basic"
    timeout: int = 30


@dataclass
class SerpAPIConfig:
    """external_search.serpapi 段：SerpAPI 的 API Key、结果数、超时与底层搜索引擎。"""
    api_key: str = ""
    max_results: int = 10
    timeout: int = 30
    engine: str = "google"


@dataclass
class DuckDuckGoConfig:
    """external_search.duckduckgo 段：免费搜索的结果数与超时（无需 API Key）。"""
    max_results: int = 10
    timeout: int = 15


@dataclass
class ExternalSearchConfig:
    """external_search 段：tavily / serpapi / duckduckgo 三个外部搜索源配置的聚合。"""
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    serpapi: SerpAPIConfig = field(default_factory=SerpAPIConfig)
    duckduckgo: DuckDuckGoConfig = field(default_factory=DuckDuckGoConfig)


@dataclass
class ASRConfig:
    """云端 ASR 凭据（批次 4.7：audio_utils 环境变量直读改配置中心统一入口）。

    值仍可来自环境变量（ConfigLoader 的 ${VAR} 占位符），但读取点收敛到
    ``get_config().asr``，audio_utils 不再各自 ``os.environ.get``。
    """

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    dashscope_api_key: str = ""
    local_whisper_model_dir: str = ""


@dataclass
class SandboxConfigYaml:
    """agent 代码执行沙箱参数（features/agent/sandbox/config.py SandboxConfig 的 YAML 段）。"""

    enabled: bool = False
    max_memory_mb: int = 256
    max_output_bytes: int = 65536
    default_timeout: int = 30
    max_timeout: int = 120
    network_disabled: bool = True
    rebuild_interval: int = 50
    container_prefix: str = "agent_sandbox"
    images: dict[str, str] = field(default_factory=lambda: {
        "python": "python:3.12-slim",
        "javascript": "node:20-slim",
        "shell": "bash:5",
    })


@dataclass
class AgentConfig:
    """agent feature 的 YAML 配置段。"""

    sandbox: SandboxConfigYaml = field(default_factory=SandboxConfigYaml)


@dataclass
class DeepResearchModeConfig:
    """deep_research.modes.<mode> 段：单个深度研究模式的搜索深度与迭代轮数。"""
    depth: int = 3
    iterations: int = 5


@dataclass
class DeepResearchModesConfig:
    """deep_research.modes 段：quick / standard / deep 三档深度研究模式参数。"""
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
    """deep_research 段：深度研究功能的模式配置集合。"""
    modes: DeepResearchModesConfig = field(default_factory=DeepResearchModesConfig)


@dataclass
class KnowledgeOpsConfig:
    """知识运营（kb-ops）feature 的 YAML 配置段。"""

    # 会话内改写检测：时间窗（秒）与字符 3-gram 相似度阈值。
    # 判定保守：宁可漏标不可误标（误标会污染 gap 统计）。
    reformulate_window_seconds: int = 120
    reformulate_similarity_threshold: float = 0.5
    # 归因流水线（A1）：低分阈值与批次 2b 看板同口径；降级阈值用于区分
    # content_gap vs retrieval_failure；回溯窗与批上限控制追赶成本。
    attribution_low_score_threshold: float = 0.35
    attribution_replay_low_threshold: float = 0.15
    attribution_lookback_days: int = 7
    attribution_batch_limit: int = 50
    # 复审提醒（B2）：到期前提前提醒天数；确认复审时无周期文档的顺延天数
    review_advance_days: int = 7
    review_fallback_cycle_days: int = 90
    # 质量基线（C）：合成测试集单 KB 配额上限（LLM 成本硬闸）；跑批 cron 开关
    testset_max_cases: int = 20
    quality_baseline_enabled: bool = False


@dataclass
class ProjectConfig:
    """project 段：项目名、版本与描述（健康检查与根路径信息展示用）。"""
    name: str = "novamind"
    version: str = "0.1.0"
    description: str = "novamind backend"


@dataclass
class TaskQueueConfig:
    """task_queue 段：arq 任务队列的并发上限、单任务超时、重试次数与退避基数。"""
    max_jobs: int = 3
    job_timeout: int = 1800
    max_tries: int = 3
    retry_base_delay: int = 60
    queue_name: str = "arq:queue"


@dataclass
class SmtpConfig:
    """smtp 段：邮件服务器连接参数、发件人与 TLS 开关（通知邮件发送用）。"""
    enabled: bool = False
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_email: str = ""
    use_tls: bool = True


@dataclass
class AppConfig:
    """全量配置根：聚合全部配置节，是 get_config() 返回的强类型配置对象。"""
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
    asr: ASRConfig = field(default_factory=ASRConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    deep_research: DeepResearchConfig = field(default_factory=DeepResearchConfig)
    task_queue: TaskQueueConfig = field(default_factory=TaskQueueConfig)
    knowledge_ops: KnowledgeOpsConfig = field(default_factory=KnowledgeOpsConfig)
    smtp: SmtpConfig = field(default_factory=SmtpConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)
    cors_origins: str = "*"
