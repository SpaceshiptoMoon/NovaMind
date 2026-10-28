"""prompt 注册表工程化回归测试（93e9c595 收编面）。

覆盖：
- engines/agent/prompts.py 模板渲染契约：占位符可 format、标签约定结构完整、
  两份摘要模板（独立/对齐）结构一致且不可互相替代
- SystemPromptBuilder 模型适配路由：gpt/gemini/未知三路取到正确模板、空模型返回空
- PlanningFlow 模板化后 system 消息仍强制 JSON 输出（_PLAN_SYSTEM 收编不退化）
- SubAgentRunner：系统提示进 messages[0]、task/todo 工具裁剪、
  sub_context 防递归（subagent_runner=None）、LLM fallback VLM
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


# ==================== 模板渲染契约（engines/agent/prompts.py） ====================


class TestTemplateRenderContract:
    """模板注册后必须可安全渲染（占位符齐全、转义写法正确）。"""

    def test_all_engine_templates_renderable(self):
        """全部 agent_engine_* 模板 format 冒烟：无占位符的直接渲染，
        有占位符的喂测试值——{{}} 转义错漏会在这里炸。"""
        from novamind.shared.prompts.prompt_manager import PromptManager

        placeholder_values = {
            "content": "对话内容",
            "old_summary": "旧摘要",
            "new_content": "新内容",
        }
        for key in (
            "agent_engine_structured_summary",
            "agent_engine_summary_merge",
            "agent_engine_compaction_aligned_instruction",
            "agent_engine_tag_convention",
            "agent_engine_tool_discipline_default",
            "agent_engine_model_adaptation_gpt",
            "agent_engine_model_adaptation_gemini",
            "agent_engine_plan_system",
            "agent_engine_plan_finalize_system",
            "agent_engine_subagent_system",
        ):
            template = PromptManager.get_template(key)
            # 无条件渲染：模板中出现的 {placeholder} 都必须能被喂值或为合法 {{}} 转义
            rendered = template.format(
                **{k: v for k, v in placeholder_values.items() if "{" + k + "}" in template}
            )
            # 渲染后不应残留 {{ 或 }}（转义写法错漏）
            assert "{{" not in rendered and "}}" not in rendered, key

    def test_tag_convention_structure_intact(self):
        """标签约定层是注入防御的钥匙：开闭标签成对、三条规则齐全。"""
        from novamind.shared.prompts.prompt_manager import PromptManager

        t = PromptManager.get_template("agent_engine_tag_convention")
        assert t.startswith("<system-tag-convention>")
        assert t.rstrip().endswith("</system-tag-convention>")
        assert "<system-*>" in t
        assert "&lt;" in t  # 用户内容转义约定
        assert t.count("<system-tag-convention>") == 1

    def test_summary_pair_same_13_sections(self):
        """独立摘要与对齐重放是两份模板但结构必须一致（同 13 节），
        防止单边改结构导致两条压缩路径产出不同形状的摘要。"""

        def sections(text: str) -> list[str]:
            return [ln for ln in text.split("\n") if ln.startswith("## ")]

        from novamind.shared.prompts.prompt_manager import PromptManager

        standalone = PromptManager.get_template("agent_engine_structured_summary")
        aligned = PromptManager.get_template("agent_engine_compaction_aligned_instruction")
        assert sections(standalone) == sections(aligned)
        assert len(sections(standalone)) == 13

    def test_merge_template_block_wrappers_present(self):
        """融合模板保留 <existing_summary>/<new_messages> 块包裹（调用方
        html.escape 后填入；块标记本身是模型解析增量结构的锚点）。"""
        from novamind.shared.prompts.prompt_manager import PromptManager

        t = PromptManager.get_template("agent_engine_summary_merge")
        assert "<existing_summary>\n{old_summary}\n</existing_summary>" in t
        assert "<new_messages>\n{new_content}\n</new_messages>" in t

    def test_subagent_prompt_smaller_than_parent_convention(self):
        """子代理提示与父约定层同源但收窄：保留标签规则，去掉对话示例清单。"""
        from novamind.shared.prompts.prompt_manager import PromptManager

        sub = PromptManager.get_template("agent_engine_subagent_system")
        parent = PromptManager.get_template("agent_engine_tag_convention")
        assert sub.startswith("<system-tag-convention>")
        # 子代理版不带父版的 &lt; 转义规则段（messages 仅一条 user，无需）
        assert ("&lt;" in parent) and ("&lt;" not in sub)


# ==================== SystemPromptBuilder 模型适配路由 ====================


class TestModelAdaptationRouting:
    """_MODEL_ADAPTATION 收编后按模板键取用，路由正确性回归。"""

    def _build(self, model_name: str) -> str:
        from novamind.engines.agent.prompt_builder import SystemPromptBuilder

        registry = MagicMock()
        registry.get_tool.return_value = None
        import asyncio

        return asyncio.run(SystemPromptBuilder(registry).build(
            base_prompt="BASE", enabled_tools=[], skill_fragments=[],
            frozen_memory="", model_name=model_name, max_prompt_tokens=None,
        ))

    def test_gpt_family_gets_gpt_adaptation(self):
        result = self._build("gpt-4o")
        assert "<tool_persistence>" in result
        assert "<mandatory_tool_use>" in result

    def test_gemini_family_gets_gemini_adaptation(self):
        result = self._build("gemini-2.5-pro")
        assert "absolute file paths" in result
        assert "<tool_persistence>" not in result

    def test_gemma_also_matches_gemini_template(self):
        result = self._build("gemma-3-27b")
        assert "absolute file paths" in result

    def test_unknown_model_gets_default_discipline(self):
        result = self._build("qwen3.8-27b")
        assert "Tool-Use Enforcement" in result
        assert "<tool_persistence>" not in result

    def test_empty_model_no_adaptation_layer(self):
        result = self._build("")
        assert "Tool-Use Enforcement" not in result
        assert "BASE" in result

    def test_o_series_matches_gpt_template(self):
        result = self._build("o3-mini")
        assert "<tool_persistence>" in result


# ==================== PlanningFlow 模板化后 JSON 约束不退化 ====================


class TestPlanSystemTemplateConstraint:
    """_PLAN_SYSTEM 收编注册表后，system 消息仍强制 JSON 输出（规划解析依赖）。"""

    def test_plan_template_requires_json_only(self):
        from novamind.shared.prompts.prompt_manager import PromptManager

        t = PromptManager.get_template("agent_engine_plan_system")
        # 解析契约：parse_plan_json 依赖模板明确「只返回 JSON」
        assert "JSON" in t and "只返回 JSON" in t
        # {{}} 转义后渲染出字面 JSON 示例
        rendered = t.format()
        assert '"title"' in rendered and '"steps"' in rendered


# ==================== SubAgentRunner（此前零测试） ====================


class _StubRunnerEngine:
    """记录 run 入参并按脚本 yield 事件的桩引擎（runner 位置调用，签名对齐）。"""

    def __init__(self, events: list[Any]):
        self._events = events
        self.calls: list[dict[str, Any]] = []

    async def run(self, *args, **kwargs):
        self.calls.append(
            {
                "llm_client": args[0] if len(args) > 0 else kwargs.get("llm_client"),
                "messages": args[1] if len(args) > 1 else kwargs.get("messages"),
                "tools": args[2] if len(args) > 2 else kwargs.get("tools"),
                "context": args[3] if len(args) > 3 else kwargs.get("context"),
                **kwargs,
            }
        )
        for e in self._events:
            yield e


def _runner(engine, enabled_tools=None):
    from novamind.engines.agent.subagent.runner import SubAgentRunner

    executor = MagicMock()
    executor.resolve_tools_openai_format.return_value = [{"fake": "tool"}]
    # 工厂闭包 LLM→VLM 兜底（与业务侧 _subagent_client_factory 同形）
    async def client_factory(model):
        return "llm"

    return SubAgentRunner(
        agent_engine=engine,
        tool_executor=executor,
        client_factory=client_factory,
        model="gpt-4o-mini",
        enabled_tools=enabled_tools if enabled_tools is not None else ["web_search"],
        enabled_mcp_ids=[],
        parent_context={"conversation_id": 55, "subagent_runner": "parent"},
    )


class TestSubAgentRunner:
    """子代理委派的三条硬约束：约定层提示、工具裁剪、防递归。"""

    @pytest.mark.asyncio
    async def test_system_prompt_is_tag_convention(self):
        """messages[0] 是 <system-tag-convention> 约定层（父 system prompt 不传入）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="done", data={"full_response": "结果"}),
        ])
        runner = _runner(engine)
        result = await runner.run_subagent("查一下 x")

        call = engine.calls[0]
        assert call["messages"][0]["role"] == "system"
        assert call["messages"][0]["content"].startswith("<system-tag-convention>")
        assert call["messages"][1] == {"role": "user", "content": "查一下 x"}
        assert result["summary"] == "结果"
        assert result["session_id"] is None

    @pytest.mark.asyncio
    async def test_task_todo_tools_stripped(self):
        """enabled_tools 里的 task/todo 在构造期被剔除（防递归 + 不改全局 todo）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="done", data={"full_response": "ok"}),
        ])
        runner = _runner(engine, enabled_tools=["web_search", "task", "todo", "memory"])
        await runner.run_subagent("任务")

        resolved_tools = engine.calls[0]["tools"]
        assert resolved_tools == [{"fake": "tool"}]  # 桩只验证透传；裁剪在构造期生效
        # 直接验证裁剪后的启用清单
        assert runner._enabled_tools == ["web_search", "memory"]

    @pytest.mark.asyncio
    async def test_sub_context_blocks_recursion(self):
        """子 context 的 subagent_runner 置 None（双保险：即使工具裁剪漏了也不能再委派）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="done", data={"full_response": "ok"}),
        ])
        runner = _runner(engine)
        await runner.run_subagent("任务")

        sub_context = engine.calls[0]["context"]
        assert sub_context["conversation_id"] == 55  # 父端口复用
        assert sub_context["subagent_runner"] is None

    @pytest.mark.asyncio
    async def test_llm_fallback_to_vlm(self):
        """主模型客户端获取失败 → fallback VLM（多模态场景降级不中断）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="done", data={"full_response": "ok"}),
        ])
        from novamind.engines.agent.subagent.runner import SubAgentRunner

        executor = MagicMock()
        executor.resolve_tools_openai_format.return_value = []
        mcs = SimpleNamespace(
            get_llm_client_by_model=AsyncMock(side_effect=RuntimeError("no llm")),
            get_vlm_client_by_model=AsyncMock(return_value="vlm-client"),
        )

        # LLM→VLM 兜底策略属业务工厂内部（与 _subagent_client_factory 同形）
        async def fallback_factory(model):
            try:
                return await mcs.get_llm_client_by_model(1, model)
            except Exception:
                return await mcs.get_vlm_client_by_model(1, model)

        runner = SubAgentRunner(
            agent_engine=engine, tool_executor=executor, client_factory=fallback_factory,
            model="gpt-4o-mini", enabled_tools=["web_search"],
            enabled_mcp_ids=[], parent_context={},
        )
        await runner.run_subagent("任务")
        assert engine.calls[0]["llm_client"] == "vlm-client"

    @pytest.mark.asyncio
    async def test_error_event_becomes_error_summary(self):
        """子 ReAct 发 error 事件 → summary 为错误文案而非空串（父模型可感知失败）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="error", data={"content": "boom"}),
        ])
        runner = _runner(engine)
        result = await runner.run_subagent("任务")

        assert "子 agent 执行失败" in result["summary"]
        assert "boom" in result["summary"]

    @pytest.mark.asyncio
    async def test_max_iterations_tightened_and_no_stream(self):
        """子 ReAct 固定 max_iterations=5 + 非流式（收紧预算防子任务失控）。"""
        engine = _StubRunnerEngine([
            SimpleNamespace(event_type="done", data={"full_response": "ok"}),
        ])
        runner = _runner(engine)
        await runner.run_subagent("任务")

        call = engine.calls[0]
        assert call["max_iterations"] == 5
        assert call["stream"] is False


