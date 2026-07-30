"""
PromptProvider 宿主适配器

包 `shared.prompts.prompt_manager.PromptManager`（纯注册表），实现引擎
`PromptProvider` 协议。引擎内模块（如 LongTermMemory）不再直接 import
`shared.prompts`，改经注入的 PromptProvider 用字符串键取模板。

依赖方向：本适配器属宿主层，可 import shared.prompts；引擎层只依赖
`shared.engine_ports.PromptProvider` 协议。
"""
from typing import Any

from novamind_engine_core.engine_ports import PromptProvider


class HostPromptProvider:
    """PromptProvider 宿主实现：委托 PromptManager 类级注册表。"""

    def get(self, key: str) -> str:
        from novamind_engine_core.prompts import PromptManager

        return PromptManager.get_template(key)

    def format(self, key: str, **kwargs: Any) -> str:
        from novamind_engine_core.prompts import PromptManager

        return PromptManager.format_prompt(key, **kwargs)


def as_prompt_provider() -> PromptProvider:
    """构造 PromptProvider 实例。"""
    return HostPromptProvider()  # type: ignore[return-value]