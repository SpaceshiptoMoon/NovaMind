import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .config import (
    AdminConfig,
    AppConfig,
    DatabaseConfig,
    DeepResearchConfig,
    DeepResearchModeConfig,
    DeepResearchModesConfig,
    DuckDuckGoConfig,
    ElasticsearchConfig,
    ExternalSearchConfig,
    HybridSearchConfig,
    KnowledgeBaseConfig,
    LLMConfig,
    MinioConfig,
    ParsingConfig,
    ProjectConfig,
    RedisConfig,
    RetrievalConfig,
    RerankSettings,
    SecurityConfig,
    SerpAPIConfig,
    SplittingConfig,
    SmtpConfig,
    TavilyConfig,
    TaskQueueConfig,
    VectorDbConfig,
)


class ConfigLoader:
    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path(__file__).parent / "yaml"
        self._config: Dict[str, Any] = {}

    def load(self, environment: Optional[str] = None) -> Dict[str, Any]:
        env = environment or os.getenv("ENVIRONMENT", "development")
        default_config = self._load_yaml("default.yaml")
        env_config = self._load_yaml(f"{env}.yaml")
        local_config = self._load_yaml("local.yaml")

        self._config = self._deep_merge(default_config, env_config)
        if local_config:
            self._config = self._deep_merge(self._config, local_config)

        self._config = self._replace_env_vars(self._config)
        self._config["environment"] = env
        return self._config

    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        filepath = self.config_dir / filename
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if data else {}
        return {}

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    def _replace_env_vars(self, config: Any) -> Any:
        if isinstance(config, str):
            placeholder = "\x00ESCAPED_DOLLAR_BRACE\x00"
            escaped = re.sub(r"\\\$\{", placeholder, config)
            pattern = r"\$\{([^}:]+)(?::([^}]*))?\}"

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
        value: Any = self._config
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value


def create_config_from_dict(data: Dict[str, Any]) -> AppConfig:
    config = AppConfig()
    config.environment = data.get("environment", "development")
    config.cors_origins = data.get("cors_origins", "*")

    project = data.get("project", {})
    config.project = ProjectConfig(
        name=project.get("name", "novamind"),
        version=project.get("version", "0.1.0"),
        description=project.get("description", "novamind backend"),
    )

    minio_cfg = data.get("minio", {})
    is_production = config.environment == "production"
    minio_secure = minio_cfg.get("secure", False)
    if is_production and not minio_secure:
        import logging

        logging.warning("Production MinIO should enable SSL; forcing secure=true")
        minio_secure = True
    config.minio = MinioConfig(
        endpoint=minio_cfg.get("endpoint", "localhost:9000"),
        public_endpoint=minio_cfg.get("public_endpoint"),
        access_key=minio_cfg.get("access_key", "***REMOVED***"),
        secret_key=minio_cfg.get("secret_key", "***REMOVED***"),
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
        password=admin.get("password", "***REMOVED***"),
        phone=admin.get("phone"),
        create_on_startup=admin.get("create_on_startup", True),
        reset_password_if_exists=admin.get("reset_password_if_exists", False),
    )

    security = data.get("security", {})
    config.security = SecurityConfig(
        secret_key=security.get("secret_key", "your-super-secret-key"),
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
            ocr_enabled=parsing.get("ocr_enabled", False),
            preserve_structure=parsing.get("preserve_structure", True),
            encoding=parsing.get("encoding", "utf-8"),
            vlm_description_enabled=parsing.get("vlm_description_enabled", False),
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

    return config


_loader: Optional[ConfigLoader] = None
_config_dict: Optional[Dict[str, Any]] = None
_config: Optional[AppConfig] = None
_environment: Optional[str] = None
_config_lock = threading.Lock()


def set_environment(env: str) -> None:
    global _environment, _loader, _config_dict, _config
    with _config_lock:
        _environment = env
        _loader = None
        _config_dict = None
        _config = None


def get_environment() -> Optional[str]:
    return _environment


def get_config() -> AppConfig:
    global _loader, _config_dict, _config, _environment
    if _config is None:
        with _config_lock:
            if _config is None:
                _loader = ConfigLoader()
                env = _environment or os.getenv("ENVIRONMENT", "development")
                _config_dict = _loader.load(env)
                _config = create_config_from_dict(_config_dict)
    return _config


def get_config_dict() -> Dict[str, Any]:
    get_config()
    return _config_dict or {}


def get_config_value(key: str, default: Any = None) -> Any:
    global _loader
    if _loader is None:
        get_config()
    return _loader.get(key, default)


def reload_config(environment: Optional[str] = None) -> AppConfig:
    global _loader, _config_dict, _config
    with _config_lock:
        _loader = ConfigLoader()
        _config_dict = _loader.load(environment)
        _config = create_config_from_dict(_config_dict)
    return _config
