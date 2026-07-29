"""
提示词注册表（纯机制，零 feature 依赖）

本模块只提供注册表机制：`register(TEMPLATES)` 写入、`get_template/format_prompt`
读取。它 **不 import 任何 feature** 的提示词数据——这是引擎可抽离的前提：
`shared/` 层不能反向依赖 `features/`。

提示词数据的注册由宿主启动层（`core/middleware/startup_manager._register_prompt_templates`）
在应用生命周期启动时完成，该层合法地 import 各 feature 的 `*_prompts.TEMPLATES`。

历史：本注册表原位于 `shared/prompts/templates.py` 的 `PromptManager`，其
`_ensure_loaded` 方法反向 import 8 个 feature 模块，构成 shared→features 分层违规。
现拆分为「纯机制（本文件）+ 数据注册（startup 层）」两段，消除该违规。
"""
from __future__ import annotations

from __future__ import annotations


class PromptManager:
    """提示词管理器（纯注册表）

    线程安全性：注册发生在应用启动期（单线程 lifespan），读发生在请求期；
    `_templates` 为类级 dict，CPython GIL 下注册/读不产生竞争。注册幂等：
    同键后注册者覆盖先注册者，重复注册同一份 TEMPLATES 无副作用。
    """

    _templates: dict[str, str] = {}

    @classmethod
    def register(cls, templates: dict[str, str]) -> None:
        """注册一批提示词模板（合并到全局表，幂等）。

        由宿主 startup 层在各 feature 初始化时调用，把该 feature 的
        `*_prompts.TEMPLATES` 注入全局表。
        """
        cls._templates.update(templates)

    @classmethod
    def is_registered(cls, key: str) -> bool:
        return key in cls._templates

    @classmethod
    def get_template(cls, template_name: str) -> str:
        """获取提示词模板；键不存在抛 ValueError。"""
        if template_name not in cls._templates:
            raise ValueError(f"模板 '{template_name}' 不存在")
        return cls._templates[template_name]

    @classmethod
    def format_prompt(cls, template_name: str, **kwargs: str) -> str:
        """格式化提示词；键不存在或缺参抛 ValueError。"""
        template = cls.get_template(template_name)
        try:
            return template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"模板 '{template_name}' 缺少参数: {e}") from None


# 便捷函数
def get_prompt(template_name: str) -> str:
    """获取提示词模板"""
    return PromptManager.get_template(template_name)


def format_prompt(template_name: str, **kwargs: str) -> str:
    """格式化提示词"""
    return PromptManager.format_prompt(template_name, **kwargs)


__all__ = ["PromptManager", "format_prompt", "get_prompt"]