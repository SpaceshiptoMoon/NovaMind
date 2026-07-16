# NovaMind 前端

NovaMind 前端是一个基于 Vue 3 + TypeScript 的应用，为知识空间、知识库管理、RAG 聊天、深度研究、Agent、技能广场、通知中心、应用中心和 ClawMate 提供用户界面。

## 技术栈

- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router
- Element Plus
- Vitest
- ESLint + Prettier

## 主要页面域

当前前端主要包含这些区域：

- `auth`：登录、忘记密码、重置密码
- `space`：空间列表、知识库、KB 配置、文档、任务批次、检索、评测、空间设置
- `chat`：AI 聊天工作区
- `agent`：Agent 列表与 Agent 聊天
- `research`：深度研究与历史记录
- `skill`：技能广场、管理审核、技能详情
- `app`：应用中心与简历挖掘等场景页
- `clawmate`：浏览器终端和 AI 辅助工作区
- `user`：个人资料、通知、修改密码、模型配置、用户管理

## 目录结构

```text
frontend/
|- public/
|- src/
|  |- api/           # API 封装和共享请求类型
|  |- assets/        # 本地资源
|  |- components/    # 复用 UI 组件
|  |- composables/   # Vue composables
|  |- layouts/       # 页面布局
|  |- router/        # 路由定义和守卫
|  |- stores/        # Pinia 状态管理
|  |- types/         # 本地 TypeScript 类型
|  |- utils/         # 工具函数
|  `- views/         # 路由级页面
|- package.json
`- vite.config.ts
```

知识库相关 UI 主要集中在：

- `src/views/space/`
- `src/components/knowledge/`
- `src/api/knowledge/`

## 环境要求

- Node.js `^20.19.0 || >=22.12.0`
- 与当前 Node 版本兼容的 npm

## 本地开发

```bash
cd frontend
npm install
npm run dev
```

默认开发地址：

- `http://localhost:5173`

在常规本地全栈联调模式下，前端默认请求运行在 `http://localhost:8100` 的后端。

## 质量检查

```bash
cd frontend
npm run type-check
npm run test:unit -- --run
npm run lint
npm run format
```

## 构建

```bash
cd frontend
npm run build
npm run preview
```

## 关键路由

主要路由组包括：

- `/`
- `/login`
- `/forgot-password`
- `/reset-password`
- `/home`
- `/home/spaces`
- `/home/workspace/chat`
- `/home/workspace/agents`
- `/home/workspace/research`
- `/home/workspace/skills`
- `/home/workspace/clawmate`
- `/home/apps`

## 前端协作约定

- Vue 组件和页面优先使用 `PascalCase` 命名。
- Store 保持小而聚焦，避免一个 store 承担过多业务。
- 新增工具函数、store 行为和关键交互时，优先补测试。
- 如果 UI 改动影响根文档中的截图、流程或说明，请在同一个 PR 里一起更新文档。

## 相关文档

- 项目总览：[`../README.md`](../README.md)
- 后端说明：[`../backend/README.md`](../backend/README.md)
- 文档总入口：[`../docs/README.md`](../docs/README.md)
- 前端专题文档：[`../docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md`](../docs/frontend/FRONTEND-MULTIMODAL-DESIGN.md)
