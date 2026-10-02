# novamind-kb skill 安装说明

NovaMind 知识库的 Claude Code skill：安装后 Claude Code 可直接检索你部署的
NovaMind 知识库（`kb_search`）并获取带引用出处标注的问答（`kb_ask`）。

## 前置条件

1. NovaMind 后端已部署并运行（你或管理员知道其地址，如 `http://<nova主机>:8100`）；
2. 本机已安装 Claude Code。

## 安装（三步）

### 第 1 步：安装 skill 文件

把本目录（`docs/skill-package/novamind-kb/`，部署产物中随仓库分发）复制到
Claude Code 的用户级 skills 目录：

```bash
mkdir -p ~/.claude/skills/novamind-kb
cp SKILL.md ~/.claude/skills/novamind-kb/
```

### 第 2 步：创建 API key

向 NovaMind 管理员索取一个 API key（`nvm_` 开头），或自行经 NovaMind API 创建：

```bash
# 登录拿 JWT
TOKEN=$(curl -s -X POST http://<nova主机>:8100/api/v1/user/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "<用户名>", "password": "<密码>"}' | jq -r .access_token)

# 创建 key（明文仅此一次返回）
curl -s -X POST http://<nova主机>:8100/api/v1/agent-api/keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "claude-code"}'
```

### 第 3 步：注册 MCP server 到 Claude Code

```bash
claude mcp add --transport http novamind-kb http://<nova主机>:8100/mcp \
  --header "X-API-Key: <你的 nvm_ key>"
```

`claude mcp list` 显示 `novamind-kb ... ✔ Connected` 即成功。重启 Claude Code
会话后，skill 与两个工具一并生效。

## 验证

在 Claude Code 中直接问：

> 用 kb_search 查一下「RAG」

若返回带 `rank/score/snippet` 的片段列表即全链可用。

## 管理

- **吊销 key**（泄露/换岗时）：`DELETE /api/v1/agent-api/keys/<key_id>`，
  吊销后本机 Claude Code 的工具立即失效；换新 key 后更新 `claude mcp` 配置重注册；
- **key 列表**：`GET /api/v1/agent-api/keys`（脱敏显示）；
- 完整接口文档见 NovaMind 仓库 `docs/agent/claude-code-mcp-setup.md`。
