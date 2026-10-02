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
- [`frontend-development-plan-2026-07.md`](./frontend-development-plan-2026-07.md)：前端开发计划（2026-07）
- [`REFACTOR-ragflow-style-migration.md`](./REFACTOR-ragflow-style-migration.md)：ragflow 务实单体风格迁移方案（✅ 2026-09-21 批次 0-6 全部合并 main，R1-R6 生效；详版规则见 backend/CLAUDE.md §import 依赖规则）
- [`REFACTOR-ragflow-style-alignment-round2.md`](./REFACTOR-ragflow-style-alignment-round2.md)：第二轮 ragflow 对齐（✅ 2026-09-21 全部批次完成；第三轮仪式清除未单独成文）
- [`engine-restructure-6x-revert-and-reorganize.md`](./engine-restructure-6x-revert-and-reorganize.md)：引擎抽库方案变更与 6x 批次执行记录（engines/ 目录分层已落地）
- [`REFACTOR-qa-rag-pipeline.md`](./REFACTOR-qa-rag-pipeline.md)：QA 检索增强问答管道重构（已实施，作架构记录保留）
- [`knowledge-operations-loop-plan.md`](./knowledge-operations-loop-plan.md)：知识运营闭环开发计划（✅ 2026-10-02 八批次全部完成——O1/O2/A1/A2/B1/B2/C/D + 前端批次；当前事实见 [`../../knowledge-space/current/kb-ops-loop-summary.md`](../../knowledge-space/current/kb-ops-loop-summary.md)）

## 使用约定

- 需要追溯设计演进、历史迁移或旧命名来源时，再阅读这里。
- 如果本文档与当前代码或正式文档冲突，以当前代码和正式文档为准。
