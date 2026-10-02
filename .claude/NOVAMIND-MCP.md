# NovaMind × Claude Code 集成

本目录存放 Claude Code 与 NovaMind 知识库集成的资产。

## MCP server 直连

- **配置指南**：[`docs/claude-code-mcp-setup.md`](../docs/claude-code-mcp-setup.md)
  （API key 创建 → `claude mcp add` 注册 → 使用与管理）
- **skill**：[`skills/novamind-kb/SKILL.md`](./skills/novamind-kb/SKILL.md)
  （kb_search/kb_ask 工具选择、参数约定、结果解读；项目级自动生效，全局安装方法见文件内「安装」节）

## 快速开始

```bash
# 1. 创建 key（见配置指南第一节），然后：
claude mcp add --transport http novamind-kb http://127.0.0.1:8100/mcp \
  --header "X-API-Key: <你的 key>"
# 2. 重启 Claude Code 会话，直接自然语言问知识库
```
