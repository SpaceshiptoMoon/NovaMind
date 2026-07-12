# QA 检索增强问答管道 · 重构文档

> 范围：`backend/src/features/qa/services/ai_chat_service.py` 的检索问答管道，及配套组件 `grade_retrier.py` / `query_rewriter.py`。
> 背景：见 [`IMPROVEMENT-enterprise-kb.md`](../knowledge-space/IMPROVEMENT-enterprise-kb.md) §2.1 —— 重构前 `qa` 模块是「无根对话」（纯上下文拼接 + 裸生成，**完全不调知识库检索**）。本系列重构（批次 1–4）把它升级为完整的 RAG 管道：**查询改写 → 检索增强 → Grade→Retry 自评估 → 检索链路 trace**。
> 文档目的：记录重构后的架构、数据流、各组件/helper 职责与配置语义，供后续维护。

---

## 一、重构动机

| 痛点（重构前） | 重构后 |
|---|---|
| QA 不接检索，回答不可溯源、易幻觉 | 会话级 `auto_rag` 自动检索 KB + sources 注入 system_prompt |
| 检索结果不评估，垃圾结果照样生成 | Grade→Retry：检索后 LLM 打分，不通过则换 mode/降阈值重检索 |
| 多查询改写（DECOMPOSE）与 grade 互斥 | DECOMPOSE 也接 grade（设计 A：合并后整体打分） |
| 检索过程对用户黑盒 | 检索链路 trace（rewrite/search/grade）经 SSE 下发前端 |
| 配置默认值多处自相矛盾 / 死接线 | 配置语义统一、阈值路径统一、前端保存联动 |

---

## 二、管道总览（数据流）

入口：`AIChatService._prepare_chat(user_id, session_id, content, llm_model, attachment_ids, enable_web_search)` → 返回 `ChatPreparation`，供流式/非流式生成共用。

```
_prepare_chat
 │
 ├─ ensure_session_config() → session_config          # 会话级配置（压缩 / KB绑定 / LLM参数）
 ├─ 生成参数 ← llm_config properties（null 兜底默认）
 ├─ system_prompt ← llm_config.system_prompt │ QA_AI_CHAT_SYSTEM 模板
 ├─ add_message(user) + get_conversation_context + _inject_attachments_to_context
 │
 ├─ 开关来源（关键：避免「请求」与「会话表」两套配置源冲突）
 │     do_web        = enable_web_search              # 请求级（前端主输入区）
 │     do_rag        = session_config.auto_rag        # 会话级（无请求开关）
 │     rag_space/kb_ids/refusal_on/score_threshold/search_mode/top_k ← session_config properties
 │
 ├─【1 查询改写 Query Rewriting】  strategy = rag_query_rewriting（≠ none 且 do_web|do_rag 才进）
 │     QueryRewriter.rewrite(content, strategy, history) → RewriteResult{queries, strategy, degraded}
 │       COMPLETION / SYNONYM / HYDE → 单查询
 │       DECOMPOSE                    → 多子查询（O-RAG6 编号清洗）
 │
 ├─【2 检索 Retrieval】  （do_web|do_rag 才进）
 │     effective_threshold = score_threshold if refusal_on else None   # 拒答关=不过滤
 │     ├ len(queries)==1 单查询：
 │     │     grade_retry 开 + 有 LLM → GradeRetrier.search_with_retry（循环：切mode+降阈值+打分）
 │     │     否则                      → _augment_system_prompt_with_retrieval（单次）
 │     └ len(queries)>1  DECOMPOSE：
 │           grade_retry 开 + 有 LLM → 循环 _decompose_retrieve + grade(原问题整体)（设计A）
 │           否则                      → _decompose_retrieve（单次）
 │
 │     _augment_system_prompt_with_retrieval：
 │       web(_retrieve_web) + kb(_retrieve_knowledge) → raw_sources
 │         → refusal_on 时按 score_threshold 过滤 → 全局重编号 → _build_augmented_prompt 注入
 │
 ├─【3 分级拒答】 refusal_on 且 无 sources 且 非 web → prep_refused
 │
 ├─【4 Trace 构建】 rewrite / search / grade 条目（透传给 SSE → 前端 RetrievalTrace）
 │
 └─ conversation_history = [{system: system_prompt}] + context → LLM 生成（流式/非流式）
```

**核心设计决策**：
- **配置单一来源**：RAG 细节（空间/库/拒答/阈值/模式/top_k）统一从会话表读，前端不传，避免两套配置源冲突。
- **阈值与拒答解耦**：`refusal_on` 关 → `effective_threshold=None` → 不做分数过滤（web+kb 结果全留）；`refusal_on` 开 → 按阈值过滤低分 KB 来源。grade 与非 grade 两路径语义一致（批次3 R4）。
- **生成参数 null 语义**：`llm_config` 三字段默认 `None`（=「未设置」），由 property 兜底到 `api/constants.py`；GET 默认 dict 也返回 None，不物化成具体值（批次3 C7）。

