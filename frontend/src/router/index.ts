import { createRouter, createWebHistory } from 'vue-router'
import { setupRouterGuards } from './guards'

// 布局组件
import AuthLayout from '@/layouts/AuthLayout.vue'
import MainLayout from '@/layouts/MainLayout.vue'
import WorkspaceLayout from '@/layouts/WorkspaceLayout.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    // 公开封面页（无需登录）
    {
      path: '/',
      name: 'Landing',
      component: () => import('@/views/LandingView.vue'),
      meta: { requiresAuth: false, title: 'NovaMind — 问而知，知而行' },
    },

    // 认证相关路由（使用 AuthLayout）
    {
      path: '/login',
      component: AuthLayout,
      meta: { requiresAuth: false, title: '登录' },
      children: [
        {
          path: '',
          name: 'Login',
          component: () => import('@/views/auth/LoginView.vue'),
        },
      ],
    },
    {
      path: '/forgot-password',
      component: AuthLayout,
      meta: { requiresAuth: false, title: '忘记密码' },
      children: [
        {
          path: '',
          name: 'ForgotPassword',
          component: () => import('@/views/auth/ForgotPasswordView.vue'),
        },
      ],
    },
    {
      path: '/reset-password',
      component: AuthLayout,
      meta: { requiresAuth: false, title: '重置密码' },
      children: [
        {
          path: '',
          name: 'ResetPassword',
          component: () => import('@/views/auth/ResetPasswordView.vue'),
        },
      ],
    },

    // 主应用路由（使用 MainLayout，需要登录）
    {
      path: '/home',
      component: MainLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'Home',
          component: () => import('@/views/HomeView.vue'),
          meta: { title: '首页' },
        },
        {
          path: 'profile',
          name: 'Profile',
          component: () => import('@/views/user/UserProfileView.vue'),
          meta: { title: '个人信息' },
        },
        {
          path: 'notifications',
          name: 'Notifications',
          component: () => import('@/views/user/NotificationView.vue'),
          meta: { title: '通知中心' },
        },
        {
          path: 'change-password',
          name: 'ChangePassword',
          component: () => import('@/views/user/ChangePasswordView.vue'),
          meta: { title: '修改密码' },
        },
        {
          path: 'settings/models',
          name: 'ModelConfig',
          component: () => import('@/views/user/ModelConfigView.vue'),
          meta: { title: '模型配置' },
        },
        {
          path: 'admin/users',
          name: 'UserManage',
          component: () => import('@/views/user/UserManageView.vue'),
          meta: { title: '用户管理', requiresAdmin: true },
        },
        {
          path: 'spaces',
          name: 'SpaceList',
          component: () => import('@/views/space/SpaceListView.vue'),
          meta: { title: '知识空间' },
          children: [
            {
              path: ':id/knowledge-bases',
              name: 'KnowledgeBases',
              component: () => import('@/views/space/KnowledgeBaseView.vue'),
              meta: { title: '知识库' },
            },
            {
              path: ':id/knowledge-bases/:kbId/documents',
              name: 'Documents',
              component: () => import('@/views/space/DocumentView.vue'),
              meta: { title: '文档管理' },
            },
            {
              path: ':id/knowledge-bases/:kbId/evaluation',
              name: 'KbEvaluation',
              component: () => import('@/views/space/KbEvaluationView.vue'),
              meta: { title: '知识库评测' },
            },
            {
              path: ':id/documents/:docId',
              name: 'DocumentDetail',
              component: () => import('@/views/space/DocumentDetailView.vue'),
              meta: { title: '文档详情' },
            },
            {
              path: ':id/search',
              name: 'Search',
              component: () => import('@/views/space/SearchView.vue'),
              meta: { title: '知识检索' },
            },
            {
              path: ':id/settings',
              name: 'SpaceSettings',
              component: () => import('@/views/space/SpaceSettingsView.vue'),
              meta: { title: '空间设置' },
            },
          ],
        },
        {
          path: 'chat',
          redirect: '/home/workspace/chat',
        },
        {
          path: 'agents',
          redirect: '/home/workspace/agents',
        },
        {
          path: 'agents/:agentId/chat',
          redirect: (to) => `/home/workspace/agents/${to.params.agentId}/chat`,
        },
        {
          path: 'research/:spaceId',
          redirect: (to) => `/home/workspace/research/${to.params.spaceId}`,
        },
        {
          path: 'research/:spaceId/history',
          redirect: (to) => `/home/workspace/research/${to.params.spaceId}/history`,
        },
        {
          path: 'apps',
          name: 'Apps',
          component: () => import('@/views/app/AppView.vue'),
          meta: { title: '应用中心' },
        },
        {
          path: 'apps/resume',
          name: 'ResumeMining',
          component: () => import('@/views/app/resume/ResumeApp.vue'),
          meta: { title: '简历挖掘' },
        },
        {
          path: 'apps/resume/history',
          name: 'ResumeHistory',
          component: () => import('@/views/app/resume/ResumeHistory.vue'),
          meta: { title: '简历挖掘历史' },
        },
        {
          path: 'apps/resume/session/:sessionId',
          name: 'ResumeMiningSession',
          component: () => import('@/views/app/resume/ResumeApp.vue'),
          meta: { title: '简历挖掘' },
        },
        // 统一工作台
        {
          path: 'workspace',
          component: WorkspaceLayout,
          redirect: '/home/workspace/chat',
          meta: { title: '工作台' },
          children: [
            {
              path: 'chat',
              name: 'WorkspaceChat',
              component: () => import('@/views/chat/ChatView.vue'),
              meta: { title: 'AI 对话' },
            },
            {
              path: 'agents',
              name: 'WorkspaceAgents',
              component: () => import('@/views/agent/AgentView.vue'),
              meta: { title: '智能体' },
            },
            {
              path: 'agents/:agentId/chat',
              name: 'WorkspaceAgentChat',
              component: () => import('@/views/agent/AgentChatView.vue'),
              meta: { title: '智能体对话' },
            },
            {
              path: 'research',
              name: 'WorkspaceResearch',
              component: () => import('@/views/research/ResearchView.vue'),
              meta: { title: '深度研究' },
            },
            {
              path: 'research/:spaceId',
              name: 'WorkspaceResearchSpace',
              component: () => import('@/views/research/ResearchView.vue'),
              meta: { title: '深度研究' },
            },
            {
              path: 'research/:spaceId/history',
              name: 'WorkspaceResearchHistory',
              component: () => import('@/views/research/ResearchHistoryView.vue'),
              meta: { title: '研究历史' },
            },
            {
              path: 'skills',
              name: 'WorkspaceSkills',
              component: () => import('@/views/skill/SkillMarketplaceView.vue'),
              meta: { title: '技能广场' },
            },
            {
              path: 'skills/admin',
              name: 'WorkspaceSkillAdmin',
              component: () => import('@/views/skill/SkillAdminView.vue'),
              meta: { title: '技能审核', requiresAdmin: true },
            },
            {
              path: 'skills/:skillId',
              name: 'WorkspaceSkillDetail',
              component: () => import('@/views/skill/SkillDetailView.vue'),
              meta: { title: '技能详情' },
            },
          ],
        },
      ],
    },

    // 403 无权限
    {
      path: '/403',
      name: 'Forbidden',
      component: () => import('@/views/ForbiddenView.vue'),
      meta: { requiresAuth: false, title: '无权限' },
    },

    // 404 页面
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('@/views/NotFoundView.vue'),
      meta: { requiresAuth: false, title: '页面未找到' },
    },
  ],
})

// 设置路由守卫
setupRouterGuards(router)

export default router
