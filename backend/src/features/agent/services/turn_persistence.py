"""对话轮次落库状态板（单聊/群聊共用）。

自 chat_service 独立：事件落库 mixin 与主服务双向引用其类型注解，
独立模块避免循环 import。不进 ToolContext——工具与引擎不可见。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnPersistence:
    """单次对话请求的落库状态板（单聊/群聊共用，不进 ToolContext）。

    接替原 context dict 上的 11 个服务层状态 key（current_iteration/plan_*/
    assistant_msg_id/tc_*）——这些是事件处理与持久化的中间状态，工具与引擎
    均不可见，与端口容器（ToolContext）职责正交。
    """

    iteration: int | None = None
    """当前 ReAct 轮号（1-based），随带 iteration 的事件推进，落库打标用。"""
    assistant_msg_id: int | None = None
    """本轮 assistant 决策消息 id（tool_call 记录关联锚点）。"""
    tool_call_ids: dict[str, int] = field(default_factory=dict)
    """call_id → agent_tool_calls.id 映射（tool_result 回写关联）。"""
    plan_msg_id: int | None = None
    """plan 消息 id（计划状态持久化锚点，仅计划模式）。"""
    plan_state: dict[str, Any] | None = None
    """计划单一事实源（title/steps/statuses/summary），经 update_extra 持久化。"""
    plan_step_index: int | None = None
    """当前执行中的计划步骤下标。"""
    plan_finalizing: bool = False
    """plan.completed 已发出：后续 done 为外层收尾（落最终 summary）。"""
    plan_iter_offset: int = 0
    """计划模式轮号偏移（内层引擎每步从 1 重计数，加偏移全局连续化）。"""
