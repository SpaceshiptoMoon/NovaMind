"""
``PromptProvider`` 跨引擎端口的默认宿主适配器。

包装宿主侧 ``PromptManager``（``shared.prompts.templates``）供所有消费引擎取模板。
``PromptManager`` 是 ``@classmethod`` 注册表且方法名为 ``get_template``/``format_prompt``，
不直接满足 ``PromptProvider``（``get``/``format`` 实例方法），故保留一层薄 adapter，
由各 feature 装配点调 ``as_prompt_provider`` 注入。

归属说明：``HostPromptProvider`` 不接任何 host 具体依赖（不 import setting/ORM/features），
仅委托 ``PromptManager`` 类级注册表，是 ``PromptProvider``（``engines.ports``）的**默认实现**，
被 evaluation/skill/agent/app/qa 多 feature 共用、无单一 owner feature。此前置于
``shared/prompts/host_prompt_provider.py`` 造成 shared → engines 反向依赖（违反分层铁律），
故收口到 engines 顶层：engines → shared PromptManager 合法；shared 不再触碰 engines。
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


__all__ = ["HostPromptProvider", "as_prompt_provider"]