"""提示词管理模块

导出：
  - PromptTemplate：键名字面量枚举（过渡，批次 0 子任务 3 替换为字符串字面量）
  - PromptManager：纯注册表（实现于 prompt_manager.py，零 feature 依赖）
  - get_prompt / format_prompt：便捷函数
"""

from novamind.shared.prompts.prompt_manager import (
    PromptManager,
    format_prompt,
    get_prompt,
)
from novamind.shared.prompts.templates import PromptTemplate

__all__ = ["PromptTemplate", "PromptManager", "get_prompt", "format_prompt"]