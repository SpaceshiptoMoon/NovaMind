---
name: novamind-kb
description: NovaMind 知识库检索。配置一次（api_key + space_id + kb_id）后，用户问知识库相关问题就直接检索回答。MCP 已注册时用 mcp__novamind-kb__kb_search，否则跑 scripts/kb_search.py（读 config.json，零参数）。当用户要求查询 NovaMind 知识库、检索公司文档、问知识库问题、或提到 novamind-kb/kb_search 时使用。
allowed-tools: mcp__novamind-kb__kb_search, Skill(novamind-kb)
---

# NovaMind 知识库检索

**用户体验目标：配置一次，之后直接问。** 你（Claude）负责检索并综合答案，
转述时保留 `rank` 编号作为出处（用户可在 NovaMind Web UI 回溯原文）。

## 首次使用检查（配置是否就绪）

按顺序检查，任一就绪即可用：

1. MCP：`mcp__novamind-kb__kb_search` 在可用工具列表里 → 直接用（推荐）；
2. 脚本配置：`<skill目录>/config.json` 存在且含 `api_key` → 直接跑脚本（零参数）；
3. 都没有 → 引导用户完成一次配置（见下方「配置引导」），**不要**反复询问。

## 日常使用（配置就绪后）

用户问知识库相关问题 → 直接检索 → 综合回答。两种方式等价：

**MCP（优先）：**

```
kb_search(query="用户的问题关键词", top_k=5)
```

**脚本（MCP 不可用时）：**

```bash
python <skill目录>/scripts/kb_search.py "用户的问题关键词"
```

space_id/kb_id 已在配置里，**只传 query 即可**。仅当用户明确要求换范围/调参数时
才传额外参数：`--space-id` `--kb-id` `--top-k` `--search-mode` `--score-threshold`
`--vector-weight` `--bm25-weight` `--no-cache`（MCP 对应 camelCase 同名参数）。

## 检索参数速查（默认值已够用，勿主动堆参数）

| 参数 | 默认 | 何时调 |
|------|------|--------|
| `search_mode` | `content_hybrid` | 概念性查询用 `question_*`；精确术语用 `content_bm25`；找不到时 `all_hybrid` 兜底 |
| `score_threshold` | 不过滤 | 结果噪声多时 0.3~0.5 |
| `vector_weight`/`bm25_weight` | 0.7/0.3 | 专有名词匹配场景调高 bm25 |
| `top_k` | 5 | 用户要多条参考时加大 |
| `use_cache` | `true` | KB 刚更新需最新结果时关掉（`--no-cache`） |

## 结果解读与答案综合

- `results[].score` 为 0~1 相关度，<0.3 的片段参考价值低；
- `snippet` 是 300 字符截断预览，不够时换更具体的 query 重查；
- 综合答案用 `[Source N]`（N=rank）标注出处；
- 脚本退出码 `3`（多空间候选）或 MCP 返回候选清单：从候选中选最相关的，
  按其 space_id 重试一次；确实无法判断再问用户；
- 检索无结果：换措辞或放宽关键词重试一次，仍无结果如实告知。

## 配置引导（仅首次，用户要求接入时执行）

1. 创建 API key（明文 `nvm_` 开头仅返回一次），方法见
   `docs/agent/claude-code-mcp-setup.md` 第一节（登录拿 JWT → POST keys）；
2. 确定默认空间与知识库：列出用户的空间让用户选（或用户直接报名字，调
   kb_search 不带 space_id 会返回候选清单可利用）；
3. 二选一接入：
   - **MCP 路径**：`claude mcp add --transport http novamind-kb http://127.0.0.1:8100/mcp --header "X-API-Key: <key>"`，
     重启会话后多空间时用户需带 space_id（或后续补配置）；
   - **脚本路径**：把 `<skill目录>/config.example.json` 复制为 `config.json`，
     填 `api_key`/`space_id`/`kb_id`（`base_url` 非本机部署才改）——
     **推荐**，配置一次后体验最顺（用户只管问）；
4. 验证：跑一次零参数检索，返回 `total/results` 即接入完成。

## 凭证安全

- key 等同用户身份，泄露即吊销：`DELETE /api/v1/agent-api/keys/<key_id>`；
- config.json 含明文 key，不得提交进 git（已在 .gitignore 的 config.json 规则覆盖范围内，
  若无则提醒用户不要提交）。
