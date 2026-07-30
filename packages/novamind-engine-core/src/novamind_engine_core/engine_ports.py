"""
引擎端口协议（临时宿主侧定义）

本模块定义引擎库对外依赖的抽象协议。当前阶段（批次 0-5）这些协议留在宿主
`shared/` 下，供宿主代码与即将端口化的引擎代码面向接口编程；批次 6 物理抽包时，
本文件整体迁入 `novamind-engine-core/ports.py`，引擎库只依赖该协议包，
不再 import `novamind.core.middleware.structured_logging` 或
`novamind_engine_core.prompts`。

设计约束：
  - 协议只描述引擎所需的能力，不携带任何 NovaMind 业务实体（ORM/枚举/配置键）。
  - 引擎构造器接收这些协议的实例；宿主在装配时注入实现。
  - 依赖方向：宿主 -> 引擎 -> 本协议；引擎 ✗-> 宿主 features/setting。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Protocol, runtime_checkable

if TYPE_CHECKING:
    # 仅用于类型注解（配合 `from __future__ import annotations` 惰性求值），
    # 避免 engine_ports 顶部强 import ai_models（批次 6 同迁 engine-core）。
    from novamind_engine_core.ai_models.base_model import BaseLLM


@runtime_checkable
class Logger(Protocol):
    """结构化日志协议，对齐 structlog BoundLogger 的调用形态。

    引擎内模块级不再直接 `get_logger(...)`，而是在构造器接收一个 Logger 实例。
    宿主侧把 `structured_logging.get_logger(name)` 返回的 BoundLogger 直接注入
    （structlog BoundLogger 满足该 Protocol 的方法签名，duck-type 兼容）。

    注意：structlog 的方法是 `info(event: str, **kw)`，而非 stdlib 的
    `info("msg %s", arg)`，本协议与之对齐。
    """

    def debug(self, event: str, **kwargs: Any) -> None: ...

    def info(self, event: str, **kwargs: Any) -> None: ...

    def warning(self, event: str, **kwargs: Any) -> None: ...

    def error(self, event: str, **kwargs: Any) -> None: ...


@runtime_checkable
class PromptProvider(Protocol):
    """提示词模板提供者协议。

    引擎通过字符串键取模板，**不 import 业务枚举**（如 PromptTemplate）。
    键的命名约定由各 feature 的 `*_prompts.py` 定义，宿主在装配时把
    `PromptManager` 实现注入引擎。

    设计决策（与 REFACTOR-qa-rag-pipeline 对齐）：键用字符串字面量，避免
    引擎库反向依赖宿主的提示词枚举，从而切断引擎 -> features 的导入边。
    """

    def get(self, key: str) -> str:
        """按键取原始模板字符串；键不存在应抛 ValueError。"""
        ...

    def format(self, key: str, **kwargs: Any) -> str:
        """按键取模板并用 kwargs 填充；缺参或键不存在应抛 ValueError。"""
        ...


@runtime_checkable
class FallbackLLMProvider(Protocol):
    """降级 LLM 提供者协议。

    引擎在主模型重试耗尽后，经此端口取用户其他可用 LLM 客户端做降级调用，
    不再直接 import ``user.services.model_config_service.ModelConfigService``
    （切断引擎 -> user feature 导入边；ModelConfigService 全量端口化见批次 5b/任务#36）。

    ``exclude_model`` 为当前主模型名，加载结果应排除之，避免降级回主模型。
    """

    async def load_fallback_clients(
        self, user_id: int, exclude_model: str
    ) -> List["BaseLLM"]:
        """加载用户可用的降级 LLM 客户端列表（排除主模型）。"""
        ...


__all__ = ["Logger", "PromptProvider", "FallbackLLMProvider"]