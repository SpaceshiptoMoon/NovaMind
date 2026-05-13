"""
Agent LLM 交互层

AgentLLM 封装 BaseLLM，提供 Agent 专用的接口：
- 真正的流式输出（逐 token 产出）
- 流式场景下的工具调用收集
- 统一的响应模型
"""
