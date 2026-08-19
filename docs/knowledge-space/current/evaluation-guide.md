# 知识库评估（测评）—— 测试集标准、评估指标与结果解读

本文档说明知识库测评（evaluation）模块的**测试集编写标准**、**评估指标定义**、**结果（报告）格式与解读**，以及**如何使用**。它是 `backend/docs/api/evaluation_api.md`（接口参考）的配套指南，回答"该准备什么样的测试集、评测怎么算分、结果怎么看、怎么跑一次评测"。

## 1. 概述

测评模块对一个知识库（KB）的检索与生成质量做自动化打分。评测流程是：

```
上传测试集 → 创建评测任务（可配检索/生成/打分策略）→ 后台异步并发执行
           → 逐条检索 + 生成 + 打分 → 汇总报告 →（可选）人工评分 / 导出
```

测评体系参考 RAGAS / DeepEval 等主流框架，分三个层次：

| 层次 | 回答的问题 | 主要指标 |
|------|-----------|---------|
| 检索阶段 | 检索到的内容是否相关、是否命中、是否排得靠前 | Precision@K、Hit Rate、MRR |
| 生成阶段 | 生成的回答是否正确、忠实、切题、质量高 | Correctness、Faithfulness、Answer Relevance、Quality |
| 端到端 | 上下文是否精准/完整、答案与期望答案语义是否接近 | Context Precision、Context Recall、Answer Similarity |

### 相关代码位置

| 组件 | 路径 |
|------|------|
| 编排服务 | `backend/src/features/evaluation/services/evaluation_service.py` |
| 测试集解析 | `backend/src/features/evaluation/services/test_set_parser.py` |
| 结果导出 | `backend/src/features/evaluation/services/result_exporter.py` |
| 评估引擎（纯逻辑） | `backend/src/engines/eval/`（retrieval/generation/embedding/claim 四个评估器） |
| API 路由 | `backend/src/features/evaluation/api/routes.py` |

---

## 2. 测试集标准

### 2.1 文件格式

支持 **JSON** 与 **CSV** 两种格式，编码必须为 **UTF-8**（CSV 额外兼容带 BOM 的 UTF-8），单个文件不超过 **10MB**。

每条测试用例由两个必填字段构成：

| 字段 | 必填 | 说明 |
|------|------|------|
| `question` | 是 | 测试问题。评测时作为检索查询，并作为生成阶段的输入 |
| `expected_answer` | 是 | 期望答案（参考答案）。用于正确性、上下文召回、答案相似度等指标 |

**JSON 格式**（根对象可带可选 `name` 字段）：

```json
{
  "name": "OCR 知识库回归测试集",
  "test_cases": [
    {
      "question": "第一代机械式 OCR 的核心原理是什么？",
      "expected_answer": "基于模板匹配，将字符图像与预置字符模板逐像素比对，识别度受字体和噪声影响大。"
    },
    {
      "question": "多模态大模型 OCR 相比传统方案的优势有哪些？",
      "expected_answer": "能够结合图像、文本与上下文语义进行端到端识别，对复杂版面、手写体和低质量图像鲁棒性更强。"
    }
  ]
}
```

**CSV 格式**（表头必须包含 `question` 与 `expected_answer` 两列）：

```csv
question,expected_answer
"第一代机械式 OCR 的核心原理是什么？","基于模板匹配，逐像素比对字符模板。"
"多模态大模型 OCR 的优势有哪些？","端到端语义识别，对复杂版面鲁棒性强。"
```

### 2.2 解析校验规则

`test_set_parser.py` 在上传时做如下校验，任一不满足即返回 `INVALID_TEST_SET`（400）：

1. 扩展名必须为 `.json` 或 `.csv`；
2. 文件内容非空，且不超过 10MB；
3. 编码必须为 UTF-8（CSV 允许带 BOM）；
4. JSON 根元素必须是对象，且 `test_cases` 必须为非空数组；
5. 每条用例必须是对象，`question` 与 `expected_answer` 去首尾空白后均不能为空；
6. CSV 必须含 `question`、`expected_answer` 两列，且至少有一行数据。

### 2.3 编写高质量测试集的最佳实践

评测结果的可信度直接取决于测试集质量。建议：

- **问题与知识库内容强相关**：每条 `question` 都应能在目标知识库中找到答案，否则检索/召回指标会系统性偏低。
- **参考答案信息完整**：`expected_answer` 应包含检索应覆盖的关键信息点（claims），供 Context Recall、Correctness 等指标拆解比对。
- **覆盖核心知识点**：按文档章节/主题抽题，避免集中在一两个文档；覆盖面广才能反映整体检索质量。
- **问题表达自然、单一**：一条用例只问一个问题，避免复合多问句，否则相关性/忠实度打分易受干扰。
- **一次建集、多次复用**：同一测试集可被多个任务（不同检索模式/不同模型/不同 top_k）复用，用于对照实验。

