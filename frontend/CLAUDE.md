# CLAUDE.md — Frontend

## 一、功能模块

Vue 3 + TypeScript 前端应用，按域组织页面视图，Pinia 管理状态，Axius + SSE 与后端通信。

### Store → 视图 → API 对应关系

| 功能域 | Store | 主要视图 | API 模块 | 后端路由前缀 |
|--------|-------|---------|---------|-------------|
| **用户认证** | `stores/user.ts` | `LoginView`, `UserProfileView`, `UserManageView`, `ModelConfigView` | `api/user.ts` | `/api/v1/user` |
| **知识空间** | `stores/space.ts` | `SpaceListView`, `KnowledgeBaseView`, `KbConfigView`, `DocumentView`, `DocumentDetailView`, `SearchView`, `SpaceSettingsView` | `api/space.ts`, `api/knowledgeBase.ts`, `api/document.ts`, `api/search.ts`, `api/member.ts` | `/api/v1/spaces` |
| **知识库评估** | — | `KbEvaluationView` | `api/evaluation.ts` | `.../evaluation` |
| **AI 对话** | `stores/chat.ts` | `ChatView` | `api/chat.ts`, `api/session.ts` | `/api/v1/ai-chat`, `/api/v1/qa` |
| **深度研究** | `stores/research.ts` | `ResearchView`, `ResearchHistoryView` | `api/research.ts` | `.../deep-research` |
| **AI Agent** | `stores/agent.ts` | `AgentView`, `AgentChatView` | `api/agent.ts` | `/api/v1/agent` |
| **技能市场** | `stores/skill.ts` | `SkillMarketplaceView`, `SkillDetailView`, `SkillAdminView` | `api/skill.ts` | `/api/v1/skills` |
| **ClawMate** | `stores/clawmate.ts` | `ClawMateView` | `api/clawmate.ts` | `/clawmate` |
| **应用中心** | — | `AppView`, `ResumeApp`, `ResumeHistory` | `api/app.ts` | `/api/v1/apps` |

### 页面路由总览

| 前端路由 | 页面 | 布局 |
|---------|------|------|
| `/` | 着陆页 | 无 |
| `/login` | 登录 | AuthLayout |
| `/forgot-password` | 忘记密码 | AuthLayout |
| `/reset-password` | 重置密码 | AuthLayout |
| `/home` | 首页仪表盘 | MainLayout |
| `/home/profile` | 个人资料 | MainLayout |
| `/home/notifications` | 通知中心 | MainLayout |
| `/home/change-password` | 修改密码 | MainLayout |
| `/home/settings/models` | 模型配置 | MainLayout |
| `/home/admin/users` | 用户管理 (admin) | MainLayout |
| `/home/spaces` | 空间列表 | MainLayout |
| `/home/spaces/:id/knowledge-bases` | 知识库管理 | MainLayout |
| `/home/spaces/:id/knowledge-bases/:kbId/documents` | 文档管理 | MainLayout |
| `/home/spaces/:id/knowledge-bases/:kbId/evaluation` | 知识库评估 | MainLayout |
| `/home/spaces/:id/knowledge-bases/:kbId/config` | 知识库配置（解析/分块/生成向导） | MainLayout |
| `/home/spaces/:id/documents/:docId` | 文档详情 | MainLayout |
| `/home/spaces/:id/search` | 搜索 | MainLayout |
| `/home/spaces/:id/settings` | 空间设置+成员 | MainLayout |
| `/home/apps` | 应用中心 | MainLayout |
| `/home/apps/resume` | 简历挖掘 | MainLayout |
| `/home/apps/resume/history` | 简历历史 | MainLayout |
| `/home/apps/resume/session/:sessionId` | 简历挖掘会话 | MainLayout |
| `/home/workspace/chat` | AI 对话 | WorkspaceLayout |
| `/home/workspace/agents` | Agent 管理 | WorkspaceLayout |
| `/home/workspace/agents/:agentId/chat` | Agent 对话 | WorkspaceLayout |
| `/home/workspace/research` | 深度研究入口 | WorkspaceLayout |
| `/home/workspace/research/:spaceId` | 深度研究 | WorkspaceLayout |
| `/home/workspace/research/:spaceId/history` | 研究历史 | WorkspaceLayout |
| `/home/workspace/skills` | 技能广场 | WorkspaceLayout |
| `/home/workspace/skills/:skillId` | 技能详情 | WorkspaceLayout |
| `/home/workspace/skills/admin` | 技能审核 (admin) | WorkspaceLayout |
| `/home/workspace/clawmate` | ClawMate 助手 | WorkspaceLayout |

