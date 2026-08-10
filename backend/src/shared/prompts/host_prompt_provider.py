"""
PromptProvider 宿主适配器（共享）：包装 ``PromptManager`` 供所有消费引擎取模板。

此前 agent/app/evaluation/skill/qa 各持一份逐字等价的 ``HostPromptProvider``，
统一收口到 shared 一份。``PromptManager`` 是 ``@classmethod`` 注册表且方法名为
``get_template``/``format_prompt``，不直接满足 ``PromptProvider``（``get``/``format``
实例方法），故保留一层薄 adapter，由各 feature 装配点调 ``as_prompt_provider`` 注入。
"""
from typing import Any

from novamind.engines.ports import PromptProvider
from novamind.shared.prompts.templates import PromptManager


class HostPromptProvider:
    """``PromptProvider`` 宿主实现：委托宿主侧 ``PromptManager`` 类级注册表。"""

    def get(self, key: str) -> str:
        return PromptManager.get_template(key)

    def format(self, key: str, **kwargs: Any) -> str:
        return PromptManager.format_prompt(key, **kwargs)


def as_prompt_provider() -> PromptProvider:
    """构造 ``PromptProvider`` 实例（供各 feature 装配点注入消费引擎）。"""
    return HostPromptProvider()  # type: ignore[return-value]