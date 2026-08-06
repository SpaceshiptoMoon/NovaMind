"""
PromptProvider 宿主适配器，包装 PromptManager 供引擎模块经端口注入取模板。
"""
from typing import Any

from novamind.engines.ports import PromptProvider


class HostPromptProvider:
    """PromptProvider 宿主实现：委托 PromptManager 类级注册表。"""

    def get(self, key: str) -> str:
        from novamind.shared.prompts import PromptManager

        return PromptManager.get_template(key)

    def format(self, key: str, **kwargs: Any) -> str:
        from novamind.shared.prompts import PromptManager

        return PromptManager.format_prompt(key, **kwargs)


def as_prompt_provider() -> PromptProvider:
    """构造 PromptProvider 实例。"""
    return HostPromptProvider()  # type: ignore[return-value]