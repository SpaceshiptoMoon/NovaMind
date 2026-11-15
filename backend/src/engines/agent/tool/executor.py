"""工具执行器：内置与 MCP 工具统一路由，经 before/after 钩子链执行，钩子异常隔离并带超时保护。"""
import asyncio
import time
from collections import OrderedDict
from typing import Any

from novamind.engines.agent.mcp.client import McpClientManager
from novamind.engines.agent.tool.catalog import LOAD_TOOLS_NAME
from novamind.engines.agent.tool.context import ToolContext
from novamind.engines.agent.tool.definition import ToolDefinition, ToolSource
from novamind.engines.agent.tool.hooks import ToolHook
from novamind.engines.agent.tool.registry import ToolRegistry
from novamind.engines.agent.tool.result import ToolResult, ToolResultStatus
from novamind.shared.logging import get_logger

logger = get_logger(__name__)

MCP_PREFIX = "mcp__"

# 执行失败（非参数校验失败）的纠错指引：带工具用途摘要，模型可对照自查参数
_FAILURE_HINT = (
    "\n\n[工具执行失败，未产生结果。该工具的用途：{desc_summary} "
    "请对照用途检查参数取值是否合理，修正后可重试一次。]"
)
# 连续失败升级指引：同一 (会话, 工具) 连败达到阈值后替换普通指引，
# 阻断「同参数无限重试」循环——这是 agent 失败循环最常见的形态
_ESCALATION_THRESHOLD = 3
_ESCALATION_HINT = (
    "\n\n[该工具在本次会话已连续失败 {count} 次。请勿以相同方式重试："
    "改用其他工具、调整思路达成同一目标，或直接向用户说明该操作无法完成。]"
)


