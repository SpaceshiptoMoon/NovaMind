"""
ClawMate 配置
"""

from typing import List
from pydantic import BaseModel


class ClawMateConfig(BaseModel):
    """ClawMate 模块配置"""

    enabled: bool = True
    default_timeout: int = 30              # 命令执行超时（秒）
    max_output_size: int = 65536           # 输出截断（64KB）
    max_session_idle: int = 600            # session 空闲超时（秒，默认 10 分钟）
    cleanup_interval: int = 60             # 清理检查间隔（秒）
    blocked_commands: List[str] = [        # 危险命令黑名单（保留，作为 command_safety 的补充）
        "rm -rf /", "rm -rf /*",
        "mkfs", "dd if=",
        ":(){ :|:& };:",                    # fork bomb
        "chmod -R 777 /",
        "shutdown", "reboot",
        "init 0", "init 6",
    ]
    write_denied_paths: List[str] = [      # 写入保护路径前缀（已有，file_safety.py 内置更全面的列表）
        "/etc", "/proc", "/sys", "/boot",
        "/root/.ssh",
    ]
    write_denied_files: List[str] = []     # 额外精确文件黑名单
    write_denied_dirs: List[str] = []      # 额外目录前缀黑名单
    write_safe_root: str = ""              # 可选沙盒根目录（环境变量 CLAWMATE_WRITE_SAFE_ROOT 优先）

    @classmethod
    def from_yaml(cls) -> "ClawMateConfig":
        """从 YAML 配置加载"""
        try:
            from src.setting.yaml_config import get_config
            config = get_config()
            clawmate_config = getattr(config, "clawmate", None)

            if clawmate_config is None:
                return cls()

            if isinstance(clawmate_config, dict):
                return cls(**clawmate_config)

            # dataclass → dict
            if hasattr(clawmate_config, "__dict__"):
                return cls(**{
                    k: v for k, v in vars(clawmate_config).items()
                    if not k.startswith("_")
                })

            return cls()
        except Exception:
            return cls()
