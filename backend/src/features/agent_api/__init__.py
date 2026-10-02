"""外部 Agent API（agent_api）：API key 凭证与 MCP server。

当前批次：API key 管理（创建/列出/吊销 + X-API-Key 鉴权依赖）。
下一批次：MCP server（kb_search/kb_ask tools，streamable_http 挂 /mcp）。

key 继承创建者用户权限（检索走完整权限链）；永久有效 + 手动吊销（即时失效）。
明文 key 仅创建响应返回一次，库内 SHA-256 hash（校验）+ AES-GCM 密文（可逆留存）双存。
"""
