# Claude Code 直连 NovaMind 知识库（MCP）配置指南

> **前置条件**：NovaMind 后端已运行（默认 `http://127.0.0.1:8100`），MCP server 随后端自动挂载于 `/mcp`。
> **能力**：`kb_search`（知识库检索，返回带评分的片段）、`kb_ask`（带 `[Source N]` 引用的知识库问答）。
> **权限**：API key 继承创建者的完整权限链（空间成员 + 文档级可见性），吊销即时失效。

## 一、创建 API key

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

响应示例（记录 `api_key` 字段）：

```json
{
  "id": 4,
  "key_prefix": "nvm_wobFl3tO",
  "api_key": "nvm_wobFl3tOVfUZ...",   // ← 这个就是 X-API-Key 的值
  "status": "active"
}
```

## 二、注册到 Claude Code

### 方式 A：CLI 一条命令（推荐）

```bash
claude mcp add --transport http novamind-kb http://127.0.0.1:8100/mcp \
  --header "X-API-Key: nvm_你的明文key"
```

> 在哪个目录执行就注册到哪个项目 scope（`--scope user` 可全局）。
> `claude mcp list` 应显示 `novamind-kb ... ✔ Connected`。

### 方式 B：手写 `.claude.json`（项目级）

在项目根的 `.claude.json` 的 `mcpServers` 段加：

```json
{
  "mcpServers": {
    "novamind-kb": {
      "type": "http",
      "url": "http://127.0.0.1:8100/mcp",
      "headers": { "X-API-Key": "nvm_你的明文key" }
    }
  }
}
```

重启 Claude Code 会话后生效。

## 三、使用

注册后在 Claude Code 里直接自然语言提问即可，例如：

- 「用 novamind-kb 检索 RAG 检索增强，告诉我命中了几条、最高分多少」
- 「用 kb_ask 问一下：RAG 相比直接用大模型有什么优势？」

行为说明：

| 场景 | 行为 |
|------|------|
| 只属于一个空间 | `space_id`/`kb_id` 可省略，自动选定 |
| 属于多个空间 | 首次调用返回候选空间清单（id+名称），带上 `space_id` 重试即可 |
| `kb_ask` 无检索结果 | `answer` 为 `null`，附 `answer_error` 提示——可换措辞重试 |
| key 被吊销 | 下一次调用立即 401，Claude Code 会提示重连 |

## 四、管理 key

```bash
# 列出我的 key（脱敏）
curl -s http://127.0.0.1:8100/api/v1/agent-api/keys -H "Authorization: Bearer $TOKEN"

# 吊销（即时失效；泄露时立即执行）
curl -s -X DELETE http://127.0.0.1:8100/api/v1/agent-api/keys/<key_id> \
  -H "Authorization: Bearer $TOKEN"
```

## 五、快速 skill（可选）

如果频繁在 Claude Code 中使用，可安装配套 skill：`~/.claude/skills/novamind-kb/SKILL.md`
（仓库 `docs/` 同目录发布的安装说明见 skill 文件头）——提供 key 环境变量约定与
检索/问答的使用指引，帮助 Claude 更准确地选工具与传参。

---

## 附：实现参考

- MCP server：`backend/src/features/agent_api/mcp/server.py`（FastMCP stateless+JSON，streamable_http）
- key 服务：`backend/src/features/agent_api/services/api_key_service.py`
- 权限继承链：`SearchService.search`（空间成员 + `hidden_doc_ids` 文档级过滤在检索时生效）
- 系统现状总览：[`kb-ops-loop-summary.md`](./knowledge-space/current/kb-ops-loop-summary.md)
