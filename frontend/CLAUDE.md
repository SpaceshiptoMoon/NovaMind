# CLAUDE.md — 前端

## 概述

前端是 Vue 3 + TypeScript 应用。

职责：清晰呈现工作台、知识库、智能体与多模态配置流程，同时与后端 API 契约保持对齐。

## 目录结构

- `src/api/`：按领域分组的带类型 API 访问
- `src/components/`：按领域分组的可复用 UI 组件
- `src/views/`：路由级页面
- `src/stores/`：Pinia store
- `src/router/`：路由定义
- `src/layouts/`：应用外壳与结构性布局
- `src/types/`：前端共享类型
- `src/utils/`：前端专用辅助函数

## 领域分组规则

领域代码聚拢存放。

知识库相关 UI 主要放在：

- `src/api/knowledge/`
- `src/components/knowledge/`
- `src/views/space/`

能留在知识领域内部的知识库表单逻辑，不要散落到无关的通用目录。

## 组件边界

- view 负责编排数据加载、页面状态与路由上下文
- 领域组件渲染可复用的业务 UI
- 通用基础组件保持纯展示职责
- store 管理共享客户端状态；页面局部临时 UI 状态不放 store，除非确有复用

## 编码规则

- 新逻辑一律 TypeScript
- 2 空格缩进
- Vue 单文件组件（SFC）命名用 `PascalCase`
- composable、store、工具函数用 `camelCase`
- API 响应与表单模型优先强类型
- watcher 与副作用保持可读且局部化

## UI 与 UX 规则

- 非有意重设计时，保持既有设计语言
- 知识库配置页应让结构与处理流程一目了然
- 复杂表单按用户意图分组，而非按后端实现细节分组
- 用标签与辅助文字说明互斥选项与兜底行为

## 抗压缩布局规范

以 `src/views/space/DocumentTaskBatchView.vue`（任务列表页）为黄金基准：任意视口宽度（含 F12 手动压缩到极窄）下不穿模、不溢出、文字与容器框完整。新页面/改版必须达到同等鲁棒性，规则如下：

### 布局骨架（高度/宽度链完整性）

- Flex 主轴滚动链上每一层容器必须显式闭合：纵向 flex 列写 `min-height: 0`，横向 flex 行写 `min-width: 0`。漏掉任意一层，flex 子项会以内容固有尺寸撑破父容器（即「穿模」的根因）。
- 可收缩的内容列用 `flex: 1` + `min-width: 0` 组合；固定列（侧栏、右侧信息列）用 `flex-shrink: 0` + 显式 `width`，绝不允许被压缩。
- 栅格统计卡用 `grid-template-columns: repeat(N, minmax(0, 1fr))`——`minmax(0, 1fr)` 的下限 0 是关键，裸 `1fr`（即 `minmax(auto, 1fr)`）会让长内容卡住轨道导致整行溢出。

### 文本溢出收敛（防文字撑破框）

- 单行文本（文件名、slug、ID、chip 标签）：固定搭配 `overflow: hidden; text-overflow: ellipsis; white-space: nowrap`，且其最近 flex 父项必须有 `min-width: 0`。
- 不可断行的短标签/徽标：`white-space: nowrap` + `flex-shrink: 0`，保证压缩时整体保留而非折行错位。
- 多行长文本（错误信息等）：`word-break: break-word` 或 `overflow-wrap: anywhere`，允许在任意字符处换行。
- 表格列给 `min-width`（如 el-table-column 的 `min-width` 属性），让表格在容器内横向滚动而不是挤压到文字重叠。

### 响应式降级（窄屏换结构，不硬扛）

- 断点处用 `@media` 主动改变布局形态而非让 flex 硬撑：`grid` 列数 4→2→1 递减、横向行改 `flex-direction: column`、固定侧列改 `width: 100%`、`nowrap` 行改 `flex-wrap: wrap`。
- 布局必须同时覆盖三档：宽屏（完整三栏/四列）、中屏（断点降列）、窄屏（纵向堆叠）。只写宽屏样式 = 窄屏必穿模。

### 验证口径

- 交付前用浏览器 DevTools 拖拽视口从最宽压到 ~320px，全程检查：文字不溢出容器、边框/圆角不裁切内容、无横向滚动条（除表格/代码块等有意横向滚动的区域）、布局在断点处平滑切换无跳变。

## API 对齐规则

- 前端配置模型必须匹配后端 schema 形状
- 后端配置嵌套变化时，同步更新：
  - API 类型
  - 表单状态
  - 提交转换
  - 展示逻辑
  - 需要时更新文档
- 未经后端兼容性确认，不在前端静默重命名字段

## 验证工作流

相关场景下本地运行：

- `npm run dev`
- `npm run type-check`
- `npm run lint`
- `npm run format`
- `npm run build`

若已存在与本次改动无关的类型错误，明确说明这一点，并尽可能验证被触碰的区域。

## 修改前端代码时

- 先确认改动属于 `view`、`component`、`store` 还是 `api`
- 优先扩展现有领域组件，而不是添加重复项
- 表单要对用户和未来的开发者都可理解
- 改面向后端的配置界面时，验证实际提交的 payload 形状