> 每个模块的完整 API 端点清单见根目录 [项目结构导航.md](../项目结构导航.md)。

## 二、结构导航

### 目录结构

```
src/
├── main.ts                        # 入口: Pinia + Router + ElementPlus
├── App.vue                        # 根组件 (<router-view>)
├── router/
│   ├── index.ts                   # 三层路由: Auth / Main / Workspace
│   └── guards.ts                  # JWT 认证守卫 + 管理员权限
├── api/
│   ├── index.ts                   # Axios 实例 + JWT 管理 + 401 自动刷新 + createSSEStream()
│   ├── types.ts                   # ~1390 行全局 TypeScript 类型定义
│   ├── user.ts                    # 用户: 登录/CRUD/模型配置     → /api/v1/user
│   ├── space.ts                   # 空间: CRUD/配置/搜索        → /api/v1/spaces
│   ├── knowledgeBase.ts           # 知识库: CRUD/配置           → .../knowledge-bases
│   ├── document.ts                # 文档: 上传/处理/下载        → .../documents
│   ├── search.ts                  # 搜索: 执行/模式/模型配置     → .../search
│   ├── chat.ts                    # AI 对话: SSE流式/附件/模型   → /api/v1/ai-chat
│   ├── session.ts                 # QA 会话: 消息/压缩配置       → /api/v1/qa
│   ├── research.ts                # 深度研究: SSE流式/历史       → .../deep-research
│   ├── evaluation.ts              # 评估: 测试集/任务/报告       → .../evaluation
│   ├── agent.ts                   # Agent: CRUD/SSE对话/MCP/工具 → /api/v1/agent
│   ├── skill.ts                   # 技能: 上传/市场/安装/审核    → /api/v1/skills
│   ├── app.ts                     # 应用: 简历挖掘              → /api/v1/apps
│   ├── clawmate.ts                # ClawMate 对话: SSE 流式     → /clawmate
│   ├── notification.ts            # 通知: 列表/已读/偏好设置     → /notifications
│   └── member.ts                  # 成员: 邀请/加入/角色管理     → .../members
├── stores/                        # Pinia 状态管理 (Composition API)
│   ├── user.ts                    # JWT 登录/登出/Profile/localStorage 恢复
│   ├── space.ts                   # 空间列表/搜索/当前选中
│   ├── chat.ts                    # 会话/消息/流式发送/附件/压缩配置
│   ├── agent.ts                   # Agent CRUD/对话/工具调用/MCP/附件
│   ├── research.ts                # 研究流式/进度/报告/历史
│   ├── skill.ts                   # 市场/上传/安装/评分/审核
│   └── clawmate.ts                # ClawMate 对话: SSE 流式
├── layouts/                       # 布局组件
│   ├── AuthLayout.vue             # 认证页: 居中卡片 + Logo
│   ├── MainLayout.vue             # 主布局: AppHeader + 路由视图
│   ├── WorkspaceLayout.vue        # 工作区: 可折叠侧边栏 + 频道切换
│   └── AppHeader.vue              # 顶部导航: Logo + 导航链接 + 用户菜单
├── components/common/             # 12 个通用组件
│   ├── MarkdownRenderer.vue       # Markdown 渲染 (marked + highlight.js)
│   ├── Pagination.vue             # 分页器 (v-model 双向绑定)
│   ├── StatusTag.vue              # 状态标签 (颜色映射)
│   ├── EmptyState.vue             # 空状态占位 (3种 SVG 插图)
│   ├── BreadcrumbNav.vue          # 面包屑导航 (Space→KB→Document)
│   ├── PageHeader.vue             # 页面标题栏 (可选返回按钮)
│   ├── SearchBar.vue              # 搜索栏 (防抖)
│   ├── StatCard.vue               # 统计卡片
│   ├── FormSection.vue            # 表单分组
│   ├── ModelFanSelector.vue       # 模型扇形选择器
│   ├── NavIcon.vue                 # 自定义 SVG 导航图标
│   └── UnicornIcon.vue            # 品牌 Logo
├── views/                         # 页面视图 (按域组织)
│   ├── LandingView.vue            # 着陆页 (无需登录)
│   ├── HomeView.vue               # 首页仪表盘
│   ├── ForbiddenView.vue          # 403 无权限页
│   ├── NotFoundView.vue           # 404 页面未找到
│   ├── auth/LoginView.vue
│   ├── chat/ChatView.vue
│   ├── space/                     # SpaceListView, KnowledgeBaseView, DocumentView, ...
│   ├── research/                  # ResearchView, ResearchHistoryView
│   ├── agent/                     # AgentView, AgentChatView
│   ├── skill/                     # SkillMarketplaceView, SkillDetailView, SkillAdminView
│   ├── app/                       # AppView, resume/ResumeApp, resume/ResumeHistory
│   └── user/                      # UserProfileView, UserManageView, ModelConfigView
├── types/index.ts                 # 重导出 api/types.ts + RouteMeta 扩展
└── utils/
    ├── markdown.ts               # marked + highlight.js 渲染管线
    ├── document.ts               # 文档相关工具函数
    └── format.ts                 # 通用格式化工具
```

