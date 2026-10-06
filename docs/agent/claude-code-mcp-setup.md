# NovaMind 知识库接入指南：skill 与 MCP

> **两种平级的使用方式，配置同源**（同一个 API key、同一套权限）：
>
> | 方式 | 形态 | 适合 |
> |------|------|------|
> | **Claude Code skill** | skill 内置脚本，读 `config.json` | 一次配置后直接自然语言问，**推荐** |
> | **MCP server** | Claude Code 原生 MCP 注册 | 想用标准 MCP 工具面 / 在其他 MCP 客户端复用 |
>
> 两者都走 NovaMind 后端同一个端点 `/mcp`，检索同一个知识库，鉴权用同一种 key。
> 前置条件：NovaMind 后端已运行（默认 `http://127.0.0.1:8100`）。

## 第零步：创建 API key（两种方式共用）

登录 NovaMind 后调用 key 管理接口（或请管理员创建）：

```bash
# 1. 登录拿 JWT
TOKEN=$(curl -s -X POST http://127.0.0.1:8100/api/v1/user/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "<你的用户名>", "password": "<你的密码>"}' | jq -r .access_token)

# 2. 创建 API key（明文 nvm_xxx 仅此一次返回，妥善保存）
curl -s -X POST http://127.0.0.1:8100/api/v1/agent-api/keys \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "claude-code"}'
```

响应里的 `api_key` 字段就是凭证。key 继承你的完整权限链
（空间成员 + 文档级可见性），吊销即时失效。

## 方式一：skill（推荐——配置一次，直接问）

### 安装 skill

把 `docs/skill-package/novamind-kb/` 复制到 Claude Code 的 skills 目录
（项目级 `.claude/skills/` 或用户级 `~/.claude/skills/`）：

```bash
mkdir -p <skills目录>/novamind-kb
cp docs/skill-package/novamind-kb/SKILL.md <skills目录>/novamind-kb/
cp -r docs/skill-package/novamind-kb/scripts <skills目录>/novamind-kb/
cp docs/skill-package/novamind-kb/config.example.json <skills目录>/novamind-kb/
```

> 本仓库协作者无需安装——`.claude/skills/novamind-kb/` 已随仓库分发，clone 即用。

### 配置（一次）

把 skill 目录下的 `config.example.json` 复制为 `config.json`，填三项：

```json
{
  "api_key": "nvm_你的key",
  "space_id": 6,
  "kb_id": 11,
  "base_url": "http://127.0.0.1:8100/mcp"
}
```

- `space_id`/`kb_id`：默认检索目标。不知道 ID 时先随便填 space_id（或不填），
  检索一次服务端会返回你的空间候选清单（`id(名称)`），挑一个回填即可；
- `base_url`：非本机部署才改；
- **config.json 含明文 key，已在 .gitignore 中，不要提交、不要外发。**

### 使用

重启 Claude Code 会话后，直接自然语言问：

> 「知识库里有没有关于文档解析流程的文档？」
> 「kb_search 查一下 Rerank 怎么配置」

Claude 会自动跑 skill 脚本检索并综合答案（带 `[Source N]` 出处编号）。
想临时换空间/调精度，口头说明即可（如「在 2 号空间里搜」「只要 0.5 以上相关的」）。

## 方式二：MCP server（标准 MCP 工具面）

### 注册

```bash
claude mcp add --transport http novamind-kb http://127.0.0.1:8100/mcp \
  --header "X-API-Key: nvm_你的key"
```

> 在哪个目录执行就注册到哪个项目 scope（`--scope user` 可全局）。
> `claude mcp list` 应显示 `novamind-kb ... ✔ Connected`。

### 使用

重启 Claude Code 会话后同样直接自然语言问。MCP 方式下 `space_id`/`kb_id`
由 Claude 按候选清单自动解析（多空间时会先返回候选再选），也可以在
`config.json` 之外用 Claude Code 的输出风格固定——两种方式的差别只在
配置载体（MCP 注册 header vs skill config.json），体验一致。

## 两种方式可以并存

同时配置时 Claude 优先走 MCP tool（标准协议、免进程启动）；skill 脚本作为
MCP 不可用时的自动降级路径。互不冲突，凭证同源。

## 行为说明（两种方式一致）

| 场景 | 行为 |
|------|------|
| 只属于一个空间 | 自动选定，直接出结果 |
| 属于多个空间 | 返回候选空间清单（id+名称），选定后重试 |
| 配置固定 space_id+kb_id | 永远直接出结果（最顺滑） |
| 非法 `search_mode` | 返回错误消息并列出全部可选值 |
| key 被吊销 | 立即 401 / 脚本报「无效或已吊销」 |

## 管理 key

```bash
# 列出我的 key（脱敏）
curl -s http://127.0.0.1:8100/api/v1/agent-api/keys -H "Authorization: Bearer $TOKEN"

# 吊销（即时失效；泄露时立即执行）
curl -s -X DELETE http://127.0.0.1:8100/api/v1/agent-api/keys/<key_id> \
  -H "Authorization: Bearer $TOKEN"
```

吊销后：MCP 需换新 key 重注册；skill 改 config.json 的 `api_key` 字段。

---

## 附：实现参考

- MCP server：`backend/src/features/agent_api/mcp/server.py`（FastMCP stateless+JSON，streamable_http）
- skill 脚本：`docs/skill-package/novamind-kb/scripts/kb_search.py`（裸 JSON-RPC，仅标准库）
- key 服务：`backend/src/features/agent_api/services/api_key_service.py`
- 权限继承链：`SearchService.search`（空间成员 + `hidden_doc_ids` 文档级过滤在检索时生效）
