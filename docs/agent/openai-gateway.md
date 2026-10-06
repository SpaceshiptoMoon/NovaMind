# OpenAI 兼容网关

NovaMind 把用户已配置的 LLM 以 OpenAI 协议对外暴露：任何 OpenAI SDK / 兼容客户端
（ChatBox、LobeChat、Cursor、openai-python 等）指到本网关即可调用你在
「模型配置页」配好的模型。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/v1/models` | 列出当前 API key 归属用户已配置的 LLM 模型 |
| POST | `/v1/chat/completions` | 对话补全（`"stream": true` 时 SSE 流式） |

## 鉴权

复用 agent_api 的 `nvm_` API key（在 Web 端「API 密钥管理页」创建）。
两种凭证头等价，Bearer 优先：

```
Authorization: Bearer nvm_xxxx
X-API-Key: nvm_xxxx
```

## 快速开始

base_url = `http://<host>:8100/v1`。

### OpenAI Python SDK

```python
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key="nvm_xxxx", base_url="http://localhost:8100/v1")

# 模型清单（= 你在 NovaMind 配置的 LLM 列表）
models = await client.models.list()

# 非流式
r = await client.chat.completions.create(
    model="Moonshot-Kimi-K2-Instruct",   # 直连已配模型名，不做别名映射
    messages=[{"role": "user", "content": "你好"}],
)
print(r.choices[0].message.content)

# 流式（SSE）
stream = await client.chat.completions.create(
    model="Moonshot-Kimi-K2-Instruct",
    messages=[{"role": "user", "content": "讲个笑话"}],
    stream=True,
)
async for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### curl

```bash
curl http://localhost:8100/v1/chat/completions \
  -H "Authorization: Bearer nvm_xxxx" -H "Content-Type: application/json" \
  -d '{"model":"Moonshot-Kimi-K2-Instruct","messages":[{"role":"user","content":"hi"}]}'
```

## 语义说明

- **模型名直连**：`model` 字段填你在 NovaMind 模型配置页配的真实模型名，
  网关不做别名映射；未配置的模型返回 `404 model_not_found`。
- **能力协商**：请求 `tools` 但模型不支持工具调用 → `400 tools_not_supported`
  （显式报错，不静默剥工具）；请求 thinking 但模型不支持 → 静默关闭
  （能力缺失退化）。流式 + 工具但协议无流式工具实现 → `400` 提示改非流式。
- **协议透传**：模型底层是 openai/anthropic/ollama 哪种协议由其 NovaMind
  配置决定，网关经统一客户端层转换，客户端始终说 OpenAI 方言。
- **thinking**：请求体可选 `"enable_thinking": true`（NovaMind 扩展，
  DashScope 同名惯例），仅对声明支持 thinking 的模型生效。
- **未知字段容错**：官方 SDK 附带的字段（`reasoning_effort`/`logprobs` 等）
  静默忽略；`content` 数组（gpt-4o 多模态形状）提取 text 部件拼接。
- **reasoning**：思考型模型的思考内容在 `message.reasoning_content`
  / 流式 `delta.reasoning_content`（DeepSeek/Qwen 惯例）。

## 错误格式

统一 OpenAI 官方错误信封（SDK 据此重试/归类）：

```json
{"error": {"message": "...", "type": "invalid_request_error", "param": null, "code": "..."}}
```

| code | HTTP | 场景 |
|---|---|---|
| `invalid_api_key` | 401 | key 缺失/无效/已吊销/用户禁用 |
| `model_not_found` | 404 | 模型未在 NovaMind 配置 |
| `tools_not_supported` | 400 | 模型不支持工具调用 |
| `streaming_tools_not_supported` | 400 | 协议无流式工具实现 |
| `insufficient_quota` | 400/403 | 上游欠费/免费额度耗尽 |
| `rate_limit_exceeded` | 429 | 上游限流（SDK 自动退避重试） |
| `provider_error` | 4xx/502 | 其余上游错误（message 含厂商原文摘要） |

## 已知限制

- 无跨模型 failover / 熔断 / 供应商健康探活（规划中，后续批次补）。
- 不支持 `/v1/embeddings`、`/v1/completions`（legacy）等其余端点。
- usage 字段在上游未返回时为空对象 `{}`（官方 SDK 容忍）。
