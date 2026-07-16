# 交接记录

本目录保存阶段性交接说明，主要写给后续接手的维护者或 Agent。

与正式设计文档不同，交接记录是时间快照。它们通常描述：

- 当时刚完成了什么改动
- 当时认为还有哪些问题或风险
- 下一位接手者需要重点关注什么

因此，这些文档适合提供历史背景，但不应被视为当前仓库结构的唯一真相。

## 分层入口

- [`active/README.md`](./active/README.md)：活跃 handover 入口
- [`historical/README.md`](./historical/README.md)：已归档 handover 入口

## 如何使用这些记录

1. 只有在你继续同一块工作时，再读对应交接文件。
2. 对里面提到的路径、导入、TODO 和风险，都要以当前仓库状态重新核对。
3. 当前正式说明优先看：
   - [`../knowledge-space/README.md`](../knowledge-space/README.md)
   - [`../knowledge-space/current/README.md`](../knowledge-space/current/README.md)
   - [`../deepdoc/deepdoc-integration.md`](../deepdoc/deepdoc-integration.md)
   - [`../project-structure-navigation.md`](../project-structure-navigation.md)

## 维护约定

如果一份交接记录成为某项关键设计决策的唯一来源，应把那部分内容提升到 `docs/` 下更正式的文档中。
