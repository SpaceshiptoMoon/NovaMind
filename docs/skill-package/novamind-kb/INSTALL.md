# novamind-kb skill 安装说明

NovaMind 知识库的 Claude Code skill。装好并配置一次（api_key + space_id + kb_id）
后，在 Claude Code 里直接自然语言问知识库，Claude 自动检索并综合答案。

> skill 与 MCP server 是 NovaMind 知识库的两种平级接入方式（同 key 同权限），
> 对比与完整流程见仓库 `docs/agent/claude-code-mcp-setup.md`。本文件只讲 skill。

## 前置条件

1. NovaMind 后端已部署并运行（你或管理员知道其地址，如 `http://<nova主机>:8100`）；
2. 本机已安装 Claude Code。

## 安装（三步）

### 第 1 步：安装 skill 文件

把本目录（`docs/skill-package/novamind-kb/`，部署产物中随仓库分发）复制到
Claude Code 的 skills 目录（用户级 `~/.claude/skills/` 或某项目的 `.claude/skills/`）：

```bash
mkdir -p ~/.claude/skills/novamind-kb
cp SKILL.md ~/.claude/skills/novamind-kb/
cp -r scripts ~/.claude/skills/novamind-kb/
cp config.example.json ~/.claude/skills/novamind-kb/
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

### 第 3 步：填 config.json（一次配置，之后直接问）

在 skill 目录把 `config.example.json` 复制为 `config.json`，填三项：

```json
{
  "api_key": "nvm_你的key",
  "space_id": 6,
  "kb_id": 11,
  "base_url": "http://<nova主机>:8100/mcp"
}
```

- 不知道 space_id/kb_id：先只填 api_key，之后让 Claude 检索一次——服务端会
  返回你的空间候选清单，挑一个回填；
- **config.json 含明文 key，勿提交 git、勿外发。**

## 验证

重启 Claude Code 会话后直接问：

> 知识库里有没有关于 RAG 的文档？

Claude 会自动跑 `scripts/kb_search.py` 检索并综合答案。也可手动验证：

```bash
python ~/.claude/skills/novamind-kb/scripts/kb_search.py "RAG"
```

返回带 `rank/score/snippet` 的片段列表即全链可用。

## 优先级与降级

配置优先级：命令行参数 > 环境变量（`NOVAMIND_API_KEY`/`NOVAMIND_MCP_URL`/
`NOVAMIND_SPACE_ID`/`NOVAMIND_KB_ID`）> `config.json` > 默认值。
若同时注册了 MCP server，Claude 优先走 MCP tool，脚本作自动降级。

## 管理

- **吊销 key**（泄露/换岗时）：`DELETE /api/v1/agent-api/keys/<key_id>`，
  吊销后立即失效；换新 key 只需改 config.json 的 `api_key` 字段；
- **key 列表**：`GET /api/v1/agent-api/keys`（脱敏显示）；
- 完整接入文档（含 MCP 方式对比）见 NovaMind 仓库 `docs/agent/claude-code-mcp-setup.md`。
