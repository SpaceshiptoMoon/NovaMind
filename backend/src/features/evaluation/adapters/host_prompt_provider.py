"""
PromptProvider 宿主适配器

把宿主侧 `shared.prompts.PromptManager` 包成引擎端口 `PromptProvider` 实例，
供 evaluation 的 evaluator 经构造器注入。evaluator 不再 import 业务侧
`PromptManager`，切断引擎 -> shared.prompts 的直接导入边（批次 6 抽包前提）。
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