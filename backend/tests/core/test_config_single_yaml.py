"""回归门禁：配置分工——凭据 .env 显式定义，连接参数 yaml 基线 + compose 覆盖。

锁定 2026-10 配置架构三轮收敛后的最终语义：
- 纯 ${VAR}（凭据类，yaml 不带默认值）：未定义 → None（缺失显性化，不静默兜底）
- ${VAR:基线}（连接类）：未定义 → 基线默认值（本地开发零配置）；整串
  true/false/null 归一为 bool/None；嵌入串纯文本替换、未设替换空串
- compose environment 注入优先于 env_file（Docker 连接值路径）
- <环境>.yaml / local.yaml 合并层已删除：同名文件存在也必须被忽略
- environment 键始终来自 load 参数/ENVIRONMENT 变量，供生产门控消费
"""
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from novamind.setting.yaml_config.loader import ConfigLoader

pytestmark = pytest.mark.unit

YAML = (
    "security:\n"
    '  secret_key: "${SECRET_KEY}"\n'      # 凭据类：无基线，缺失 → None
    "redis:\n"
    '  enabled: "${REDIS_ENABLED:true}"\n'  # 连接类：本地基线
    '  host: "${REDIS_HOST:127.0.0.1}"\n'
    "es:\n"
    "  hosts:\n"
    '    - "${ES_HOST:http://127.0.0.1:9200}"\n'
    '  username: "${ES_USERNAME:elastic}"\n'
    '  password: "${ES_PASSWORD:}"\n'
    'mixed: "scheme://${ES_HOST:x}/v"\n'
)

VARS = ("SECRET_KEY", "REDIS_ENABLED", "REDIS_HOST", "ES_HOST", "ES_USERNAME", "ES_PASSWORD")


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
    c = ConfigLoader(config_dir=config_dir).load("development")
    assert c["security"]["secret_key"] is None


def test_connection_params_fall_back_to_yaml_baseline(config_dir):
    """连接类未定义 → yaml 基线默认值（本地开发零配置）；bool 基线归一为 True。"""
    c = ConfigLoader(config_dir=config_dir).load("development")
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
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["redis"]["host"] == "redis"
    assert c["es"]["hosts"] == ["http://elasticsearch:9200"]
    assert c["es"]["username"] == ""


def test_defined_credential_used_and_null_coercion(config_dir, monkeypatch):
    """已定义凭据按值使用；"null" 归一为 None。"""
    monkeypatch.setenv("SECRET_KEY", "real-secret")
    monkeypatch.setenv("ES_PASSWORD", "null")
    c = ConfigLoader(config_dir=config_dir).load("development")
    assert c["security"]["secret_key"] == "real-secret"
    assert c["es"]["password"] is None


def test_env_yaml_and_local_yaml_are_ignored(config_dir):
    """负向锁：合并层已删除——docker.yaml/local.yaml 存在也绝不能参与加载。"""
    (config_dir / "docker.yaml").write_text("redis:\n  host: evil\n", encoding="utf-8")
    (config_dir / "local.yaml").write_text("cors_origins: evil\n", encoding="utf-8")
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["redis"]["host"] == "127.0.0.1"
    assert "cors_origins" not in c


def test_environment_key_comes_from_argument(config_dir):
    """environment 键来自 load 参数（生产门控消费方依赖），与 yaml 文件无关。"""
    assert ConfigLoader(config_dir=config_dir).load("production")["environment"] == "production"