---

## 3. 评估指标标准

评测的每个用例经过「检索 → 生成 → 打分」三阶段。下面按层次说明每个指标的**定义、计算方式、取值范围**。

### 3.1 检索阶段指标

检索结果相关性判断有两种策略（由 `retrieval_relevance_strategy` 控制）：

- `llm`（默认）：LLM 逐条判断每条检索 chunk 是否与问题相关，返回 `relevant` / `not_relevant`。
- `embedding`：计算 question 与每条 chunk 的 Embedding 余弦相似度，**相似度 ≥ 0.5 判定为相关**。

基于每条 chunk 的相关性判定，计算：

| 指标 | 定义 | 公式 | 取值范围 |
|------|------|------|---------|
| **Precision@K** | 前 K 条检索结果中相关 chunk 的比例 | 相关条数 ÷ K | 0.0 – 1.0 |
| **Hit Rate** | 至少命中一条相关结果的用例占比 | 命中用例数 ÷ 总用例数 | 0.0 – 1.0 |
| **MRR**（Mean Reciprocal Rank） | 首个相关结果排名的倒数均值 | Σ(1/首个相关排名) ÷ 用例数 | 0.0 – 1.0 |
| **Recall@K** | 所有相关文档中被检索到的比例 | （预留，见下方备注） | 0.0 – 1.0 |

> **备注**：`Recall@K` 在配置项 `enable_recall_at_k` 中暴露（默认关闭），但当前聚合计算尚未输出到报告 `summary`。检索报告实际输出 `precision_at_k`、`hit_rate`、`mrr` 三项。

### 3.2 生成阶段指标

生成阶段用 LLM-as-Judge 打分，各指标默认 1–10 分。四个评分维度（`scoring_dimensions` 控制启用哪些）：

| 指标 | 含义 | 默认策略 | 可选策略 |
|------|------|---------|---------|
| **Correctness**（正确性） | 生成答案与参考答案的语义吻合度 | `llm` | `llm` / `embedding` / `hybrid` |
| **Faithfulness**（忠实度） | 答案是否只基于检索上下文、无幻觉 | `decompose` | `decompose` / `llm` |
| **Answer Relevance**（答案相关性） | 答案是否切题 | `reverse_question` | `reverse_question` / `llm` |
| **Quality**（综合质量） | 完整性、条理性、可读性综合评价 | `llm` | 仅 `llm` |

**评分策略说明**：

| 策略 | 计算方式 |
|------|---------|
| `llm` | LLM-as-Judge 直接打 1–10 分（夹在 [1, 10]），失败返回 `None`（不计入平均） |
| `embedding` | 余弦相似度 × 10，映射到 1–10 分（`max(1, round(sim × 10))`） |
| `hybrid` | LLM 分 × 0.7 + Embedding 分 × 0.3，四舍五入后夹在 [1, 10] |
| `decompose` | 见下方「Claim 拆解法」 |
| `reverse_question` | 见下方「反向问题法」 |

- **Claim 拆解法（`decompose`）**：LLM 将生成答案拆解为若干独立事实声明（claims）→ 逐条验证是否可由检索上下文推导 → 支撑数 ÷ 总数得到支撑比例 → 映射到 10 分制（`max(1, round(比例 × 10))`）。若答案无可验证事实，忠实度记为 1 分。
- **反向问题法（`reverse_question`）**：LLM 从生成答案反向生成 3 个候选问题 → 计算候选问题与原始问题的 Embedding 平均相似度 → 映射到 10 分制。

### 3.3 端到端指标

| 指标 | 定义 | 计算方式 | 取值范围 |
|------|------|---------|---------|
| **Context Precision** | 相关结果是否排在检索结果靠前位置 | 取自单条检索的 `precision_at_k` | 0.0 – 1.0 |
| **Context Recall** | 参考答案中的信息点是否都被检索到 | 拆解参考答案为 claims，检查被上下文覆盖的比例 | 0.0 – 1.0 |
| **Answer Similarity** | 生成答案与参考答案的语义相似度 | Embedding 余弦相似度 | 0.0 – 1.0 |

> **备注**：单条用例的 `context_recall` 会写入 `details`（当 `enable_context_recall=true`），但报告 `summary` 的端到端部分当前只汇总输出 `context_precision` 与 `answer_similarity` 两项。

