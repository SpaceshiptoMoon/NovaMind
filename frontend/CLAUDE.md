# 智能知识库前端项目

## 项目概述

基于 Vue 3 + TypeScript 的智能知识库前端应用，配套后端为 FastAPI 构建的智能知识库系统。

## 技术栈

| 技术 | 版本 | 说明 |
|------|------|------|
| Vue | 3.5+ | Composition API + `<script setup>` |
| TypeScript | 6.0 | 类型安全 |
| Vite | 8.0 | 构建工具 |
| Vue Router | 5.0 | 路由管理 |
| Pinia | 3.0 | 状态管理 |
| Element Plus | 2.13+ | UI 组件库 |

## 常用命令

```bash
# 安装依赖
npm install

# 开发服务器
npm run dev

# 生产构建
npm run build

# 类型检查
npm run type-check

# 代码检查 (oxlint + eslint)
npm run lint

# 代码格式化
npm run format

# 单元测试
npm run test:unit
```

## 项目结构

```
src/
├── assets/          # 静态资源
├── components/      # 通用组件
├── views/           # 页面视图
├── router/          # 路由配置
├── stores/          # Pinia 状态管理
├── App.vue          # 根组件
└── main.ts          # 入口文件
```

## 后端 API

- **基础 URL**: `http://localhost:8100/api/v1`
- **认证方式**: JWT Bearer Token
- **详细文档**: [docs/API_REFERENCE.md](docs/API_REFERENCE.md)

### 核心模块

| 模块 | 路由前缀 | 功能 |
|------|---------|------|
| 用户管理 | `/users` | 登录、注册、JWT 认证 |
| 知识空间 | `/spaces` | 多租户知识管理 |
| 智能问答 | `/ai-chat`, `/qa` | AI 对话、会话管理 |
| 深度研究 | `/spaces/{id}/deep-research` | 研究报告生成 |

## 代码规范

### Vue 组件

- 使用 Composition API + `<script setup lang="ts">`
- 组件命名：PascalCase (如 `UserProfile.vue`)
- 导入组件时使用 `@/` 别名

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'
import MyComponent from '@/components/MyComponent.vue'
</script>
```

### TypeScript

- 优先使用类型推断，必要时显式声明类型
- API 响应类型定义在 `src/types/` 目录

### 样式

- 使用 `scoped` 样式
- 颜色/间距使用 CSS 变量 (`var(--color-*)`)

## 认证流程

1. 登录获取 `access_token` 和 `refresh_token`
2. 请求携带 `Authorization: Bearer <token>`
3. Token 过期 (30分钟) 后使用 refresh_token 刷新
4. 刷新失败则跳转登录页

## IDE 配置

- **推荐 IDE**: VS Code
- **必需插件**: Vue - Official (Volar)
- **禁用插件**: Vetur (与 Volar 冲突)

## 开发流程

严格遵守以下流程，**不可跳步，不可省略任何环节**：

### 第一步：需求分析

- 收到用户需求后，**禁止直接写代码**
- 仔细分析需求的背景、目标和约束条件
- 如有不清楚的部分 → 再次向用户确认
- **此步骤会循环多次，直到用户完全认可为止**
- 每次修改后都必须重新提交完整的计划文档，不要只发修改片段

### 第二步：用户确认后开始开发

- **只有当用户明确说"同意按照计划文档开发"或同等含义的确认话语后，才能开始写代码**
- 没有用户确认 = 不写一行代码
- 开发过程中严格按照计划执行，不擅自添加计划之外的功能
- 如开发中发现计划有问题，**停下来向用户说明情况**，等待用户指示

### 第三步：开发完成后的核对

- 开发完成后，**主动核对**实现是否满足原始需求
- 逐项检查计划中的每个步骤是否都已落实
- 如有遗漏或偏差，主动修复，不要等用户指出

## 注意事项

- Node.js 版本要求: `^20.19.0 || >=22.12.0`
- 文件上传最大 100MB
- 支持 `.pdf`, `.docx`, `.txt`, `.md`, `.xlsx` 等格式