### 数据流

```
视图 (views/)
  → Store actions (stores/)
    → API 方法 (api/*.ts)
      → Axios request 或 createSSEStream (api/index.ts)
        → 后端 /api/v1/*
  ← Store state 更新
    ← 视图响应式渲染
```

### 关键约定

- **组件风格:** `<script setup lang="ts">` + Composition API
- **API 调用:** 使用 `request.get<T>()` 等类型安全方法
- **SSE 流式:** 使用 `createSSEStream()` + `AbortController`，不用 Axios 处理 SSE
- **类型定义:** 所有 API 类型放在 `api/types.ts`
- **视图命名:** PascalCase + `View` 后缀，放在 `views/{domain}/`

## 三、测试步骤

### 环境准备

```bash
cd frontend
npm install
```

### 类型检查

```bash
npm run type-check
```

无输出 = 通过。检查所有 `.ts` 和 `.vue` 文件的类型正确性。

### Lint 检查

```bash
npm run lint
```

先 oxlint 再 eslint，自动修复格式问题。无输出 = 通过。

### 格式化

```bash
npm run format
```

Prettier 格式化 `src/` 目录。

### 单元测试

```bash
npm run test:unit
```

Vitest 单元测试。

### 构建验证

```bash
npm run build-only
```

Vite 生产构建。构建成功 = 通过。

### 开发中的快速验证

```bash
# 启动前端 (代理 /api → localhost:8100)
npm run dev

# 浏览器访问对应页面路由
# 检查浏览器控制台无错误
# 验证功能正常路径 + 边界情况
```

### 新增功能的测试检查项

1. `npm run type-check` 通过 — 类型无误
2. `npm run lint` 通过 — 代码规范
3. `npm run build-only` 通过 — 构建成功
4. 浏览器访问对应页面路由 — 功能正常
5. 浏览器控制台无错误
6. SSE 流式功能：验证 `AbortController` 取消正常
7. 新 API 类型已添加到 `api/types.ts`
8. 新路由已添加到 `router/index.ts`
