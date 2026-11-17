# 评测归因分析设计（五阶段 15 类）

> 2026-11-17 定稿并实施（E1 引擎 / E2 报告 / E3 闭环）。本文是分类法与判定链的权威参考。

## 定位

评测回答「多少分」，归因分析回答「为什么是这个分、该修什么」。与线上点踩归因（四分法）互补：
**线上单点失败走 gap 流，测试集批量失败走质量基线流**，两路根因词表对齐
（S1↔content_gap、R1-R3↔retrieval_failure），最终都汇入运营待办。

## 错误分类法（五阶段 15 类，按数据流向）

| 组 | 类别 | 判定依据 | 处置方 |
|---|---|---|---|
| **S 源数据** | source_missing | L0-L4 全 miss | 补文档（进 gap 流） |
| | source_defect | 检索到+忠实引用+与期望不符+上下文不含答案 | 修源文档 |
| **P 解析入库** | parse_failed | ES 无 chunk + 最新任务 FAILED/未完成 | 重解析 |
| | parse_defect | 源对但 chunk 丢失/错乱（deep_check） | 换解析配置 |
| | chunk_fragmentation | gold 替换变好 + 碎片率高 | 调切分 |
| | index_sync_missing | 文档在、任务完成、chunk 未入索引 | 重建索引 |
| **R 检索** | ranking_issue | 扩窗重放命中 | 调权重/rerank/top_k |
| | mode_mismatch | 换模式命中 | 调检索模式 |
| | embedding_gap | 索引有但语义检索不到 | 重建向量/换模型 |
| | permission_boundary | 权限旁路重放命中 | 权限配置 |
| **G 生成** | context_underuse | 上下文含答案、忠实、没答出 | prompt/模型 |
| | hallucination | 答案与上下文矛盾 | 模型忠实度 |
| **Q 问题侧** | case_label_error | 语义比对判答案其实对 | 修测试集 |
| | case_out_of_scope | LLM 判超出知识库定位/歧义 | 修用例 |
| | query_quality | 归一化后 BM25 重放命中 | 修表述/改写配置 |

## 判定链（成本分层：重放零 LLM → LLM 仅失败用例 → deep_check 控最贵的深检）

```
检索 miss:
  L0 权限旁路 → L1 扩窗(×3/阈值0) → L2 换模式 → Q3 归一化重搜
  → L3 ES 直查(在索引→embedding_gap) → P1/P4 查任务表 → Q2 LLM 超范围 → S1 兜底

生成差(命中但 correctness/quality < 5.0):
  G1 gold 替换重生成变好 → 碎片率高 P3 / 低并 R1
  G2 语义对→Q1 → 与上下文矛盾→D2 幻觉 → 上下文充分性:
      不含→S2（deep_check 再判 P2/S2） / 含→G1 利用不足 / 判不出→不归因
```

失败方向安全：任何判定异常降级到下一级或兜底，绝不影响评测主流程。

## 实施归属

- 引擎：`features/evaluation/services/attribution_analyzer.py`（AttributionAnalyzer，依赖全注入可测）；L0-L3 从 evaluation_service 迁入，旧 `_diagnose_retrieval_failure` 薄委托保持异常安全契约
- 配置：`EvaluationConfig.enable_attribution`（默认开）/ `attribution_deep_check`（默认关——P2/S2 源文档对照是近似判定，confidence=low）
- prompt：6 个 `eval_attr_*` 模板（evaluation_prompts.py 注册）
- 报告：`summary.attribution = {by_stage, by_category, hotspot_documents, attributed_cases, deep_checked}`；miss 协程内已判的 failure_diagnosis 汇总段只补 stage 不重放
- 前端：KbEvaluationView 报告弹窗「归因分析」区（五阶段分布条/类别 chip/重灾文档）
- 运营出口：`OpsTodoService._attribution_todos` 第四探针——S/P 六类进收件箱（R/G/Q 不进：检索配置/模型侧不走待办），`todo_key=eval:{task_id}:{category}` 天然幂等
- 回归告警：quality_baseline cron 消化上一轮跑批（judge_regression），回归 → 通知管理员 + baseline_regression 动作，exists_by_action_target 幂等

## 遗留

- 真机完整跑批 + 归因区真数据验证（演示库无完成任务，随 quality_baseline_enabled 打开后验证）
- 对比视图的归因 delta 未做（get_report_comparison 未透传 attribution）
- P2/S2 深检不拉源文档原文（chunk 集合近似，已注明 confidence）
