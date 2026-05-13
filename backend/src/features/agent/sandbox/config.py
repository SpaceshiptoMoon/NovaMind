"""
沙箱配置模型

从 YAML 配置加载沙箱参数
"""
from typing import Dict, Optional

from pydantic import BaseModel


# 默认语言镜像映射
DEFAULT_IMAGES: Dict[str, str] = {
    "python": "python:3.12-slim",
    "javascript": "node:20-slim",
    "shell": "bash:5",
}

# 语言对应的文件扩展名
LANGUAGE_EXTENSIONS: Dict[str, str] = {
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
    images: Dict[str, str] = DEFAULT_IMAGES.copy()

    @property
    def supported_languages(self) -> list[str]:
        """返回支持的语言列表"""
        return list(self.images.keys())

    @classmethod
    def from_yaml(cls) -> "SandboxConfig":
        """从 YAML 配置加载沙箱配置"""
        try:
            from src.setting.yaml_config.config_manager import get_config

            config = get_config()
            agent_config = getattr(config, "agent", None)

            if agent_config is None:
                return cls()

            # agent_config 可能是 dict 或对象
            if isinstance(agent_config, dict):
                sandbox_dict = agent_config.get("sandbox", {})
            else:
                sandbox_dict = getattr(agent_config, "sandbox", None)
                if sandbox_dict is None:
                    return cls()
                if isinstance(sandbox_dict, dict):
                    pass
                else:
                    # 尝试转为 dict
                    sandbox_dict = (
                        vars(sandbox_dict) if hasattr(sandbox_dict, "__dict__") else {}
                    )

            return cls(**sandbox_dict)
        except Exception:
            return cls()
