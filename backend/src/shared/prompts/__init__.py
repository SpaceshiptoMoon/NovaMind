"""
提示词管理模块，导出 PromptTemplate 枚举、PromptManager 注册表及便捷函数。
"""

from novamind.shared.prompts.prompt_manager import (
    PromptManager,
    format_prompt,
    get_prompt,
)
from novamind.shared.prompts.templates import PromptTemplate

__all__ = ["PromptTemplate", "PromptManager", "get_prompt", "format_prompt"]