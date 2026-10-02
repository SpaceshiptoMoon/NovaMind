"""回归门禁：配置加载为两层模型——单 default.yaml + 环境变量（根 .env）。

锁定 2026-10 配置架构收敛（f5e1dab）后的语义，防止回退或漂移：
- 环境差异经 ${VAR:默认值} 占位符表达：未设变量用默认值，已设变量优先
- 整串占位符的 true/false/null 类型归一（bool 配置可经环境变量表达）；
  嵌入更长字符串的占位符不做归一，保持纯文本替换
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
    "redis:\n"
    '  enabled: "${REDIS_ENABLED:false}"\n'
    '  host: "${REDIS_HOST:127.0.0.1}"\n'
    "es:\n"
    "  hosts:\n"
    '    - "${ES_HOST:http://127.0.0.1:9200}"\n'
    '  username: "${ES_USERNAME:elastic}"\n'
    '  password: "${ES_PASSWORD:}"\n'
    "endpoint: \"${MINIO_ENDPOINT:127.0.0.1:9005}\"\n"
    'mixed: "scheme://${ES_HOST:http://x}:9200"\n'
)


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """隔离的配置目录：只写 default.yaml。

    同时把 _load_dotenv 打桩为空操作——loader 固定读真实仓库根 .env，
    本机 .env 里的同名变量（如 REDIS_ENABLED）会污染默认值断言。
    """
    monkeypatch.setattr(ConfigLoader, "_load_dotenv", lambda self: None)
    for var in ("REDIS_ENABLED", "REDIS_HOST", "ES_HOST", "ES_USERNAME", "ES_PASSWORD", "MINIO_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "default.yaml").write_text(YAML, encoding="utf-8")
    return tmp_path


def test_placeholder_defaults_used_when_env_unset(config_dir):
    """反用例：未设环境变量时回落占位符内默认值（本地开发零配置即用）。"""
    c = ConfigLoader(config_dir=config_dir).load("development")
    assert c["redis"]["enabled"] is False
    assert c["redis"]["host"] == "127.0.0.1"
    assert c["es"]["hosts"] == ["http://127.0.0.1:9200"]
    assert c["endpoint"] == "127.0.0.1:9005"


def test_env_overrides_default_and_coerces_bool(config_dir, monkeypatch):
    """正用例：环境变量优先于默认值；true/false 归一为原生 bool（Docker 注入路径）。"""
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("DB_HOST", "mysql")
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["redis"]["enabled"] is True
    # 空串凭据 = ES 客户端 falsy 短路免认证（compose 注入 ES_USERNAME="" 的契约）
    monkeypatch.setenv("ES_USERNAME", "")
    c2 = ConfigLoader(config_dir=config_dir).load("docker")
    assert c2["es"]["username"] == ""


def test_null_coercion_and_embedded_placeholder_stays_string(config_dir, monkeypatch):
    """null 归一为 None；嵌入更长字符串的占位符不做类型归一，纯文本替换。"""
    monkeypatch.setenv("ES_PASSWORD", "null")
    monkeypatch.setenv("ES_HOST", "http://elasticsearch:9200")
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["es"]["password"] is None
    assert c["mixed"] == "scheme://http://elasticsearch:9200:9200"


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
