"""YAML 配置加载器：${VAR} 占位符解析、环境覆盖与线程安全单例。"""
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml

from .config import (
    AdminConfig,
    AgentConfig,
    AppConfig,
    ASRConfig,
    DatabaseConfig,
    DeepResearchConfig,
    DeepResearchModeConfig,
    DeepResearchModesConfig,
    DuckDuckGoConfig,
    ElasticsearchConfig,
    ExternalSearchConfig,
    FeatureFlag,
    FeaturesConfig,
    HybridSearchConfig,
    KnowledgeBaseConfig,
    KnowledgeOpsConfig,
    LLMConfig,
    MinioConfig,
    ParsingConfig,
    ProjectConfig,
    RedisConfig,
    RerankSettings,
    RetrievalConfig,
    SandboxConfigYaml,
    SecurityConfig,
    SerpAPIConfig,
    SmtpConfig,
    SplittingConfig,
    TaskQueueConfig,
    TavilyConfig,
    VectorDbConfig,
)


class ConfigLoader:
    """YAML 配置加载器：只加载 default.yaml，解析 ${VAR:默认值} 占位符（取值自进程环境/根 .env）。"""
    def __init__(self, config_dir: Path | None = None):
        """指定配置目录（默认包内 yaml/ 目录），便于测试注入临时配置。"""
        self.config_dir = config_dir or Path(__file__).parent / "yaml"
        self._config: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        """加载 default.yaml 并解析 ${VAR} 占位符（单一模式，无环境名概念）。

        Returns:
            占位符已替换（取值自进程环境/仓库根 .env）的完整配置 dict。
        """
        # 两层配置模型：default.yaml 定义结构与默认值，环境差异（host/endpoint/
        # 桶名/凭据）全部经 ${VAR} / ${VAR:默认值} 占位符从环境取值。本地开发
        # 用占位符内默认值（仓库根 .env 提供密钥）；Docker 由 compose environment
        # 注入容器名等覆盖值（优先级高于 env_file 的 .env 全量注入）。
        self._load_dotenv()
        self._config = self._load_yaml("default.yaml")

        self._config = self._replace_env_vars(self._config)
        return self._config

    def _load_dotenv(self) -> None:
        """从仓库根（backend/ 的上一级）加载 .env，供 ${VAR} 占位符解析取值。

        load_dotenv 默认不覆盖已存在的进程环境变量（容器/CI 注入优先于文件）。
        .env 缺失时静默跳过——YAML 占位符此时回落到 _replace_env_vars 的默认值。
        .env 存在但不是合法 UTF-8 时显性报错（典型根因：Windows PowerShell 5.1
        生成 .env 时按 GBK 重编码，见 deploy.ps1 Ensure-EnvFile）——缺失显性化，
        不静默吞掉让占位符全部回落默认值造成难排查的假配置。
        """
        try:
            from dotenv import load_dotenv

            # 本文件位于 <repo>/backend/src/setting/yaml_config/，
            # 仓库根 = 上四级（yaml_config → setting → src → backend → repo）
            repo_root = Path(__file__).resolve().parents[4]
            dotenv_path = repo_root / ".env"
            if not dotenv_path.exists():
                return
            try:
                load_dotenv(dotenv_path, override=False)
            except UnicodeDecodeError as exc:
                raise RuntimeError(
                    f"仓库根 .env 不是合法 UTF-8 编码（{exc}）。"
                    "常见根因：Windows PowerShell 5.1 的 Get-Content/Set-Content 按 GBK 重编码了文件；"
                    "请删除 .env 后用修复后的 deploy.ps1 重新生成，或将文件另存为 UTF-8（无 BOM）。"
                ) from exc
        except ImportError:
            # python-dotenv 为核心依赖，缺失仅在实际有 .env 时才有影响
            pass

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        """读取单个 YAML 文件为 dict；文件不存在或为空返回空 dict。"""
        filepath = self.config_dir / filename
        if filepath.exists():
            with open(filepath, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else {}
        return {}

    def _replace_env_vars(self, config: Any) -> Any:
        """递归替换 ${VAR} / ${VAR:默认值} 占位符；整串占位符做类型归一。

        整串恰为单个占位符时的取值与归一（「全显式」模型：变量一律由 .env
        或进程环境定义，yaml 不内建环境差异默认值）：
        - 未设变量且无默认值 → None（缺失显性化，不做静默空串/兜底）
        - 已设变量（含空串）或占位符带默认值 → 原样/默认值
        - 结果为 "true"/"false" 归一为 bool，"null" 归一为 None
        占位符嵌入更长字符串时（如 URL 拼接）只做纯文本替换，未设变量替换为
        空串（字符串上下文无法表达 None），不做类型归一。反斜杠转义的占位符
        保留为字面量。
        """
        if isinstance(config, str):
            placeholder = "\x00ESCAPED_DOLLAR_BRACE\x00"
            escaped = re.sub(r"\\\$\{", placeholder, config)
            pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

            whole = re.fullmatch(pattern, escaped)
            if whole:
                raw = os.getenv(whole.group(1))
                if raw is None:
                    if whole.group(2) is None:
                        return None
                    raw = whole.group(2)
                if raw == "true":
                    return True
                if raw == "false":
                    return False
                if raw == "null":
                    return None
                return raw

            def _replace_match(match: re.Match[str]) -> str:
                var_name = match.group(1)
                default = match.group(2) if match.group(2) is not None else ""
                return os.getenv(var_name, default)

            result = re.sub(pattern, _replace_match, escaped)
            return result.replace(placeholder, "${")
        if isinstance(config, dict):
            return {k: self._replace_env_vars(v) for k, v in config.items()}
        if isinstance(config, list):
            return [self._replace_env_vars(item) for item in config]
        return config

    def get(self, key: str, default: Any = None) -> Any:
        """按点号路径读取已加载配置 dict 的嵌套值，任一层缺失返回 default。

        Args:
            key: 点号分隔的配置路径（如 database.pool_size），逐段下钻。
            default: 任一层缺失时的兜底值；None 表示缺失即返回 None。

        Returns:
            命中的配置值（类型由 YAML 决定）；路径中断或键缺失返回 default。
        """
        value: Any = self._config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value


def create_config_from_dict(data: dict[str, Any]) -> AppConfig:
    """把原始配置 dict 映射为强类型 AppConfig（逐节构造 dataclass，未提供的键用默认值）。

    Args:
        data: load 产出的原始配置 dict；缺失的节用 dataclass 默认值填充。

    Returns:
        可直接全局使用的 AppConfig 实例（minio.secure 严格按配置取值，不静默改写）。
    """
    config = AppConfig()
    config.cors_origins = data.get("cors_origins", "*")

    project = data.get("project", {})
    config.project = ProjectConfig(
        name=project.get("name", "novamind"),
        version=project.get("version", "0.1.0"),
        description=project.get("description", "novamind backend"),
    )

    minio_cfg = data.get("minio", {})
    minio_secure = minio_cfg.get("secure", False)
    config.minio = MinioConfig(
        endpoint=minio_cfg.get("endpoint", "localhost:9000"),
        public_endpoint=minio_cfg.get("public_endpoint"),
        access_key=minio_cfg.get("access_key", ""),
        secret_key=minio_cfg.get("secret_key", ""),
        secure=minio_secure,
        region=minio_cfg.get("region", "us-east-1"),
        bucket_name=minio_cfg.get("bucket_name", "knowledge-base"),
    )

    es_cfg = data.get("elasticsearch", {})
    config.elasticsearch = ElasticsearchConfig(
        hosts=es_cfg.get("hosts", ["http://localhost:9200"]),
        username=es_cfg.get("username"),
        password=es_cfg.get("password"),
        index_prefix=es_cfg.get("index_prefix", "kb"),
        default_embedding_dim=es_cfg.get("default_embedding_dim", 1024),
        analyzer=es_cfg.get("analyzer", "ik_max_word"),
        verify_certs=es_cfg.get("verify_certs", False),
        ca_certs=es_cfg.get("ca_certs"),
    )

    db = data.get("database", {})
    config.database = DatabaseConfig(
        host=db.get("host", "localhost"),
        port=db.get("port", 3306),
        user=db.get("user", "root"),
        password=db.get("password", ""),
        database=db.get("database", "novamind_db"),
        pool_size=db.get("pool_size", 10),
        max_overflow=db.get("max_overflow", 20),
        pool_timeout=db.get("pool_timeout", 30),
        pool_recycle=db.get("pool_recycle", 3600),
        pool_pre_ping=db.get("pool_pre_ping", True),
        ssl=db.get("ssl", False),
    )

    redis = data.get("redis", {})
    config.redis = RedisConfig(
        enabled=redis.get("enabled", False),
        host=redis.get("host", "localhost"),
        port=redis.get("port", 6379),
        db=redis.get("db", 0),
        password=redis.get("password"),
        max_connections=redis.get("max_connections", 10),
        sentinel_hosts=redis.get("sentinel_hosts", ""),
        sentinel_master=redis.get("sentinel_master", "mymaster"),
        cluster_hosts=redis.get("cluster_hosts", ""),
    )

    llm = data.get("llm", {})
    config.llm = LLMConfig(
        compression_strategy=llm.get("compression_strategy", "summary"),
        compression_threshold=llm.get("compression_threshold", 70000),
        keep_recent_messages=llm.get("keep_recent_messages", 6),
        compression_target_tokens=llm.get("compression_target_tokens", 2000),
        enable_compression=llm.get("enable_compression", True),
        custom_summary_prompt=llm.get("custom_summary_prompt"),
    )

    rerank = data.get("rerank", {})
    config.rerank = RerankSettings(
        enabled=rerank.get("enabled", False),
        default_top_k=rerank.get("default_top_k", 3),
    )

    admin = data.get("admin", {})
    config.admin = AdminConfig(
        username=admin.get("username", "admin"),
        email=admin.get("email", "admin@example.com"),
        password=admin.get("password", ""),
        phone=admin.get("phone"),
        create_on_startup=admin.get("create_on_startup", True),
        reset_password_if_exists=admin.get("reset_password_if_exists", False),
    )

    security = data.get("security", {})
    config.security = SecurityConfig(
        secret_key=security.get("secret_key", ""),
        algorithm=security.get("algorithm", "HS256"),
        access_token_expire_minutes=security.get("access_token_expire_minutes", 30),
        encryption_key=security.get("encryption_key", ""),
    )

    kb = data.get("knowledge_base", {})
    splitting = kb.get("splitting", {})
    parsing = kb.get("parsing", {})
    retrieval = kb.get("retrieval", {})
    hybrid = retrieval.get("hybrid_search", {})
    config.knowledge_base = KnowledgeBaseConfig(
        splitting=SplittingConfig(
            strategy=splitting.get("strategy", "recursive"),
            chunk_size=splitting.get("chunk_size", 500),
            chunk_overlap=splitting.get("chunk_overlap", 50),
            separator=splitting.get("separator", "\n\n"),
            min_chunk_size=splitting.get("min_chunk_size", 100),
            max_chunk_size=splitting.get("max_chunk_size", 2000),
        ),
        parsing=ParsingConfig(
            extract_images=parsing.get("extract_images", False),
            extract_tables=parsing.get("extract_tables", True),
            preserve_structure=parsing.get("preserve_structure", True),
            encoding=parsing.get("encoding", "utf-8"),
            vlm_description_enabled=parsing.get("vlm_description_enabled", False),
            local_whisper_model_dir=parsing.get("local_whisper_model_dir", None),
            local_whisper_model=parsing.get("local_whisper_model", None),
            local_whisper_cpu_threads=parsing.get("local_whisper_cpu_threads", None),
            local_whisper_device=parsing.get("local_whisper_device", None),
            local_whisper_compute_type=parsing.get("local_whisper_compute_type", None),
            local_whisper_beam_size=parsing.get("local_whisper_beam_size", None),
            local_whisper_vad_enabled=parsing.get("local_whisper_vad_enabled", True),
            video_vlm_concurrency=parsing.get("video_vlm_concurrency", 4),
            max_upload_size_mb=parsing.get("max_upload_size_mb", 2048),
            download_tmp_dir=parsing.get("download_tmp_dir", None),
            chunk_upload_dir=parsing.get("chunk_upload_dir", None),
            chunk_upload_session_ttl_sec=parsing.get("chunk_upload_session_ttl_sec", 86400),
            chunk_upload_max_chunk_mb=parsing.get("chunk_upload_max_chunk_mb", 32),
            chunk_upload_max_sessions_per_user=parsing.get(
                "chunk_upload_max_sessions_per_user", 5
            ),
        ),
        retrieval=RetrievalConfig(
            top_k=retrieval.get("top_k", 5),
            score_threshold=retrieval.get("score_threshold", 0.7),
            rerank_enabled=retrieval.get("rerank_enabled", False),
            hybrid_search=HybridSearchConfig(
                enabled=hybrid.get("enabled", True),
                vector_weight=hybrid.get("vector_weight", 0.7),
                text_weight=hybrid.get("text_weight", 0.3),
            ),
        ),
    )

    ext_search = data.get("external_search", {})
    tavily = ext_search.get("tavily", {})
    serpapi = ext_search.get("serpapi", {})
    duckduckgo = ext_search.get("duckduckgo", {})
    config.external_search = ExternalSearchConfig(
        tavily=TavilyConfig(
            api_key=tavily.get("api_key", ""),
            max_results=tavily.get("max_results", 10),
            search_depth=tavily.get("search_depth", "basic"),
            timeout=tavily.get("timeout", 30),
        ),
        serpapi=SerpAPIConfig(
            api_key=serpapi.get("api_key", ""),
            max_results=serpapi.get("max_results", 10),
            timeout=serpapi.get("timeout", 30),
            engine=serpapi.get("engine", "google"),
        ),
        duckduckgo=DuckDuckGoConfig(
            max_results=duckduckgo.get("max_results", 10),
            timeout=duckduckgo.get("timeout", 15),
        ),
    )

    asr = data.get("asr", {})
    config.asr = ASRConfig(
        openai_api_key=asr.get("openai_api_key", ""),
        openai_base_url=asr.get("openai_base_url", "https://api.openai.com/v1"),
        dashscope_api_key=asr.get("dashscope_api_key", ""),
        local_whisper_model_dir=asr.get("local_whisper_model_dir", ""),
    )

    agent = data.get("agent", {})
    sandbox = agent.get("sandbox", {})
    config.agent = AgentConfig(
        sandbox=SandboxConfigYaml(
            enabled=sandbox.get("enabled", False),
            max_memory_mb=sandbox.get("max_memory_mb", 256),
            max_output_bytes=sandbox.get("max_output_bytes", 65536),
            default_timeout=sandbox.get("default_timeout", 30),
            max_timeout=sandbox.get("max_timeout", 120),
            network_disabled=sandbox.get("network_disabled", True),
            rebuild_interval=sandbox.get("rebuild_interval", 50),
            container_prefix=sandbox.get("container_prefix", "agent_sandbox"),
            images=sandbox.get(
                "images",
                {
                    "python": "python:3.12-slim",
                    "javascript": "node:20-slim",
                    "shell": "bash:5",
                },
            ),
        )
    )

    dr = data.get("deep_research", {})
    modes = dr.get("modes", {})
    quick = modes.get("quick", {})
    standard = modes.get("standard", {})
    deep = modes.get("deep", {})
    config.deep_research = DeepResearchConfig(
        modes=DeepResearchModesConfig(
            quick=DeepResearchModeConfig(
                depth=quick.get("depth", 2),
                iterations=quick.get("iterations", 3),
            ),
            standard=DeepResearchModeConfig(
                depth=standard.get("depth", 3),
                iterations=standard.get("iterations", 5),
            ),
            deep=DeepResearchModeConfig(
                depth=deep.get("depth", 5),
                iterations=deep.get("iterations", 7),
            ),
        )
    )

    vector_db = data.get("vector_db", {})
    config.vector_db = VectorDbConfig(type=vector_db.get("type", "elasticsearch"))

    tq = data.get("task_queue", {})
    config.task_queue = TaskQueueConfig(
        max_jobs=tq.get("max_jobs", 3),
        job_timeout=tq.get("job_timeout", 1800),
        max_tries=tq.get("max_tries", 3),
        retry_base_delay=tq.get("retry_base_delay", 60),
        queue_name=tq.get("queue_name", "arq:queue"),
    )

    ko = data.get("knowledge_ops", {})
    config.knowledge_ops = KnowledgeOpsConfig(
        reformulate_window_seconds=ko.get("reformulate_window_seconds", 120),
        reformulate_similarity_threshold=ko.get("reformulate_similarity_threshold", 0.5),
        attribution_low_score_threshold=ko.get("attribution_low_score_threshold", 0.35),
        attribution_replay_low_threshold=ko.get("attribution_replay_low_threshold", 0.15),
        attribution_lookback_days=ko.get("attribution_lookback_days", 7),
        attribution_batch_limit=ko.get("attribution_batch_limit", 50),
        review_advance_days=ko.get("review_advance_days", 7),
        review_fallback_cycle_days=ko.get("review_fallback_cycle_days", 90),
        testset_max_cases=ko.get("testset_max_cases", 20),
        quality_baseline_enabled=ko.get("quality_baseline_enabled", False),
    )

    smtp = data.get("smtp", {})
    config.smtp = SmtpConfig(
        enabled=smtp.get("enabled", False),
        host=smtp.get("host", ""),
        port=smtp.get("port", 587),
        username=smtp.get("username", ""),
        password=smtp.get("password", ""),
        from_email=smtp.get("from_email", ""),
        use_tls=smtp.get("use_tls", True),
    )

    # 功能开关：features 段可选，键为 feature 名，值为 bool 或 {enabled: bool}。
    # 未列出的 feature 默认启用（由 manifest_loader 解析）。
    features_raw = data.get("features", {}) or {}
    flags: dict[str, FeatureFlag] = {}
    for name, val in features_raw.items():
        if isinstance(val, dict):
            flags[name] = FeatureFlag(enabled=bool(val.get("enabled", True)))
        else:
            flags[name] = FeatureFlag(enabled=bool(val))
    config.features = FeaturesConfig(flags=flags)

    return config


_loader: ConfigLoader | None = None
_config_dict: dict[str, Any] | None = None
_config: AppConfig | None = None
_config_lock = threading.Lock()


def get_config() -> AppConfig:
    """全局配置单例入口：首次调用时惰性加载并构造 AppConfig，进程内缓存复用；加载过程持锁保证并发安全，仅初始化一次。"""
    global _loader, _config_dict, _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _loader = ConfigLoader()
                _config_dict = _loader.load()
                _config = create_config_from_dict(_config_dict)
    return _config


def get_config_dict() -> dict[str, Any]:
    """返回 get_config 加载后的原始配置 dict（占位符已解析）；未加载时先触发加载。"""
    get_config()
    return _config_dict or {}


def get_config_value(key: str, default: Any = None) -> Any:
    """按点号路径读取单个配置项；必要时先触发全局配置加载。

    Args:
        key: 点号分隔的配置路径（如 features.wiki.enabled）。
        default: 键缺失时的兜底值；None 表示缺失即返回 None。

    Returns:
        命中的配置值；键不存在返回 default。
    """
    global _loader
    if _loader is None:
        get_config()
    return _loader.get(key, default)


def reload_config() -> AppConfig:
    """强制重新加载配置并刷新全局单例，返回新 AppConfig；持锁执行避免并发加载撕裂。

    Returns:
        重新构造的 AppConfig 实例（进程内后续 get_config 均命中新单例）。
    """
    global _loader, _config_dict, _config
    with _config_lock:
        _loader = ConfigLoader()
        _config_dict = _loader.load()
        _config = create_config_from_dict(_config_dict)
    return _config
