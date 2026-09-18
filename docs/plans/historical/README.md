# Historical Plans

本目录保存主要用于追溯历史上下文的计划和重构文档。

它们通常具有以下特征：

- 针对已经完成的重组或迁移
- 描述较早期的目标结构、命名或兼容层策略
- 对理解历史决策有帮助，但不适合作为当前实现状态的直接依据

## 当前文档

- [`knowledge-reorg-commit-checklist.md`](./knowledge-reorg-commit-checklist.md)：知识重组的暂存与提交清单
- [`knowledge-reorg-commit-messages.md`](./knowledge-reorg-commit-messages.md)：建议提交信息
- [`backend-shared-knowledge-restructure-finalization.md`](./backend-shared-knowledge-restructure-finalization.md)：共享知识结构最终说明
- [`refactoring-plan-readable-summary.md`](./refactoring-plan-readable-summary.md)：更早期文档处理重构计划的可读摘要
- [`refactoring-plan.md`](./refactoring-plan.md)：更完整的早期历史计划原文
- [`repository-structure-cleanup-plan.md`](./repository-structure-cleanup-plan.md)：仓库结构清理整体方向（已完成，结论吸收进 CLAUDE.md 与导航文档）
- [`repository-structure-cleanup-implementation.md`](./repository-structure-cleanup-implementation.md)：清理实施指南
- [`repository-structure-cleanup-execution-plan.md`](./repository-structure-cleanup-execution-plan.md)：按批次展开的清理执行计划
- [`repository-structure-cleanup-thorough-implementation.md`](./repository-structure-cleanup-thorough-implementation.md)：更彻底的清理版本
- [`fix-upload-chunk-media-issues-2026-07.md`](./fix-upload-chunk-media-issues-2026-07.md)：上传 500 / 分块分页 / ASR 路径 / VLM 降级 / 坐标泄漏修复记录（2026-07，已全部修复）

## 使用约定

- 需要追溯设计演进、历史迁移或旧命名来源时，再阅读这里。
- 如果本文档与当前代码或正式文档冲突，以当前代码和正式文档为准。