### 3.4 人工评分

任务完成后可对每条用例提交人工评分（1–10 分，可附评语）。提交后报告 `summary.human_scores` 会输出：

```json
{
  "scored_count": 3,
  "average": 8.33
}
```

人工评分与自动指标并列，用于校准自动打分的一致性。

---

## 4. 评估结果（报告）格式与解读

任务完成后，`GET /tasks/{task_id}/report` 返回报告。报告顶层结构：

```json
{
  "task_id": 1,
  "name": "第一次测评",
  "status": "completed",
  "total_cases": 5,
  "completed_cases": 5,
  "summary": { ... },
  "details": [ ... ]
}
```

### 4.1 summary（汇总指标）

```json
{
  "total_cases": 5,
  "completed_cases": 5,
  "successful_cases": 5,
  "elapsed_seconds": 267.1,
  "retrieval": {
    "precision_at_k": 0.32,
    "hit_rate": 1.0,
    "mrr": 1.0
  },
  "generation": {
    "faithfulness": 8.2,
    "answer_relevance": 8.2,
    "correctness": 9.4,
    "quality": 7.0,
    "overall": 8.2
  },
  "end_to_end": {
    "context_precision": 0.32,
    "answer_similarity": 0.8818
  },
  "human_scores": null
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `total_cases` / `completed_cases` / `successful_cases` | 用例总数 / 已执行数 / 无错误成功数 |
| `elapsed_seconds` | 任务耗时（秒） |
| `retrieval` | 检索指标均值：`precision_at_k`、`hit_rate`、`mrr` |
| `generation` | 生成维度均值（各维度对全部用例取平均），`overall` 为各维度均值的算术平均 |
| `end_to_end` | 端到端指标均值 |
| `human_scores` | 人工评分汇总（未提交时为 `null`） |

### 4.2 details（逐条详情）

每条用例一条记录：

```json
{
  "index": 0,
  "question": "多模态大模型 OCR 的优势有哪些？",
  "expected_answer": "……",
  "generated_answer": "……",
  "retrieved_chunks": [
    { "chunk_id": "chunk_39_2", "content": "……", "score": 1.0 }
  ],
  "retrieval": { "precision_at_k": 1.0, "hit": true, "first_relevant_rank": 1 },
  "generation_scores": {
    "faithfulness": 10,
    "answer_relevance": 9,
    "correctness": 9,
    "quality": 8
  },
  "end_to_end": {
    "context_precision": 1.0,
    "context_recall": 0.9,
    "answer_similarity": 0.9215
  },
  "human_score": null,
  "human_comment": null
}
```

### 4.3 CSV 导出列

`GET /tasks/{task_id}/export?format=csv` 将逐条详情扁平化为以下列（导出 JSON 则为完整 `result_data` 原文）：

| 列名 | 含义 |
|------|------|
| `index` | 用例索引 |
| `question` / `expected_answer` / `generated_answer` | 问题 / 期望答案 / 生成答案 |
| `faithfulness` / `answer_relevance` / `correctness` / `quality` | 四个生成维度得分（1–10） |
| `context_precision` / `answer_similarity` | 端到端指标（0–1） |
| `human_score` / `human_comment` | 人工评分 / 评语 |

### 4.4 结果如何解读

- **检索指标**（0–1）：`hit_rate` 接近 1 说明基本每条问题都能命中相关内容；`mrr` 越接近 1 说明相关结果越靠前；`precision_at_k` 偏低通常意味着检索混入了无关 chunk，可尝试调高 `score_threshold` 或换检索模式。
- **生成指标**（1–10）：`faithfulness` 低说明存在幻觉（答案偏离检索上下文），应检查 chunk 质量或 prompt；`correctness` 低说明答案与参考答案不一致；`overall` 是四个维度的综合均值。
- **端到端**（0–1）：`answer_similarity` 衡量答案与参考答案的语义贴近度；`context_recall` 低说明参考答案中的关键信息点未被检索覆盖。
- **交叉验证**：可将 `human_score` 与 `correctness`/`overall` 对照，若自动分与人工分偏差大，说明 prompt 评分标准需校准。

---

## 5. 怎么使用

### 5.1 前置条件

- 已登录获取 JWT（请求头 `Authorization: Bearer <token>`）；
- 用户是目标空间的成员；**写操作**（上传测试集、创建/删除/取消任务）需 **EDITOR 及以上**，**读操作**（列表、报告、评分、导出）需 **MEMBER 及以上**；
- 任务详情/报告/评分/导出等操作仅**任务作者或空间管理员**可执行；
- 若使用 LLM/Embedding 打分，需在用户模型配置中已有可用的 LLM 与 Embedding 模型（或用默认模型）。

### 5.2 完整流程

路由统一前缀：`/api/v1/spaces/{space_id}/knowledge-bases/{kb_id}/evaluation`。

```text
1. POST /test-sets                上传测试集，得到 test_set_id
2. GET  /test-sets/{id}/cases     预览用例（可选）
3. POST /tasks                    创建评测任务（传 test_set_id + config），得到 task_id
4. GET  /tasks/{id}/progress      轮询进度（current / total）
5. GET  /tasks/{id}/report        任务完成后取汇总报告
6. POST /tasks/{id}/scores        提交人工评分（可选，仅 completed）
7. GET  /tasks/{id}/export        导出 JSON / CSV（可选，仅 completed）
```

### 5.3 评测配置（config）

创建任务时的 `config` 控制检索、生成与打分策略，未传字段使用默认值：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `search_mode` | `content_hybrid` | 检索模式（9 种，见下） |
| `top_k` | `5` | 检索返回条数（1–50） |
| `score_threshold` | `0.0` | 检索分数阈值（0–1） |
| `enable_generation` | `true` | 是否启用生成阶段 |
| `llm_model` / `embedding_model` | `null` | 指定模型名，空则用用户默认模型；执行后回写实际模型 |
| `retrieval_relevance_strategy` | `llm` | 检索相关性判断：`llm` / `embedding` |
| `enable_mrr` | `true` | 是否启用 MRR |
| `correctness_strategy` | `llm` | `llm` / `embedding` / `hybrid` |
| `faithfulness_strategy` | `decompose` | `decompose` / `llm` |
| `relevance_strategy` | `reverse_question` | `reverse_question` / `llm` |
| `enable_context_precision` / `enable_context_recall` / `enable_answer_similarity` | `true` | 端到端开关 |
| `scoring_dimensions` | `["correctness","faithfulness","relevance","quality"]` | 启用的生成评分维度 |

**检索模式 `search_mode` 可选值**：

| 值 | 含义 |
|----|------|
| `content_bm25` / `content_vector` / `content_hybrid` | 内容字段的全文 / 向量 / 混合检索 |
| `question_bm25` / `question_vector` / `question_hybrid` | 问题字段的全文 / 向量 / 混合检索 |
| `all_bm25` / `all_vector` / `all_hybrid` | 全字段全文 / 向量 / 融合检索 |

### 5.4 curl 示例

```bash
BASE="http://localhost:8100/api/v1/spaces/1/knowledge-bases/2/evaluation"

