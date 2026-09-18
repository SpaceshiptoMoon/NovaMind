# Active Plans

本目录保存仍可能继续演进、仍值得作为后续优化输入的计划文档。

这些文档通常满足至少一个条件：

- 其中的目标还没有完全完成
- 其中的结构清理方向对当前仓库仍有参考价值
- 它们仍适合作为下一轮工程整理的工作底稿

## 当前文档

- [`engine-restructure-6x-revert-and-reorganize.md`](./engine-restructure-6x-revert-and-reorganize.md)：引擎抽库方案变更与 6x 批次执行记录（engines/ 目录分层已落地；agent/rag/eval/resume/deep_research 已迁入）
- [`agent-capability-enhancement-plan.md`](./agent-capability-enhancement-plan.md)：Agent 能力增强（loop detection / 审批 / 观测 / planning flow）
- [`REFACTOR-qa-rag-pipeline.md`](./REFACTOR-qa-rag-pipeline.md)：QA 检索增强问答管道重构（已实施，作架构记录保留）
- [`agent-capability-pluggable-plan.md`](./agent-capability-pluggable-plan.md)：Agent 能力可插拔化（MCP / 搜索 / 工具；G2/G3 已被 2026-08 用户决策推翻，仅保留参考价值）

已完成的仓库结构清理四部曲与媒体问题修复记录（2026-07）已移入 [`../historical/`](../historical/)。

## 使用约定

- 这些文档仍然是计划材料，不应替代正式设计文档。
- 若其中结论已经成为当前事实，应把结论迁移到 `docs/knowledge-space/current/` 或其他正式文档中。
