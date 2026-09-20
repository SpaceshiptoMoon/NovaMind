"""
沙箱配置模型

从 YAML 配置加载沙箱参数
"""

from pydantic import BaseModel

# 默认语言镜像映射
DEFAULT_IMAGES: dict[str, str] = {
    "python": "python:3.12-slim",
    "javascript": "node:20-slim",
    "shell": "bash:5",
}

# 语言对应的文件扩展名
LANGUAGE_EXTENSIONS: dict[str, str] = {
    "python": "py",
    "javascript": "js",
    "shell": "sh",
}


class SandboxConfig(BaseModel):
    """沙箱配置"""

    enabled: bool = False
    max_memory_mb: int = 256
    max_output_bytes: int = 65536
    default_timeout: int = 30
    max_timeout: int = 120
    network_disabled: bool = True
    rebuild_interval: int = 50
    container_prefix: str = "agent_sandbox"
    images: dict[str, str] = DEFAULT_IMAGES.copy()

    @property
    def supported_languages(self) -> list[str]:
        """返回支持的语言列表"""
        return list(self.images.keys())

    @classmethod
    def from_yaml(cls) -> "SandboxConfig":
        """从 YAML 配置（agent.sandbox 段）加载沙箱配置。

        历史上此处误 import 不存在的 ``config_manager`` 模块且 AppConfig 无 agent 段，
        异常被吞导致 YAML 配置从未生效；现已接线（setting/yaml_config loader）。
        配置读取失败（缺 YAML 文件等）仍回退默认值。
        """
        try:
            from novamind.setting.yaml_config import get_config

            sandbox = get_config().agent.sandbox
            return cls(
                enabled=sandbox.enabled,
                max_memory_mb=sandbox.max_memory_mb,
                max_output_bytes=sandbox.max_output_bytes,
                default_timeout=sandbox.default_timeout,
                max_timeout=sandbox.max_timeout,
                network_disabled=sandbox.network_disabled,
                rebuild_interval=sandbox.rebuild_interval,
                container_prefix=sandbox.container_prefix,
                images=dict(sandbox.images),
            )
        except Exception:
            return cls()