---

## 三、组件与 helper 职责

### 3.1 组件（可插拔）

| 组件 | 文件 | 职责 |
|---|---|---|
| `QueryRewriter` | `services/query_rewriter.py` | 检索前查询改写，4 策略（NONE/COMPLETION/SYNONYM/DECOMPOSE/HYDE）。返回 `RewriteResult{queries, strategy, original_query, degraded}`。LLM 失败/不可用时 `degraded=True` 并回退原 query |
| `GradeRetrier` | `services/grade_retrier.py` | 检索后自评估 + 自动重试（Grade→Retry） |

**QueryRewriter 要点**：
- `_call_llm` 异常返回 None → 策略层标记 `degraded`，回退 `[query]`。
- DECOMPOSE 子查询经 `_clean_sub_query` 清洗（O-RAG6）：去 `1.`/`1)`/`-`/`•` 列表前缀（**仅当数字后跟 `.`/`)`，不误伤「2024年」「1+1」类合法子查询）+ 过滤「子问题：」标题行。

**GradeRetrier 要点**：
- `grade(query, sources, passing_score=5)`：LLM 按 `_GRADE_PROMPT` 打 1–10 分，`passed = score >= passing_score`。打分失败默认 `passed=False`（重试，质量优先）；JSON 解析用 `_extract_json` 正则兜底（兼容前导文字 + 代码块）。
- `search_with_retry(query, search_fn, initial_mode=None, score_threshold=None, passing_score, max_retries=2) -> (sources, system_prompt, grade_traces)`：循环每轮切 mode + 降阈值（`threshold × 0.7^attempt`，`None` 时全程不过滤）+ 打分，通过即返；缓存最近一次非空结果，循环结束返 `last`（**不再额外检索一次**）。`initial_mode` = 用户配的 `rag_search_mode` 首轮优先。

### 3.2 helper（`ai_chat_service.py`）

| helper | 职责 |
|---|---|
| `_augment_system_prompt_with_retrieval(...)` | 单查询检索入口：web + kb → 阈值过滤 → 重编号 → 返回 `(augmented_prompt, sources, raw_count)`。`raw_count`=过滤前数量，供 trace 区分「无结果」vs「被阈值过滤」 |
| `_decompose_retrieve(...)` | DECOMPOSE 并发检索所有子查询 → 合并去重（web 按 url、kb 按 chunk_id）→ 全局重编号 → 返回 `(deduped_sources, raw_count_sum)`。任一子查询失败仅 warning 跳过 |
| `_build_augmented_prompt(system_prompt, sources)` | 纯函数：把统一编号的 sources 拼成参考资料块，追加到 system_prompt（sources 的 `index` 与正文 `[1][2]` 角标对齐） |
| `_retrieve_web` / `_retrieve_knowledge` | 底层检索：web 复用 deep_research 的 DuckDuckGo；kb 走知识空间检索服务 |

### 3.3 检索链路 trace（自由 dict，经 SSE 下发）

```python
{"type": "rewrite", "original": ..., "rewritten": ..., "strategy": ..., "degraded": bool}
{"type": "search",  "mode": ..., "sources_count": N, "web_count": ..., "kb_count": ...}
{"type": "search",  "mode": ..., "sources_count": 0, "note": "无匹配结果" | "检索到 N 条但均低于阈值被过滤"}
{"type": "grade",   "attempt": i, "mode": ..., "threshold": float|None, "score": 1-10, "passed": bool, "reason": ...}
```

---

## 四、配置参考（SessionConfig）

ORM：`models/session_config.py` · `SessionConfig`（表 `qa_session_configs`），3 个 JSON 列。schema：`schemas/session_config.py`（`CompressionConfig` / `RagBindingConfig` / `LlmConfig`）。

### compression_config（默认 70000 / 2000 / 6）
| 字段 | property | 默认 | 说明 |
|---|---|---|---|
| `threshold` | `compression_threshold` | 70000 | 触发压缩的 token 阈值 |
| `target_tokens` | `compression_target_tokens` | 2000 | 压缩目标 token |
| `keep_recent` | `keep_recent_messages` | 6 | 保留近况消息数 |
| `enable_compression` / `strategy` / `custom_prompt` | — | True / summary / None | — |

> 批次3 C6：Column default、repository `DEFAULT_COMPRESSION_CONFIG`、property fallback 三处统一为 70000/2000/6。

### kb_bindings（会话级自动 RAG）
| 字段 | property | 默认 | 说明 |
|---|---|---|---|
| `auto_rag` | `auto_rag` | False | 是否对该会话自动检索 KB |
| `space_id` | `rag_space_id` | None | 绑定空间 |
| `kb_ids` | `rag_kb_ids` | [] | 绑定知识库 |
| `refusal_enabled` | `rag_refusal_enabled` | False | 分级拒答 + 阈值过滤开关 |
| `score_threshold` | `rag_score_threshold` | 0.3 | KB 来源分数阈值（refusal_on 时生效） |
| `search_mode` | `rag_search_mode` | content_hybrid | 检索模式 |
| `top_k` | `rag_top_k` | 5 | — |
| `query_rewriting` | `rag_query_rewriting` | none | 改写策略：none/completion/synonym/decompose/hyde |
| `grade_retry_enabled` | `rag_grade_retry_enabled` | False | Grade→Retry 开关 |
| `grade_retry_passing_score` | `rag_grade_retry_passing_score` | 5 | grade 及格线（调高=更严格） |

