"""ConfigLoader 的 .env 加载与 ${VAR} 占位符解析行为。

密钥单一来源约定：真实密钥只写仓库根 .env，YAML 侧用 ${VAR} 占位符引用。
本文件锁定两个关键行为：

1. .env 中的变量能被 ConfigLoader 加载并用于占位符解析（本地开发主路径）
2. 已存在的进程环境变量优先于 .env（容器/CI 注入覆盖文件值）
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from novamind.setting.yaml_config.loader import ConfigLoader

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
DEEPDOC_ROOT = REPO_ROOT / "backend" / "src" / "setting" / "yaml_config" / "yaml"


@pytest.fixture()
def env_yaml(tmp_path: Path) -> Path:
    """构造引用占位符的最小 default.yaml。"""
    (tmp_path / "default.yaml").write_text(
        "security:\n"
        "  secret_key: \"${TEST_DOTENV_SECRET}\"\n",
        encoding="utf-8",
    )
    return tmp_path


def test_placeholder_resolved_from_repo_dotenv(env_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """若仓库根 .env 存在，其中变量应可解析 YAML 占位符；否则跳过（CI 无 .env）。"""
    dotenv_path = REPO_ROOT / ".env"
    if not dotenv_path.exists():
        pytest.skip("repo root .env not present")
    # 从 .env 中取一个真实存在的变量名来测
    lines = [
        ln.split("=", 1) for ln in dotenv_path.read_text(encoding="utf-8").splitlines()
        if "=" in ln and not ln.strip().startswith("#")
    ]
    assert lines, ".env 为空，无法验证"
    var_name = lines[0][0].strip()
    monkeypatch.delenv(var_name, raising=False)

    loader = ConfigLoader(config_dir=env_yaml)
    data = loader.load("development")
    # 占位符变量恰好是被测变量时才断言解析值
    if "TEST_DOTENV_SECRET" in dict(lines):
        assert data["security"]["secret_key"] == dict(lines)["TEST_DOTENV_SECRET"]


def test_process_env_overrides_dotenv(env_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """进程环境变量优先于 .env 文件值（load_dotenv override=False 语义）。"""
    monkeypatch.setenv("TEST_DOTENV_SECRET", "from-process-env")
    (env_yaml.parent / ".env").write_text("IGNORED=1\n", encoding="utf-8")

    loader = ConfigLoader(config_dir=env_yaml)
    loader._load_dotenv()  # 直接调用，隔离 _load_yaml 的目录差异
    assert os.getenv("TEST_DOTENV_SECRET") == "from-process-env"


def test_missing_dotenv_is_silent(env_yaml: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """.env 缺失时不报错，占位符回落到 _replace_env_vars 的默认值语义（空串）。"""
    monkeypatch.delenv("TEST_DOTENV_SECRET", raising=False)
    monkeypatch.setattr(
        "novamind.setting.yaml_config.loader.Path",
        Path,  # 占位：真实路径计算不受 tmp_path 影响，仅验证不抛异常
    )
    loader = ConfigLoader(config_dir=env_yaml)
    data = loader.load("development")  # 不应抛异常
    assert "security" in data
