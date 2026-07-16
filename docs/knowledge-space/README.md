# 知识空间文档

本目录收纳 NovaMind 知识空间与知识库子系统的文档。

为了让公开仓库读者、维护者和后续接手者更快判断“什么是当前事实、什么只是历史过程”，这里明确分成两层：

- `current/`：当前有效的架构、流程和实现设计文档
- `process/`：历史计划、迁移记录、阶段性改造说明和改进草案

如果你想理解系统现在是怎么工作的，应优先阅读 `current/`。只有在需要追溯设计演进、迁移背景或历史决策时，再进入 `process/`。

## 建议阅读顺序

1. [`current/knowledge-architecture-navigation.md`](./current/knowledge-architecture-navigation.md)：知识模块结构导航
2. [`current/document-processing-flow.md`](./current/document-processing-flow.md)：文档上传到处理的运行流程
3. [`current/knowledge-config-structure-design.md`](./current/knowledge-config-structure-design.md)：知识库配置结构与设计边界
4. `process/` 下的历史文档：仅在需要追溯演进背景时阅读

## 当前正式文档

- [`current/README.md`](./current/README.md)：当前有效文档索引
- [`current/knowledge-architecture-navigation.md`](./current/knowledge-architecture-navigation.md)
- [`current/document-processing-flow.md`](./current/document-processing-flow.md)
- [`current/knowledge-config-structure-design.md`](./current/knowledge-config-structure-design.md)

## 过程与历史文档

- [`process/README.md`](./process/README.md)：历史与迁移文档索引
- [`process/knowledge-reorg-status.md`](./process/knowledge-reorg-status.md)
- [`process/knowledge-reorg-plan.md`](./process/knowledge-reorg-plan.md)
- [`process/knowledge-reorg-migration-summary.md`](./process/knowledge-reorg-migration-summary.md)
- [`process/IMPROVEMENT-enterprise-kb.md`](./process/IMPROVEMENT-enterprise-kb.md)

## 维护约定

- 新的正式设计结论优先写入 `current/`，不要只留在计划或交接文档中。
- 历史计划、执行记录和迁移说明应放入 `process/`，避免和当前事实混杂。
- 如果 `process/` 文档与代码或 `current/` 文档冲突，以当前代码和 `current/` 文档为准。
