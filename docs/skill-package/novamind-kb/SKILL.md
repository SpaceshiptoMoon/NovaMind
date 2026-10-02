---
name: novamind-kb
description: NovaMind 知识库 MCP 直连使用指引。通过 novamind-kb MCP server 检索企业知识库（kb_search）与获取带引用的知识库问答（kb_ask）。当用户要求查询 NovaMind 知识库、检索公司文档、问知识库问题、或提到 novamind-kb/kb_search/kb_ask 工具时使用。
allowed-tools: mcp__novamind-kb__kb_search, mcp__novamind-kb__kb_ask
---

# NovaMind 知识库检索与问答

通过 `novamind-kb` MCP server（HTTP 传输，X-API-Key 鉴权）访问私有化知识库。
两个工具都继承 key 创建者的权限链——只能看到 key 所属用户有权访问的空间与文档。

## 工具选择

| 场景 | 用哪个 |
|------|--------|
| 找相关文档/片段（自己综合） | `kb_search` |
| 要一个带引用出处的答案 | `kb_ask` |
| 不确定答案是否可信，需要核对原文 | 先 `kb_ask`，再 `kb_search` 核对 snippet |

## 参数约定

```
kb_search(query, space_id?, kb_id?, top_k=5)
kb_ask(query, space_id?, kb_id?, top_k=5)
```

- `query` 必填；`space_id`/`kb_id` 可选——**不传时服务端自动解析**：
  - 单一空间：自动选定，直接返回结果；
  - 多个空间：返回候选清单（`id(名称)` 格式）——**从候选中选最相关的 space_id 立即重试**，
    不要把候选清单原样抛给用户；确实无法判断时列出候选请用户选。
- `kb_ask` 返回 `answer` 内含 `[Source N]` 标注，N 对应输出 `results[].rank`——
  向用户转述时保留出处编号，用户可据此回溯原文。
- `kb_ask` 的 `answer` 为 `null` 且带 `answer_error` 时：检索无有效内容，
  换措辞或放宽关键词重试一次，仍失败则如实告知。

## 结果解读

- `results[].score` 为 0~1 相关度（归一化后），<0.3 的片段参考价值低；
- `snippet` 是 300 字符截断预览，需要更多上下文时用 `kb_search` 换更具体的 query；
- `document_id`/`chunk_id` 可用于在 NovaMind Web UI 中定位原文。

## 连接与凭证

- server 注册（在你自己的机器上执行一次）：
  `claude mcp add --transport http novamind-kb http://<nova主机>:8100/mcp --header "X-API-Key: <key>"`
- key 由 NovaMind 管理员或你自己经 NovaMind API 创建（明文 `nvm_` 开头，仅创建时返回一次）；
- 工具报「API key 无效或已吊销」：key 已被吊销或过期——联系管理员重新生成，
  并更新 `claude mcp` 配置中的 X-API-Key。

## 推荐问法示例

```
「用 kb_ask 问：退货政策里 7 天无理由适用哪些商品？」
「kb_search 查一下 Rerank 的配置方法，top_k 给 8」
「先 kb_ask 问 X，再用 kb_search 核对它引用的片段」
```
