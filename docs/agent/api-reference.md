# 对外 API 使用参考

NovaMind 对外暴露的接口共三个消费面，全部收敛在 `agent_api` feature，**配置同源、鉴权同一种 key**：

| 消费面 | 端点 | 认证 | 适合 |
|---|---|---|---|
| **MCP server**（知识库检索） | `POST /mcp`（Streamable HTTP） | API key | Claude Code、Cursor 等 agent 宿主经 MCP 协议消费知识库 |
| **OpenAI 兼容网关** | `POST /v1/chat/completions`、`GET /v1/models` | API key | 任何 OpenAI SDK / 兼容客户端（ChatBox、LobeChat、openai-python 等） |
| **API key 管理** | `/api/v1/agent-api/keys` | JWT（站内用户） | 创建 / 列出 / 吊销消费面用的 key |

> 本文是接口面总参考（契约 / 参数 / 错误）。按工作流的专题指南：
> Claude Code 接入看 [`claude-code-mcp-setup.md`](./claude-code-mcp-setup.md)，
> 网关 SDK 用法看 [`openai-gateway.md`](./openai-gateway.md)。

## 认证

**消费面（MCP / 网关）用 API key**：明文 `nvm_` 开头，仅创建时返回一次。凭证头按消费面区分：

```
MCP（/mcp）：   仅认 X-API-Key: nvm_xxxx（Bearer 头不参与 MCP 门禁）
网关（/v1）：   Authorization: Bearer nvm_xxxx 优先，回落 X-API-Key（两者等价）
```

key 继承创建者的完整权限链（空间成员资格、文档可见性都按创建者校验），吊销即全部消费面立即拒绝。

**管理面（key CRUD）用站内 JWT**：与 Web UI 同一套登录态。

## API key 管理

```bash
# 1. 登录拿 JWT
TOKEN=$(curl -s -X POST http://127.0.0.1:8100/api/v1/user/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "<用户名>", "password": "<密码>"}' | jq -r .access_token)

# 2. 创建 key（明文 api_key 仅此一次返回；每用户上限 20 个，超限返回 409 API_KEY_LIMIT_EXCEEDED）
curl -s -X POST http://127.0.0.1:8100/api/v1/agent-api/keys \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name": "my-agent"}'

# 3. 列出我的 key（只返回元数据，不含明文）
curl -s http://127.0.0.1:8100/api/v1/agent-api/keys -H "Authorization: Bearer $TOKEN"

# 4. 吊销（key_id 从列表接口拿；吊销立即生效）
curl -s -X DELETE http://127.0.0.1:8100/api/v1/agent-api/keys/<key_id> \
  -H "Authorization: Bearer $TOKEN"
```

## MCP server：kb_search

`/mcp` 是标准 Streamable HTTP 传输的 MCP server，当前注册一个工具 **`kb_search`**——语义检索 NovaMind 知识库并返回分块结果。推荐经 MCP 客户端使用（`claude mcp add --transport http novamind-kb http://<host>:8100/mcp --header "X-API-Key: <key>"`），也可裸 JSON-RPC 直接调：

```bash
# 工具调用（initialize → tools/call 的会话流程略，最小示例如下）
curl -s -X POST http://127.0.0.1:8100/mcp \
  -H "X-API-Key: nvm_xxxx" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call",
       "params":{"name":"kb_search","arguments":{"query":"退货政策", "top_k":5}}}'
```

**kb_search 参数**（只传 query 即可，其余有默认值）：

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `query` | string | 必填 | 检索文本 |
| `space_id` / `kb_id` | int | 配置默认 / 自动选首个 ACTIVE KB | 定位目标；`space_id` 不传且用户有多空间时返回候选清单让调用方选择后重试；`kb_id` 缺省自动选该空间第一个 ACTIVE KB |
| `top_k` | int | 5 | 返回条数 |
| `search_mode` | string | `content_hybrid` | 9 种检索模式；概念性查询用 `question_*`、精确术语用 `content_bm25`、兜底 `all_hybrid` |
| `score_threshold` | float | 不过滤 | 结果噪声多时 0.3~0.5 |
| `vector_weight` / `bm25_weight` | float | 0.7 / 0.3 | 混合权重，专有名词场景调高 bm25 |
| `use_cache` | bool | true | KB 刚更新需最新结果时关闭 |

**返回结构**：`total` + `results[]`，每条含 `rank`（转述时作 `[Source N]` 出处）、`score`（0~1 相关度，<0.3 参考价值低）、`snippet`（300 字符预览）、`document_id` / `chunk_id`（回 Web UI 定位原文）、`document_name`。

> 提示：MCP 客户端里工具名为 `mcp__novamind-kb__kb_search`（注册名 `novamind-kb` 前缀）。

## OpenAI 兼容网关

把你在 NovaMind「模型配置页」配好的 LLM 以 OpenAI 协议暴露。base_url = `http://<host>:8100/v1`。

```bash
# 模型清单（= 你的已配 LLM 列表）
curl -s http://127.0.0.1:8100/v1/models -H "Authorization: Bearer nvm_xxxx"

# 对话补全（stream:true 时 SSE 流式）
curl -s -X POST http://127.0.0.1:8100/v1/chat/completions \
  -H "Authorization: Bearer nvm_xxxx" -H "Content-Type: application/json" \
  -d '{"model":"<已配模型名>","messages":[{"role":"user","content":"你好"}]}'
```

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key="nvm_xxxx", base_url="http://localhost:8100/v1")
r = await client.chat.completions.create(
    model="Moonshot-Kimi-K2-Instruct",   # 直连已配模型名，不做别名映射
    messages=[{"role": "user", "content": "你好"}],
)
```

请求 / 响应 / 流式行为对齐 OpenAI Chat Completions 规范，模型名传你在 NovaMind 配置的原始模型名。

## 错误格式与状态码

两个消费面的错误形态不同，分开表述：

**网关面（/v1）**：统一 **OpenAI 错误信封**（外部 SDK 只认该格式）：

```json
{"error": {"message": "API key 无效或已吊销", "type": "invalid_request_error", "param": null, "code": "..."}}
```

| 状态码 | 含义（网关面） |
|---|---|
| 401 | key 缺失 / 无效 / 已吊销（吊销即时生效，无缓存窗口） |
| 403 | key 有效但目标资源越权（空间 / 文档可见性） |
| 404 | 目标空间 / 知识库不存在（不区分「不存在」与「无权」，避免存在性探测） |
| 429 | 触发限流（全局限流按 IP） |
| 5xx | 上游模型 / 内部错误（信封 type 为对应错误类） |

**MCP 面（/mcp）**：门禁 401 的信封是精简两字段（无 type/param）：

```json
{"error": {"code": "invalid_api_key", "message": "..."}}
```

进入协议层后，检索类失败（空间不存在 / 无权访问等）**不走 HTTP 403/404**——以 JSON-RPC 200 响应 + `isError: true` 工具文本返回（MCP 协议惯例，客户端从工具结果文本读取原因）。

## 安全注意事项

- **key 等同用户身份**：泄露立即吊销（DELETE 接口）并重建；不要把 key 写进会提交的文件（分发包的 `config.json` 已被 .gitignore 覆盖，自建集成自行注意）。
- 检索结果自动按创建者权限过滤（含文档级可见性）——给 agent 的 key 就是给 agent 你的阅读权限，最小权限原则选创建者账号。
- 公网部署时建议经反代加 TLS，并对 `/v1`、`/mcp` 配置独立限流。
