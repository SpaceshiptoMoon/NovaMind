# 文档导航

`docs/` 目录同时包含两类内容：

- 面向外部读者和维护者的正式设计、结构与导航文档
- 研发过程中的计划、交接和阶段性记录

如果你是第一次阅读本仓库，建议先看本页列出的入口，而不是直接从 `plans/` 或 `handover/` 开始。

## 推荐阅读顺序

1. [`../README.md`](../README.md)：项目定位、部署方式、模块总览
2. [`../ROADMAP.md`](../ROADMAP.md)：当前阶段公开路线图
3. [`project-structure-navigation.md`](./project-structure-navigation.md)：仓库与代码结构导航
4. 子系统入口文档：
   - [`knowledge-space/README.md`](./knowledge-space/README.md)
   - [`deepdoc/deepdoc-integration.md`](./deepdoc/deepdoc-integration.md)
   - [`frontend/FRONTEND-MULTIMODAL-DESIGN.md`](./frontend/FRONTEND-MULTIMODAL-DESIGN.md)

## 面向外部读者的主要文档

### 通用导航

- [`project-structure-navigation.md`](./project-structure-navigation.md)：快速定位后端、前端和知识处理相关代码

### 知识空间 / 知识库

- [`knowledge-space/README.md`](./knowledge-space/README.md)：知识空间文档首页，区分当前设计文档和过程性文档
- [`knowledge-space/current/README.md`](./knowledge-space/current/README.md)：当前有效的知识空间设计文档索引
- [`knowledge-space/process/README.md`](./knowledge-space/process/README.md)：知识空间历史与迁移文档索引
- [`knowledge-space/current/knowledge-architecture-navigation.md`](./knowledge-space/current/knowledge-architecture-navigation.md)：知识相关模块导航
- [`knowledge-space/current/document-processing-flow.md`](./knowledge-space/current/document-processing-flow.md)：文档处理流程摘要
- [`knowledge-space/current/knowledge-config-structure-design.md`](./knowledge-space/current/knowledge-config-structure-design.md)：知识配置结构设计

### DeepDoc

- [`deepdoc/deepdoc-integration.md`](./deepdoc/deepdoc-integration.md)：DeepDoc 集成说明
- [`deepdoc/deepdoc-acceptance-checklist.md`](./deepdoc/deepdoc-acceptance-checklist.md)：DeepDoc 验收清单

### Frontend

- [`frontend/FRONTEND-MULTIMODAL-DESIGN.md`](./frontend/FRONTEND-MULTIMODAL-DESIGN.md)：前端多模态设计说明

## 过程性文档

以下目录更多用于保留研发背景，不建议作为首次阅读入口：

- `handover/`：阶段性交接记录，入口见 [`handover/README.md`](./handover/README.md)，并已分为 `active/` 与 `historical/`
- `plans/`：重构、清理和执行计划，入口见 [`plans/README.md`](./plans/README.md)，并已分为 `active/` 与 `historical/`
- `superpowers/`：专项实验与方案草稿
- `knowledge-space/process/`：知识模块重组和改造过程文档

如果你需要追溯设计演进、评估历史决策，或者接手某一项尚未完成的工作，再进入这些目录会更合适。

## 文档维护约定

- 新增公开能力时，优先更新根 `README.md` 和本页导航
- 新增深度设计文档时，放到最接近对应子系统的目录，并在本页补链接
- 计划、交接、临时分析与落地后的正式文档应分开，避免首页导航被过程文档淹没