# 1. 上传测试集
curl -X POST "$BASE/test-sets" \
  -H "Authorization: Bearer <token>" \
  -F "file=@ocr_test_set.json" \
  -F "name=OCR 回归测试集"

# 2. 创建评测任务（默认配置 + 指定模型）
curl -X POST "$BASE/tasks" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "test_set_id": 3,
    "name": "第一轮测评",
    "config": {
      "search_mode": "content_hybrid",
      "top_k": 5,
      "llm_model": "glm-4-flash",
      "embedding_model": "embedding-3",
      "faithfulness_strategy": "decompose",
      "relevance_strategy": "reverse_question"
    }
  }'

# 3. 轮询进度
curl "$BASE/tasks/1/progress" -H "Authorization: Bearer <token>"

# 4. 取报告
curl "$BASE/tasks/1/report" -H "Authorization: Bearer <token>"

# 5. 导出 CSV
curl "$BASE/tasks/1/export?format=csv" -H "Authorization: Bearer <token>" -o report.csv
```

### 5.5 注意事项

- **异步执行**：任务创建后即返回 `pending`，后台最多 **5 路并发**执行；用 `/progress` 轮询状态（`pending → running → completed / failed / cancelled`）。
- **对比实验**：同一测试集可创建多个任务，用不同 `search_mode` / `top_k` / 模型做对照，报告间可横向比较。
- **失败排查**：任务 `failed` 时用 `GET /tasks/{id}` 查看 `error_message`；LLM 或 Embedding 客户端获取失败会导致任务直接失败。
- **删除约束**：存在 pending/running 关联任务时测试集不可删除；pending/running 任务不可删除。

---

## 6. 相关文档

- [`backend/docs/api/evaluation_api.md`](../../../backend/docs/api/evaluation_api.md)：接口级参考（每个端点的参数、响应、错误码）。
- [`knowledge-architecture-navigation.md`](./knowledge-architecture-navigation.md)：知识模块后端结构导航（含测评模块的归属）。
