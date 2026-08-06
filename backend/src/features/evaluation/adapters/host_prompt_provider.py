"""
PromptProvider 宿主适配器，包装 PromptManager 供 evaluator 取模板。
"""
from novamind.engines.ports import PromptProvider
from novamind.shared.prompts.templates import PromptManager


class HostPromptProvider:
    """PromptProvider 宿主实现：委托宿主侧 ``PromptManager``。"""

    def get(self, key: str) -> str:
        return PromptManager.get_template(key)

    def format(self, key: str, **kwargs: object) -> str:
        return PromptManager.format_prompt(key, **kwargs)


def as_prompt_provider() -> PromptProvider:
    """构造 PromptProvider 实例（供装配点注入 evaluator）。"""
    return HostPromptProvider()  # type: ignore[return-value]