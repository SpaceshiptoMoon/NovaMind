"""回归门禁：全显式配置模型——default.yaml 只引用变量，.env 定义一切。

锁定 2026-10 配置架构两轮收敛（f5e1dab 单 yaml 化 → 全显式化）后的语义：
- yaml 占位符不内建环境差异默认值：未定义变量 → None（缺失显性化，不静默兜底）
- 已定义变量（含显式空串）按值使用；整串占位符 true/false/null 归一为 bool/None
- 显式默认值语法 ${VAR:默认值} 仍被 loader 支持（yaml 现不使用，保留语法能力）
- 占位符嵌入更长字符串时未设变量替换为空串（字符串上下文无法表达 None）
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
    '  enabled: "${REDIS_ENABLED}"\n'
    '  host: "${REDIS_HOST}"\n'
    "es:\n"
    "  hosts:\n"
    '    - "${ES_HOST}"\n'
    '  username: "${ES_USERNAME}"\n'
    '  password: "${ES_PASSWORD}"\n'
    'legacy: "${WITH_DEFAULT:127.0.0.1}"\n'
    'mixed: "scheme://${ES_HOST}/v"\n'
)

VARS = ("REDIS_ENABLED", "REDIS_HOST", "ES_HOST", "ES_USERNAME", "ES_PASSWORD", "WITH_DEFAULT")


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """隔离的配置目录：只写 default.yaml。

    同时把 _load_dotenv 打桩为空操作——loader 固定读真实仓库根 .env，
    本机 .env 里的同名变量（如 REDIS_ENABLED）会污染缺失/默认值断言。
    """
    monkeypatch.setattr(ConfigLoader, "_load_dotenv", lambda self: None)
    for var in VARS:
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "default.yaml").write_text(YAML, encoding="utf-8")
    return tmp_path


def test_undefined_variable_becomes_none(config_dir):
    """未定义变量 → None（缺失显性化）：连接类字段缺失在客户端构造处即报错。"""
    c = ConfigLoader(config_dir=config_dir).load("development")
    assert c["redis"]["enabled"] is None
    assert c["redis"]["host"] is None
    assert c["es"]["hosts"] == [None]
    assert c["es"]["username"] is None


def test_defined_variables_used_as_is(config_dir, monkeypatch):
    """正用例：.env/进程变量定义的值按原样使用；整串 true/false 归一为 bool。"""
    monkeypatch.setenv("REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("ES_HOST", "http://elasticsearch:9200")
    monkeypatch.setenv("ES_USERNAME", "")  # 空串 = ES 客户端 falsy 短路免认证
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["redis"]["enabled"] is True
    assert c["redis"]["host"] == "redis"
    assert c["es"]["hosts"] == ["http://elasticsearch:9200"]
    assert c["es"]["username"] == ""


def test_null_coercion_and_embedded_placeholder(config_dir, monkeypatch):
    """"null" 归一为 None；嵌入串占位符不归一，未设变量替换为空串。"""
    monkeypatch.setenv("ES_PASSWORD", "null")
    monkeypatch.setenv("ES_HOST", "http://elasticsearch:9200")
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["es"]["password"] is None
    assert c["mixed"] == "scheme://http://elasticsearch:9200/v"


def test_explicit_default_syntax_still_supported(config_dir):
    """${VAR:默认值} 语法能力保留（yaml 现不使用）：未设变量回落显式默认值。"""
    c = ConfigLoader(config_dir=config_dir).load("development")
    assert c["legacy"] == "127.0.0.1"


def test_env_yaml_and_local_yaml_are_ignored(config_dir):
    """负向锁：合并层已删除——docker.yaml/local.yaml 存在也绝不能参与加载。"""
    (config_dir / "docker.yaml").write_text("redis:\n  host: evil\n", encoding="utf-8")
    (config_dir / "local.yaml").write_text("cors_origins: evil\n", encoding="utf-8")
    c = ConfigLoader(config_dir=config_dir).load("docker")
    assert c["redis"]["host"] is None
    assert "cors_origins" not in c


def test_environment_key_comes_from_argument(config_dir):
    """environment 键来自 load 参数（生产门控消费方依赖），与 yaml 文件无关。"""
    assert ConfigLoader(config_dir=config_dir).load("production")["environment"] == "production"
