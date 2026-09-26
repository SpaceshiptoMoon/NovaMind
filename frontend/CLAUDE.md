# CLAUDE.md - Frontend

## Overview

The frontend is a Vue 3 + TypeScript application.

Its job is to present workspace, knowledge-base, agent, and multimodal configuration flows clearly while staying aligned with backend API contracts.

## Directory Structure

- `src/api/`: typed API access by domain
- `src/components/`: reusable UI components by domain
- `src/views/`: route-level pages
- `src/stores/`: Pinia stores
- `src/router/`: route definitions
- `src/layouts/`: app shells and structural layouts
- `src/types/`: shared frontend types
- `src/utils/`: frontend-only helpers

## Domain Grouping Rules

Keep domain code together.

Knowledge-base related UI should primarily live in:

- `src/api/knowledge/`
- `src/components/knowledge/`
- `src/views/space/`

Do not scatter knowledge-base form logic across unrelated generic folders if it can stay inside the knowledge domain.

## Component Boundaries

- Views orchestrate data loading, page state, and route context
- Domain components render reusable business UI
- Generic base components should stay presentation-focused
- Stores manage shared client state, not page-local temporary UI state unless reused

## Coding Rules

- TypeScript only for new logic
- 2-space indentation
- `PascalCase` for Vue SFC names
- `camelCase` for composables, stores, utilities
- Prefer strongly typed API responses and form models
- Keep watchers and side effects readable and local

## UI and UX Rules

- Preserve the existing design language unless a redesign is intentional
- Knowledge-base config pages should make structure and processing flow obvious
- Complex forms should group by user intent, not backend implementation detail
- Use labels and helper text to explain mutually exclusive options and fallback behavior

## Layout Robustness Rules（抗压缩布局规范）

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

## API Alignment Rules

- Frontend config models must match backend schema shape
- If backend config nesting changes, update:
  - API types
  - form state
  - submit transform
  - display logic
  - docs if needed
- Do not silently rename fields on the frontend without confirming backend compatibility

## Validation Workflow

Run locally when relevant:

- `npm run dev`
- `npm run type-check`
- `npm run lint`
- `npm run format`
- `npm run build`

If existing unrelated type errors already exist, state that clearly and still verify the touched area as far as possible.

## When Editing Frontend Code

- Check whether a change belongs in `view`, `component`, `store`, or `api`
- Prefer extending existing domain components before adding duplicates
- Keep forms understandable for both users and future developers
- When changing backend-facing config screens, verify the payload shape being submitted
