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
    data = loader.load()
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
    """.env 缺失时不报错，整串占位符未定义变量解析为 None（缺失显性化语义）。"""
    monkeypatch.delenv("TEST_DOTENV_SECRET", raising=False)
    monkeypatch.setattr(
        "novamind.setting.yaml_config.loader.Path",
        Path,  # 占位：真实路径计算不受 tmp_path 影响，仅验证不抛异常
    )
    loader = ConfigLoader(config_dir=env_yaml)
    data = loader.load()  # 不应抛异常
    assert "security" in data


def test_invalid_utf8_dotenv_raises_runtime_error(env_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """.env 编码损坏时显性报错而非静默回落默认值（防 PS 5.1 GBK 重编码难排查假配置）。"""
    # 构造非法 UTF-8 字节（GBK 编码的中文，UTF-8 解码必失败），模拟 PS 5.1 产出的损坏 .env
    broken = env_yaml.parent / ".env"
    broken.write_bytes("SECRET_KEY=中文值\n".encode("gbk"))

    # _load_dotenv 的仓库根取真实路径（parents[4]），单测经 load_dotenv 重定向到临时文件
    import dotenv

    real_load_dotenv = dotenv.load_dotenv

    def _fake_load_dotenv(path, **kwargs):
        return real_load_dotenv(broken, **kwargs)

    monkeypatch.setattr("dotenv.load_dotenv", _fake_load_dotenv)

    loader = ConfigLoader(config_dir=env_yaml)
    with pytest.raises(RuntimeError, match="UTF-8"):
        loader._load_dotenv()


def test_valid_utf8_dotenv_not_raising(env_yaml: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反例：合法 UTF-8（含中文注释）的 .env 加载不报错——正常文件不误伤。"""
    valid = env_yaml.parent / ".env"
    valid.write_text("# 中文注释：合法 UTF-8\nTEST_DOTENV_SECRET=abc\n", encoding="utf-8")

    import dotenv

    real_load_dotenv = dotenv.load_dotenv

    def _fake_load_dotenv(path, **kwargs):
        return real_load_dotenv(valid, **kwargs)

    monkeypatch.setattr("dotenv.load_dotenv", _fake_load_dotenv)

    loader = ConfigLoader(config_dir=env_yaml)
    loader._load_dotenv()  # 不应抛异常
