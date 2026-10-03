"""回归门禁：配置分工——凭据 .env 显式定义，连接参数 yaml 基线 + compose 覆盖。

锁定 2026-10 配置架构三轮收敛后的最终语义：
- 纯 ${VAR}（凭据类，yaml 不带默认值）：未定义 → None（缺失显性化，不静默兜底）
- ${VAR:基线}（连接类）：未定义 → 基线默认值（本地开发零配置）；整串
  true/false/null 归一为 bool/None；嵌入串纯文本替换、未设替换空串
- compose environment 注入优先于 env_file（Docker 连接值路径）
- <环境>.yaml / local.yaml 合并层已删除：同名文件存在也必须被忽略
- 无环境名概念（单一模式）：load 不接受环境参数，配置 dict 不含 environment 键
- minio.secure 严格按占位符取值、不静默改写（历史 production 强制翻转已删除——
  它会把 https 打到 http 端口直接断连）
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.setting.yaml_config.loader import ConfigLoader, create_config_from_dict

pytestmark = pytest.mark.unit

YAML = (
    "security:\n"
    '  secret_key: "${SECRET_KEY}"\n'      # 凭据类：无基线，缺失 → None
    "redis:\n"
    '  enabled: "${REDIS_ENABLED:true}"\n'  # 连接类：本地基线
    '  host: "${REDIS_HOST:127.0.0.1}"\n'
    "minio:\n"
    '  secure: "${MINIO_SECURE:false}"\n'   # 部署拓扑开关：内网 http / TLS 才 true
    "es:\n"
    "  hosts:\n"
    '    - "${ES_HOST:http://127.0.0.1:9200}"\n'
    '  username: "${ES_USERNAME:elastic}"\n'
    '  password: "${ES_PASSWORD:}"\n'
    'cors_origins: "${CORS_ORIGINS:*}"\n'   # 同源部署默认 *；跨源 API 消费方才收紧
    'mixed: "scheme://${ES_HOST:x}/v"\n'
)

VARS = (
    "SECRET_KEY",
    "REDIS_ENABLED",
    "REDIS_HOST",
    "MINIO_SECURE",
    "ES_HOST",
    "ES_USERNAME",
    "ES_PASSWORD",
    "CORS_ORIGINS",
)


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """隔离的配置目录：只写 default.yaml。

    同时把 _load_dotenv 打桩为空操作——loader 固定读真实仓库根 .env，
    本机 .env 里的同名变量（如 SECRET_KEY）会污染缺失/基线断言。
    """
    monkeypatch.setattr(ConfigLoader, "_load_dotenv", lambda self: None)
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "default.yaml").write_text(YAML, encoding="utf-8")
    return tmp_path


def test_credential_without_definition_is_none(config_dir):
    """凭据类纯占位符未定义 → None（缺失显性化），不静默兜底。"""
    c = ConfigLoader(config_dir=config_dir).load()
    assert c["security"]["secret_key"] is None


def test_connection_params_fall_back_to_yaml_baseline(config_dir):
    """连接类未定义 → yaml 基线默认值（本地开发零配置）；bool 基线归一为 True。"""
    c = ConfigLoader(config_dir=config_dir).load()
    assert c["redis"]["enabled"] is True
    assert c["redis"]["host"] == "127.0.0.1"
    assert c["es"]["hosts"] == ["http://127.0.0.1:9200"]
    assert c["es"]["username"] == "elastic"
    assert c["es"]["password"] == ""
    assert c["mixed"] == "scheme://x/v"


def test_compose_injection_overrides_baseline(config_dir, monkeypatch):
    """正用例：compose environment 注入（进程环境变量形态）覆盖 yaml 基线。"""
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("DB_HOST", "mysql")
    monkeypatch.setenv("ES_HOST", "http://elasticsearch:9200")
    monkeypatch.setenv("ES_USERNAME", "")  # 空串 = ES 客户端 falsy 短路免认证
    c = ConfigLoader(config_dir=config_dir).load()
    assert c["redis"]["host"] == "redis"
    assert c["es"]["hosts"] == ["http://elasticsearch:9200"]
    assert c["es"]["username"] == ""


def test_defined_credential_used_and_null_coercion(config_dir, monkeypatch):
    """已定义凭据按值使用；"null" 归一为 None。"""
    monkeypatch.setenv("SECRET_KEY", "real-secret")
    monkeypatch.setenv("ES_PASSWORD", "null")
    c = ConfigLoader(config_dir=config_dir).load()
    assert c["security"]["secret_key"] == "real-secret"
    assert c["es"]["password"] is None


def test_env_yaml_and_local_yaml_are_ignored(config_dir):
    """负向锁：合并层已删除——docker.yaml/local.yaml 存在也绝不能参与加载。"""
    (config_dir / "docker.yaml").write_text("redis:\n  host: evil\n", encoding="utf-8")
    # cors_origins 在 default.yaml 里有占位符，断言其解析值（而非键缺失）锁得更死：
    # 若 local.yaml 合并层复活，这里会变成 evil 而不是 *
    (config_dir / "local.yaml").write_text("cors_origins: evil\n", encoding="utf-8")
    c = ConfigLoader(config_dir=config_dir).load()
    assert c["redis"]["host"] == "127.0.0.1"
    assert c["cors_origins"] == "*"


def test_environment_key_is_gone(config_dir):
    """负向锁：环境名概念已删除——配置 dict 不含 environment 键（单一模式）。"""
    assert "environment" not in ConfigLoader(config_dir=config_dir).load()


def test_minio_secure_defaults_false_no_silent_rewrite(config_dir):
    """负向锁：MINIO_SECURE 未设 → AppConfig.minio.secure 保持 False，不得静默翻转。

    历史实现会在 production 强制 secure=true，导致 https 打到 compose MinIO 的
    http 端口直接断连；环境名概念删除后该路径已不存在，锁死「严格按配置取值」。
    """
    raw = ConfigLoader(config_dir=config_dir).load()
    app_cfg = create_config_from_dict(raw)
    assert app_cfg.minio.secure is False


def test_minio_secure_true_passthrough(config_dir, monkeypatch):
    """正用例：显式设 MINIO_SECURE=true → AppConfig.minio.secure 为 True（TLS 拓扑）。"""
    monkeypatch.setenv("MINIO_SECURE", "true")
    raw = ConfigLoader(config_dir=config_dir).load()
    assert create_config_from_dict(raw).minio.secure is True


def test_cors_origins_default_wildcard_and_explicit_override(config_dir, monkeypatch):
    """CORS 白名单：未设 → 通配 *（同源部署零配置）；显式设 → 逐字透传。"""
    raw = ConfigLoader(config_dir=config_dir).load()
    assert create_config_from_dict(raw).cors_origins == "*"

    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    raw = ConfigLoader(config_dir=config_dir).load()
    assert create_config_from_dict(raw).cors_origins == "https://a.example.com,https://b.example.com"