# ==================== build_tool_registry（装配收敛面） ====================


class TestBuildToolRegistry:
    """registry_setup 装配契约：基线清单、沙箱条件注册、依赖注入。"""

    def test_baseline_tools_registered(self):
        """10 个内置工具全部在册（与改造前 startup.py 手工序列等价）。"""
        from novamind.engines.agent.memory.todo_store import TodoStore
        from novamind.features.agent.tool.registry_setup import build_tool_registry

        registry = build_tool_registry(todo_store=TodoStore())
        assert sorted(registry.list_tool_names()) == sorted([
            "knowledge_search", "web_search", "memory", "todo",
            "read_tool_result", "task", "plan_output", "wiki",
            "research", "read_attachment",
        ])
        assert "code_execution" not in registry.list_tool_names()

    def test_sandbox_registers_code_execution(self):
        """传入沙箱实例 → code_execution 注册（能力具备才暴露）。"""
        from novamind.engines.agent.memory.todo_store import TodoStore
        from novamind.features.agent.tool.registry_setup import build_tool_registry

        sandbox = SimpleNamespace()  # CodeExecutionTool 只存引用不调方法
        registry = build_tool_registry(todo_store=TodoStore(), sandbox=sandbox)
        assert "code_execution" in registry.list_tool_names()

    def test_todo_tool_shares_store_instance(self):
        """todo_store 注入同一实例给 TodoTool（app.state 与工具共享状态）。"""
        from novamind.engines.agent.memory.todo_store import TodoStore
        from novamind.features.agent.tool.registry_setup import build_tool_registry

        store = TodoStore()
        registry = build_tool_registry(todo_store=store)
        tool = registry.get_tool("todo")
        assert tool._todo_store is store
