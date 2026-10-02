# NovaMind × Claude Code 集成

本目录存放 Claude Code 与 NovaMind 知识库集成的资产。

## 给部署方终端用户

- **skill 安装包**：[`docs/skill-package/novamind-kb/`](../docs/skill-package/novamind-kb/)
  （`SKILL.md` + `INSTALL.md` 三步安装：装 skill → 建 key → 注册 MCP server）
- **完整配置指南**：[`docs/agent/claude-code-mcp-setup.md`](../docs/agent/claude-code-mcp-setup.md)

## 给本仓库协作者

- skill 已随仓库分发在 `.claude/skills/novamind-kb/`（项目级自动生效——
  实际文件在 `docs/skill-package/`，gitignore 例外指到这里，单一事实源）；
- key 管理接口：`/api/v1/agent-api/keys`（实现见 `backend/src/features/agent_api/`）。

## 快速开始

```bash
# 1. 创建 key（见配置指南第一节），然后：
claude mcp add --transport http novamind-kb http://127.0.0.1:8100/mcp \
  --header "X-API-Key: <你的 key>"
# 2. 重启 Claude Code 会话，直接自然语言问知识库
```
