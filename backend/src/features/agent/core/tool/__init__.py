"""
Agent 工具系统

统一管理内置工具、MCP 工具、自定义工具：
- ToolDefinition：统一工具定义模型
- ToolResult：结构化工具执行结果
- ToolHook：生命周期钩子（日志/截断/超时）
- ToolExecutorV2：增强版执行器（带钩子链）
"""