class ToolExecutor:
    """
    工具执行器

    执行流程：
    1. 查找工具定义 → ToolDefinition
    2. 运行 before_hooks（可修改参数或阻止执行）
    3. 路由到实际执行器（builtin / mcp）
    4. 包装为 ToolResult
    5. 运行 after_hooks（可修改结果）
    6. 返回最终 ToolResult
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        mcp_client_manager: McpClientManager,
        hooks: list[ToolHook] | None = None,
    ):
        """注入工具注册表、MCP 管理器与钩子链；工具定义缓存上限 256 条，防长会话无限增长。"""
        self._tool_registry = tool_registry
        self._mcp_manager = mcp_client_manager
        self._hooks = hooks or []
        self._tool_defs: OrderedDict[str, ToolDefinition] = OrderedDict()
        self._tool_defs_max = 256
        # (session_id, tool_name) → 连续执行失败次数；成功即清零。
        # 只统计执行期失败（参数校验失败不走这里），用于升级纠错指引。
        self._consecutive_failures: dict[tuple[str, str], int] = {}
        # 本轮 turn 的 tools 列表引用与按需加载记录（begin_turn 登记，end_turn
        # 清理）。load_tools 激活的工具定义原地追加进该列表——列表引用贯穿
        # agent_engine.run 的迭代循环（无拷贝），追加后本轮后续迭代即见新工具。
        # 跨轮不保留：turn 结束清引用，下一轮从常驻集重新开始（KV-cache 前缀稳定）。
        self._turn_tools: list[dict[str, Any]] | None = None
        self._turn_loaded: set[str] = set()
        self._turn_mcp_ids: list[int] = []

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    # ==================== 按需工具目录（turn 级生命周期） ====================

    def begin_turn(
        self,
        turn_tools: list[dict[str, Any]],
        enabled_mcp_server_ids: list[int] | None = None,
    ) -> None:
        """登记本轮请求的 tools 列表引用（load_tools 激活时原地追加）。

        Args:
            turn_tools: 本轮请求的 OpenAI 格式 tools 列表（引用透传，
                由 chat_context_builder 构造、agent_engine 循环消费）。
            enabled_mcp_server_ids: 本轮授权的 MCP server id 列表
                （load_tools 加载 MCP 工具时的授权边界，防越权加载未启用
                server 的工具）。
        """
        self._turn_tools = turn_tools
        self._turn_loaded = set()
        self._turn_mcp_ids = list(enabled_mcp_server_ids or [])

    def end_turn(self) -> None:
        """清理本轮 tools 引用与已加载记录（防引用悬挂到下一轮）。"""
        self._turn_tools = None
        self._turn_loaded = set()
        self._turn_mcp_ids = []

    def build_mcp_catalog(
        self, server_ids: list[int]
    ) -> list[tuple[str, int, list[str]]]:
        """构建 MCP 目录条目：(server 名, 工具数, 工具名清单)。

        目录模式（默认）下 MCP 工具不直发 schema，只列名字进目录——
        工具名 token 便宜，描述细节由外部 server 的 schema 在 load 后提供。
        """
        entries: list[tuple[str, int, list[str]]] = []
        for server_id in server_ids:
            raws = self._mcp_manager.get_tools_for_servers([server_id])
            names = [
                raw.get("function", {}).get("name", "")
                for raw in raws
                if raw.get("function", {}).get("name")
            ]
            server_name = self._mcp_manager.get_server_name(server_id) or str(server_id)
            entries.append((server_name, len(names), names))
        return entries

    async def _execute_load_tools(
        self, arguments: dict[str, Any]
    ) -> ToolResult:
        """执行 load_tools：解析组名/工具名 → 定义追加进本轮 tools 列表。

        无副作用（只改本轮内存态），不走审批/预算钩子链；结果文本回喂
        模型（已加载清单 / 未知名错误），幂等（重复加载跳过）。
        """
        start = time.time()

        def _finish(content: str, status: ToolResultStatus) -> ToolResult:
            return ToolResult(
                status=status,
                content=content,
                duration_ms=int((time.time() - start) * 1000),
            )

        if self._turn_tools is None:
            return _finish(
                "load_tools 未激活：本轮 turn 未登记 tools 列表（内部状态缺失，"
                "请直接基于已有上下文回答）。",
                ToolResultStatus.ERROR,
            )

        groups = arguments.get("groups") or []
        names = arguments.get("tools") or []
        if not isinstance(groups, list) or not isinstance(names, list):
            return _finish(
                "参数类型错误：groups 与 tools 须为字符串数组。",
                ToolResultStatus.ERROR,
            )

        loaded: list[str] = []
        skipped: list[str] = []
        missing: list[str] = []

        registry = self._tool_registry
        seen_groups: set[str] = set()
        for group in groups:
            group = str(group)
            if group in seen_groups:
                continue
            seen_groups.add(group)
            functions = registry.group_functions(group)
            if not functions:
                missing.append(group)
                continue
            for fn_name in functions:
                self._append_turn_tool(fn_name, loaded, skipped, missing)

        for name in names:
            self._append_turn_tool(str(name), loaded, skipped, missing)

        parts: list[str] = []
        if loaded:
            parts.append(f"Loaded {len(loaded)} tools: {', '.join(loaded)}.")
        if skipped:
            parts.append(
                f"Skipped (already loaded): {', '.join(skipped)}."
            )
        if missing:
            parts.append(
                f"Not found: {', '.join(missing)} — check the names against "
                "the on-demand catalog in the system prompt."
            )
        if not parts:
            return _finish(
                "No groups or tools specified. Pass groups (catalog group "
                "names) and/or tools (specific function names).",
                ToolResultStatus.ERROR,
            )
        return _finish(" ".join(parts), ToolResultStatus.SUCCESS)

    def _append_turn_tool(
        self,
        fn_name: str,
        loaded: list[str],
        skipped: list[str],
        missing: list[str],
    ) -> None:
        """解析单个工具定义并追加进本轮 tools 列表（幂等，失败进 missing）。"""
        if fn_name in self._turn_loaded:
            skipped.append(fn_name)
            return
        tool_def = self._resolve_loadable_definition(fn_name)
        if tool_def is None:
            missing.append(fn_name)
            return
        self._turn_tools.append(tool_def.to_openai_format())
        self._turn_loaded.add(fn_name)
        loaded.append(fn_name)

    def _resolve_loadable_definition(self, fn_name: str) -> ToolDefinition | None:
        """解析可加载的工具定义；内置查注册表，MCP 按 server 名反查缓存。

        MCP 加载校验 turn 级授权边界（begin_turn 登记的 enabled server ids），
        未启用 server 的工具返回 None（防模型借 load 越权访问未授权 server）。
        """
        if fn_name.startswith(MCP_PREFIX):
            parts = fn_name[len(MCP_PREFIX):].split("__", 1)
            if len(parts) != 2:
                return None
            server_name, _original = parts
            server_id = self._mcp_manager.get_server_id_by_name(server_name)
            if server_id is None or server_id not in self._turn_mcp_ids:
                return None
            for raw_tool in self._mcp_manager.get_tools_for_servers([server_id]):
                func = raw_tool.get("function", {})
                if func.get("name") == fn_name:
                    return self._cache_tool_def(
                        fn_name,
                        self._raw_to_definition(
                            raw_tool,
                            ToolSource.MCP,
                            timeout_ms=self._provider_timeout_ms(fn_name),
                        ),
                    )
            return None
        tool_def = self._resolve_tool_definition(fn_name)
        # _resolve_tool_definition 未命中时返回空描述兜底定义——按需加载
        # 语义下空定义即「不存在」，不能把空壳 append 进 tools
        if not tool_def.description and not tool_def.parameters:
            return None
        return tool_def

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """执行工具调用（含超时保护 + 钩子异常隔离）。

        Args:
            tool_name: 工具名（MCP 工具带 mcp__ 前缀）。
            arguments: 工具参数，可被 before 钩子改写。
            context: 强类型执行上下文，透传给工具实现。

        Returns:
            ToolResult：status 为 SUCCESS/TIMEOUT/ERROR，content 或 data 承载结果。
        """
        # load_tools 拦截（在定义解析/参数校验/钩子链之前）：无副作用元工具，
        # 不在注册表内（无 schema 校验需求），执行即改本轮 tools 列表
        if tool_name == LOAD_TOOLS_NAME:
            return await self._execute_load_tools(arguments)

        tool_def = self._resolve_tool_definition(tool_name)
        timeout_sec = tool_def.timeout_ms / 1000.0 if tool_def.timeout_ms else 30.0
        session_id = str(context.session_id or "")

        # 参数 schema 校验（钩子链之前）：畸形参数不进入执行，错误回喂模型自纠
        from novamind.engines.agent.tool.validation import validate_tool_arguments

        validation_error = validate_tool_arguments(tool_def, arguments)
        if validation_error is not None:
            return validation_error

        start = time.time()
        try:
            # before hooks（在 try 内，异常不逃逸）
            for hook in self._hooks:
                modified_args = await hook.before_execute(
                    tool_def, arguments, context
                )
                if modified_args is not None:
                    arguments = modified_args

            # 执行（含超时保护）
            raw_result = await asyncio.wait_for(
                self._route_and_execute(tool_def, arguments, context),
                timeout=timeout_sec,
            )
            status = ToolResultStatus.SUCCESS
            error_message = None
            self._consecutive_failures.pop((session_id, tool_name), None)
        except TimeoutError:
            raw_result = f"工具执行超时（{timeout_sec:.1f}s）"
            status = ToolResultStatus.TIMEOUT
            error_message = raw_result
        except Exception as e:
            raw_result = str(e)
            status = ToolResultStatus.ERROR
            error_message = str(e)

        if status is not ToolResultStatus.SUCCESS:
            raw_result = self._with_failure_guidance(
                tool_def, str(raw_result), status, session_id
            )
            error_message = raw_result if isinstance(error_message, str) else None
            if error_message is not None:
                error_message = raw_result

        duration_ms = int((time.time() - start) * 1000)

        result = ToolResult(
            status=status,
            content=raw_result if isinstance(raw_result, str) else "",
            data=raw_result if isinstance(raw_result, dict) else None,
            duration_ms=duration_ms,
            error_message=error_message,
        )

        # after hooks（异常不逃逸）
        for hook in self._hooks:
            try:
                result = await hook.after_execute(
                    tool_def, arguments, result, context
                )
            except Exception as e:
                logger.warning("after_hook 执行失败", hook=type(hook).__name__, error=str(e))

        return result

    def _with_failure_guidance(
        self,
        tool_def: ToolDefinition,
        raw_error: str,
        status: ToolResultStatus,
        session_id: str,
    ) -> str:
        """执行失败时给错误附加模型可读的纠错指引。

        首次失败带工具用途摘要（模型对照参数自查）；同一 (会话, 工具) 连败
        达阈值后切换为升级指引，阻断同参数无限重试循环。

        Args:
            tool_def: 工具定义（取描述摘要）。
            raw_error: 原始错误文本。
            status: 失败状态（ERROR/TIMEOUT）。
            session_id: 会话 ID（连败计数键的一部分）。

        Returns:
            附加指引后的错误文本。
        """
        key = (session_id, tool_def.name)
        count = self._consecutive_failures.get(key, 0) + 1
        self._consecutive_failures[key] = count
        if count >= _ESCALATION_THRESHOLD:
            guidance = _ESCALATION_HINT.format(count=count)
        else:
            desc = tool_def.description.strip()
            summary = desc.split("\n")[0][:120] if desc else "（无描述）"
            guidance = _FAILURE_HINT.format(desc_summary=summary)
        logger.info(
            "工具执行失败，附加纠错指引",
            tool_name=tool_def.name,
            status=status.value,
            consecutive_failures=count,
        )
        return f"{raw_error}{guidance}"

    def resolve_tools(
        self,
        enabled_tools: list[str],
        enabled_mcp_server_ids: list[int],
        exclude_groups: set[str] | None = None,
    ) -> list[ToolDefinition]:
        """解析完整工具定义列表。

        Args:
            enabled_tools: 启用的内置工具名列表。
            enabled_mcp_server_ids: 启用的 MCP 服务器 ID 列表。
            exclude_groups: 需剔除的目录分组名集合（分组内工具不直发，
                经 load_tools 按需激活）；None/空集全量直发。

        Returns:
            ToolDefinition 列表（内置在前、MCP 在后，按传入顺序）。
        """
        tools: list[ToolDefinition] = []

        # 内置工具
        if enabled_tools:
            for tool_name in enabled_tools:
                if exclude_groups:
                    group = self._tool_registry.group_of(tool_name)
                    if group and group in exclude_groups:
                        continue
                tool = self._tool_registry.get_tool(tool_name)
                if tool:
                    for raw_tool in tool.get_tools():
                        func = raw_tool.get("function", {})
                        name = func.get("name", "")
                        if name not in self._tool_defs:
                            self._cache_tool_def(
                                name,
                                self._raw_to_definition(
                                    raw_tool,
                                    ToolSource.BUILTIN,
                                    timeout_ms=self._provider_timeout_ms(name),
                                ),
                            )
                        tools.append(self._tool_defs[name])

        # MCP 工具
        if enabled_mcp_server_ids:
            for server_id in enabled_mcp_server_ids:
                for raw_tool in self._mcp_manager.get_tools_for_servers(
                    [server_id]
                ):
                    func = raw_tool.get("function", {})
                    name = func.get("name", "")
                    if name not in self._tool_defs:
                        self._cache_tool_def(
                            name,
                            self._raw_to_definition(
                                raw_tool,
                                ToolSource.MCP,
                                timeout_ms=self._provider_timeout_ms(name),
                            ),
                        )
                    tools.append(self._tool_defs[name])

        return tools

    def resolve_tools_openai_format(
        self,
        enabled_tools: list[str],
        enabled_mcp_server_ids: list[int],
        exclude_groups: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """返回 OpenAI function calling 格式。

        Args:
            enabled_tools: 启用的内置工具名列表。
            enabled_mcp_server_ids: 启用的 MCP 服务器 ID 列表。
            exclude_groups: 需剔除的目录分组名集合（不直发，按需加载）。

        Returns:
            OpenAI function calling 格式的 dict 列表。
        """
        tools = self.resolve_tools(
            enabled_tools, enabled_mcp_server_ids, exclude_groups=exclude_groups
        )
        return [t.to_openai_format() for t in tools]

    def _cache_tool_def(self, name: str, tool_def: ToolDefinition) -> ToolDefinition:
        """缓存工具定义（LRU 淘汰）"""
        if name in self._tool_defs:
            self._tool_defs.move_to_end(name)
        else:
            self._tool_defs[name] = tool_def
            if len(self._tool_defs) > self._tool_defs_max:
                self._tool_defs.popitem(last=False)
        return tool_def

    def _resolve_tool_definition(self, tool_name: str) -> ToolDefinition:
        """查找或推断工具定义"""
        if tool_name in self._tool_defs:
            return self._tool_defs[tool_name]
        provider = self._tool_registry.find_tool_provider(tool_name)
        source = ToolSource.MCP if tool_name.startswith(MCP_PREFIX) else ToolSource.BUILTIN
        if provider is not None:
            for raw_tool in provider.get_tools():
                func = raw_tool.get("function", {})
                if func.get("name") == tool_name:
                    tool_def = self._raw_to_definition(
                        raw_tool, source, timeout_ms=self._provider_timeout_ms(tool_name)
                    )
                    return self._cache_tool_def(tool_name, tool_def)
        return ToolDefinition(
            name=tool_name,
            description="",
            source=source,
        )

    async def _route_and_execute(
        self,
        tool_def: ToolDefinition,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> str:
        """路由到实际执行器"""
        if tool_def.name.startswith(MCP_PREFIX):
            return await self._execute_mcp_tool(tool_def.name, arguments)
        else:
            return await self._execute_builtin_tool(
                tool_def.name, arguments, context
            )

    async def _execute_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """执行 MCP 工具"""
        parts = tool_name[len(MCP_PREFIX) :].split("__", 1)
        if len(parts) != 2:
            raise ValueError(f"无效的 MCP 工具名称格式：{tool_name}")
        server_name, original_tool_name = parts
        server_id = self._mcp_manager.get_server_id_by_name(server_name)
        if server_id is None:
            raise ValueError(f"MCP 服务器 '{server_name}' 未连接")
        return await self._mcp_manager.call_tool(
            server_id, original_tool_name, arguments
        )

    async def _execute_builtin_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> str:
        """路由到内置工具实现，异常统一捕获为错误 JSON 返回。"""
        tool = self._tool_registry.find_tool_provider(tool_name)
        if not tool:
            raise ValueError(f"未找到工具 '{tool_name}'")
        return await tool.execute_tool(tool_name, arguments, context)

    # ToolParameter 支持的 schema 约束键（透传给模型 + 校验器；其余键丢弃）
    _SCHEMA_CONSTRAINT_KEYS = (
        "items", "minimum", "maximum", "minLength", "maxLength",
        "minItems", "maxItems",
    )

    @staticmethod
    def _raw_to_definition(
        raw_tool: dict[str, Any], source: ToolSource, timeout_ms: int | None = None
    ) -> ToolDefinition:
        """将 OpenAI 格式工具定义转换为 ToolDefinition。

        MCP 工具的 description/参数描述由外部服务器提供（用户自选启用，仍属
        不可信面）——转义 <system- 前缀，防恶意服务器借 description 下伪系统
        指令（tools schema 在请求头部，权威位置高于消息体）。约束键（items/
        minimum/…）逐键防御性吸收：外部服务器给出畸形值时丢弃该键而非让整个
        工具注册失败（能力缺失优于报错）。
        """
        from novamind.engines.agent.tool.definition import ToolParameter
        from novamind.shared.prompts.sanitize import escape_system_tags

        func = raw_tool.get("function", {})
        params_schema = func.get("parameters", {})
        properties = params_schema.get("properties", {})
        required = params_schema.get("required", [])

        parameters: dict[str, ToolParameter] = {}
        for name, prop in properties.items():
            if not isinstance(prop, dict):
                continue
            kwargs: dict[str, Any] = {
                "type": prop.get("type", "string"),
                "description": escape_system_tags(prop.get("description", "")),
            }
            if prop.get("enum"):
                kwargs["enum"] = prop["enum"]
            if prop.get("default") is not None:
                kwargs["default"] = prop["default"]
            for key in ToolExecutor._SCHEMA_CONSTRAINT_KEYS:
                value = prop.get(key)
                if value is None:
                    continue
                try:
                    # 值类型不对（如 items 给了字符串）就丢弃该键，不影响其他参数
                    if key == "items":
                        kwargs["items"] = dict(value) if isinstance(value, dict) else None
                        if kwargs["items"] is None:
                            del kwargs["items"]
                    elif isinstance(value, (int, float)) and not isinstance(value, bool):
                        kwargs[key] = value
                except (TypeError, ValueError):
                    continue
            parameters[name] = ToolParameter(**kwargs)

        return ToolDefinition(
            name=func.get("name", ""),
            description=escape_system_tags(func.get("description", "")),
            parameters=parameters,
            required=required,
            source=source,
            timeout_ms=timeout_ms if timeout_ms is not None
            else ToolDefinition.model_fields["timeout_ms"].default,
        )

    def _provider_timeout_ms(self, tool_name: str) -> int:
        """按工具名找提供者读 default_timeout_ms（OpenAI 原始 dict 不携带超时，
        长任务工具覆写类属性才能生效），找不到提供者维持 ToolDefinition 默认。"""
        provider = self._tool_registry.find_tool_provider(tool_name)
        if provider is None:
            return ToolDefinition.model_fields["timeout_ms"].default
        return provider.default_timeout_ms
