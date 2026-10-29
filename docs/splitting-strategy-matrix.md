# 切分策略实测矩阵

> 2026-10-29 端到端实测。2 种文档形态 × 8 种切分策略 = 16 个文档，经真实解析管道
> （上传 → arq 任务 → default 解析 → 切分 → embedding → ES）逐策略触发，块数据取自
> chunks API。统一 `chunk_size=200, chunk_overlap=20, parent_chunk_size=800`。

## 文档形态

| 形态 | 文件 | 长度 | 特征 |
|------|------|------|------|
| A 结构化 | `A_structured.txt` | 732 字符 | Markdown 标记：1 个 `#` + 5 个 `##` + 段落 |
| B 叙事 | `B_narrative.txt` | 771 字符 | 无结构标记的连续中文叙事长文 |

## 实测矩阵（修复后终态）

| 策略 | 形态 | 块数 | min | max | avg | 行为解读 |
|------|------|-----:|----:|----:|----:|----------|
| recursive | A | 5 | 130 | 197 | 162 | 基线：按段落递归切，稳定尊重 chunk_size |
| recursive | B | 5 | 139 | 182 | 164 | 同上 |
| fixed_size | A | 5 | 89 | 200 | 177 | 硬切：max 恰为上限（边界截断），不感知结构 |
| fixed_size | B | 5 | 100 | 200 | 180 | 同上 |
| markdown | A | 5 | 129 | 197 | 159 | 标题/段落聚合；尊重 chunk_size（修复后） |
| markdown | B | 5 | 139 | 179 | 163 | 无标记文本退化为段落聚合，仍守上限 |
| semantic | A | 5 | 129 | 197 | 159 | 真实调 embedding 按句向量边界聚合（块内容与 markdown 不同，长度统计趋同） |
| semantic | B | 5 | 139 | 179 | 163 | 叙事文本的语义边界切分；成本最高（每候选块调 embedding） |
| delimiter | A | 4 | 169 | 198 | 184 | `separators: ["\n\n", "\n", "。"]` 配置被消费 |
| delimiter | B | 5 | 134 | 172 | 158 | 同上 |
| sentence_window | A | 16 | 27 | 81 | 49 | 句子级小块 + `expansion_window_size=2` 窗口元数据（检索时扩展上下文） |
| sentence_window | B | 21 | 9 | 77 | 42 | 同上；块数最多、单块最小 |
| parent_child | A | 8 | 44 | 769 | 203 | 两层结构：子块（小）检索 + 父块（~770）喂 LLM；`chunk_role=parent` 元数据 |
| parent_child | B | 8 | 44 | 780 | 206 | 同上 |
| hierarchical | A | 5 | 112 | 201 | 157 | 按内容层级聚合 |
| hierarchical | B | 2 | 185 | 642 | 413 | 叙事文层级少 → 大块聚合（层级感弱的内容不适用） |

## 选型建议（实测结论）

- **默认/未知形态**：`recursive`（基线稳定）或 `parent_child`（检索精度优先，小子块召回 + 大父块生成，RAG 主流推荐）。
- **Markdown/结构化文档**：`markdown`（标题层级保留）。
- **叙事长文、语义边界重要**：`semantic`（注意 embedding 调用成本约为其他策略的一个数量级）。
- **精确引用/问答**：`sentence_window`（小块高精度命中 + 窗口扩展防上下文丢失）。
- **已知固定分隔符的语料**（日志、对话记录）：`delimiter`。
- **长文档分层摘要场景**：`hierarchical`（对无层级叙事文会退化为大块）。
- `fixed_size` 仅建议作为基线对照——不感知任何结构。

## 实测揪出并已修复的缺陷

1. **markdown/semantic 的 chunk_size 配置静默失效**（`29be3782` 之前的 `fix(engines)` 第一笔）：
   工厂只读引擎内部键 `max_chunk_size`，而 `extract_splitting_params` 为缺失的该键补全局
   默认 1000——用户配 `chunk_size=200` 实跑 1000（markdown 出 1 块 818、semantic 出 2 块
   avg 400）。修复：统一经 `_chunk_size_param` 优先 `chunk_size`、回落 `max_chunk_size`。
2. **markdown 小块合并无上限守卫**（`29be3782`）：`min_chunk_size`（默认 500）逼近或超过
   chunk_size 时，`_merge_small_chunks` 把按上限切出的块链式并回单块（复测：配 200 实出
   1 块 809）。修复：并入前块后若超上限则独立保留（内容不丢，与 P1#10 防丢语义一致）；
   工厂层 markdown 块下限同步收敛到不超过上限。

回归测试：`tests/engines/document/test_splitter_factory_chunk_size.py`（7 项）；
金样 60 项 + md 回归 14 项全绿。

## 局限

- 语料为小样本（<800 字符/篇），大文档（多页/多章节）下的块数分布与合并行为未覆盖；
- `semantic` 的相似度阈值用默认值，未做阈值敏感性实验；
- 矩阵只覆盖 default 解析路径；deepdoc 路径（layout 感知重切分）下各策略的交互未单独实测；
- 检索质量维度（哪种策略命中率更高）需接 evaluation 流程，本矩阵只覆盖切分行为本身。