> 批次3 C7：GET 默认 dict 补全这 10 字段（重构前缺后 3 个 RAG 字段）。

### llm_config（生成参数，null=未设置）
| 字段 | property | null 兜底 | 说明 |
|---|---|---|---|
| `max_tokens` | `llm_max_tokens` | DEFAULT_MAX_TOKENS(2048) | — |
| `temperature` | `llm_temperature` | DEFAULT_TEMPERATURE(0.7) | — |
| `top_p` | `llm_top_p` | DEFAULT_TOP_P(0.8) | — |
| `system_prompt` | `llm_system_prompt` | （不兜底，None=用 QA 模板） | — |

> 注：`llm_model` / `enable_thinking` 由前端请求传，不在此列。批次3 C7：GET 默认 dict 返回 `None`（与 schema 对齐），不物化成具体值。

---

## 五、批次变更记录（Changelog）

> 完整发现项来自「全项目逻辑审查 + 红蓝对抗核实」。严重度：🔴P0 阻断 / 🟡P1-P2 应修。

### 批次 1（P0）
- **R1** DECOMPOSE 增强：子查询检索结果合并去重（web 按 url、kb 按 chunk_id）+ 全局重编号 + 注入 system_prompt（重构前 LLM 拿到裸 prompt 完全看不到资料）。
- **F1** ChatInput 附件上传改走 chat store（重构前附件状态散落组件、与 store 脱节）。
- **F2** ChatView 切会话/新建会话时先 `cancelStream`（重构前流式中切会话，SSE 回调污染新会话消息）。

### 批次 2（P1）
- **R3** grade_retrier 加固：`passing_score` 真正生效（原硬编码 `>=5`）；打分失败默认重试（原默认放行）；`_extract_json` 鲁棒解析；删循环后冗余检索；`initial_mode` 尊重用户配的 search_mode；返回值扩展 `grade_traces`。
- **R5** trace 补全 + 降级标记：`RewriteResult.degraded`；放宽 rewrite trace 条件；search trace note 区分「无结果」vs「被阈值过滤」；grade trace 下发。

### 批次 3（P2）
- **R4** 阈值路径统一：grade 分支去掉 `effective_threshold or 0.3` 兜底，`score_threshold` 改 `Optional`，拒答关时两路径都不做分数过滤。
- **C6** 压缩默认值统一（Column/repository/property 三处 → 70000/2000/6）。
- **C7** GET 默认补全 3 个 RAG 字段 + `llm_config` 对齐 None 语义。
- **F5** 前端死代码清理 + SessionConfigDialog `@saved` 联动刷新（保存后即时 `fetchSessionConfig`）。

### 批次 4（P1）
- **R2** DECOMPOSE 接 grade（设计 A）：抽 `_decompose_retrieve` helper；DECOMPOSE 分支循环「检索所有子查询→合并→用原始问题整体打分」，不通过则切 mode + 降阈值重检索（重构前 DECOMPOSE 完全不调 grade，两新功能组合失效）。
- **O-RAG6** DECOMPOSE 子查询编号清洗（`_clean_sub_query`）。

---

## 六、验证

```bash
# 后端语法
cd backend
.venv/Scripts/python.exe -m py_compile \
  src/features/qa/services/ai_chat_service.py \
  src/features/qa/services/grade_retrier.py \
  src/features/qa/services/query_rewriter.py

# 启动 + Swagger 手测
python main.py --config development   # http://localhost:8100/docs
```

关键场景（session_config 配置后发复合型问题）：
- **改写**：`query_rewriting=decompose` → 后端日志 `search_queries` 为多个清洗后子查询（无 `1.`/`子问题：` 前缀）。
- **grade 单查询**：`grade_retry_enabled=true` + `grade_retry_passing_score=8` → trace 出现多条 grade（attempt 递增、mode 切换、threshold 递降）。
- **grade + DECOMPOSE**：两者同开 → trace 同时出现 search（多源）+ grade（R2 验证点）。
- **拒答**：`refusal_enabled=true` + 检索全低分 → trace note 显示「被阈值过滤」；全无结果 → 「无匹配结果」。
- **降级**：改写 LLM 不可用 → trace `rewrite.degraded=true`。

---

## 七、已知遗留（未做）

- **P3（F3/F4/F6）**：经评估为可选清理，暂不做。其中 F3（`openSessionConfig` 造假 ID）修法有副作用（会导致配置弹窗不出现），需配套重写取 session ID 逻辑，暂搁置。
