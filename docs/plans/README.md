# 计划与重构文档

本目录保存仓库的执行计划、重构提案、检查清单和历史方案。

为了减少“过程文档”和“当前事实”混杂，本目录现在做了物理分层：

- [`active/README.md`](./active/README.md)：仍可能继续演进、仍可作为后续工作输入的计划材料
- [`historical/README.md`](./historical/README.md)：主要用于追溯历史重组、迁移和早期方案

如果你是第一次理解本仓库，建议先看：

1. [`../../README.md`](../../README.md)
2. [`../README.md`](../README.md)
3. [`../project-structure-navigation.md`](../project-structure-navigation.md)
4. [`../../ROADMAP.md`](../../ROADMAP.md)

## 使用建议

- `active/` 不等于“已经落地”，而是“仍值得继续参考”。
- `historical/` 不等于“无价值”，而是“主要用于追溯上下文，不应直接代表当前实现”。
- 如果计划文档与当前代码或 `docs/knowledge-space/current/` 下的正式文档冲突，以当前代码和正式文档为准。
- 如果某项计划已经落地完成，应优先把结论沉淀到正式架构文档，而不是继续扩写旧计划。
