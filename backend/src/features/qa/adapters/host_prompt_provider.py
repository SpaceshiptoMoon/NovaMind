"""PromptProvider 宿主适配器（qa 模块）。

把宿主侧 ``shared.prompts.PromptManager`` 包成引擎端口 ``PromptProvider`` 实例，
供 ``GradeRetrier``（已迁 ``engines/rag/``）经构造器注入。引擎不再直接 import
``shared.prompts.PromptManager``，切断引擎 -> 宿主 prompt 注册表导入边。
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
    """构造 PromptProvider 实例（供装配点注入 GradeRetrier）。"""
    return HostPromptProvider()  # type: ignore[return-value]