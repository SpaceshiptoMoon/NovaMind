/**
 * 路由注册表
 *
 * 三层布局：公开封面页 / AuthLayout（登录注册）/ WorkspaceLayout（/home 全站）。
 * 路由懒加载，meta.requiresAuth + meta.title 驱动守卫行为。
 */
import { createRouter, createWebHistory } from 'vue-router'
import { setupRouterGuards } from './guards'

// 布局组件
import AuthLayout from '@/layouts/AuthLayout.vue'
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
      path: '/register',
      component: AuthLayout,
      meta: { requiresAuth: false, title: '注册' },
      children: [
        {
          path: '',
          name: 'Register',
          component: () => import('@/views/auth/RegisterView.vue'),
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

    // 主应用路由（WorkspaceLayout = 全站唯一布局：侧栏导航 + 顶栏，需要登录）
    {
      path: '/home',
      component: WorkspaceLayout,
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'Home',
          component: () => import('@/views/HomeView.vue'),
          meta: { title: '首页' },
        },
        {
          // 跨空间全局检索（消费侧入口）：门户 Hero 搜索框与顶栏搜索位的落地页
          path: 'search',
          name: 'GlobalSearch',
          component: () => import('@/views/search/GlobalSearchView.vue'),
          meta: { title: '知识检索' },
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
          path: 'settings/api-keys',
          name: 'ApiKeyManage',
          component: () => import('@/views/user/ApiKeyView.vue'),
          meta: { title: 'API 密钥' },
        },
        {
          path: 'admin/users',
          name: 'UserManage',
          component: () => import('@/views/user/UserManageView.vue'),
          meta: { title: '用户管理', requiresPermission: 'user.manage' },
        },
        {
          path: 'admin/roles',
          name: 'RoleManage',
          component: () => import('@/views/user/RoleManageView.vue'),
          meta: { title: '角色管理', requiresPermission: 'role.manage' },
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
              path: ':id/knowledge-bases/:kbId/config',
              name: 'KbConfig',
              component: () => import('@/views/space/KbConfigView.vue'),
              meta: { title: '知识库配置' },
            },
            {
              path: ':id/knowledge-bases/:kbId/documents',
              name: 'Documents',
              component: () => import('@/views/space/DocumentView.vue'),
              meta: { title: '文档管理' },
            },
            {
              path: ':id/knowledge-bases/:kbId/tasks',
              name: 'DocumentTasks',
              component: () => import('@/views/space/DocumentTaskBatchView.vue'),
              meta: { title: '任务列表' },
            },
            {
              path: ':id/knowledge-bases/:kbId/wiki',
              name: 'KbWiki',
              component: () => import('@/views/space/WikiBrowserView.vue'),
              meta: { title: '知识库 Wiki' },
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
            {
              // 知识运营区：四页一区（工作台/缺口与失败/待办队列/资产健康），
              // 子导航在壳组件内——旧三页（insights/gap-report/kb-ops）按批次史
              // 切分的信息架构已废弃，旧路径 redirect 保通知链接与书签兼容
              path: ':id/ops',
              name: 'SpaceOps',
              component: () => import('@/views/space/SpaceOpsView.vue'),
              meta: { title: '知识运营' },
              children: [
                { path: '', redirect: { name: 'SpaceOpsOverview' } },
                {
                  path: 'overview',
                  name: 'SpaceOpsOverview',
                  component: () => import('@/views/space/SpaceOpsOverviewView.vue'),
                  meta: { title: '运营工作台' },
                },
                {
                  path: 'gaps',
                  name: 'SpaceOpsGaps',
                  component: () => import('@/views/space/SpaceOpsGapsView.vue'),
                  meta: { title: '缺口与失败' },
                },
                {
                  path: 'queue',
                  name: 'SpaceOpsQueue',
                  component: () => import('@/views/space/SpaceOpsQueueView.vue'),
                  meta: { title: '待办队列' },
                },
                {
                  path: 'health',
                  name: 'SpaceOpsHealth',
                  component: () => import('@/views/space/SpaceOpsHealthView.vue'),
                  meta: { title: '资产健康' },
                },
              ],
            },
            {
              path: ':id/insights',
              redirect: (to) => `/home/spaces/${String(to.params.id)}/ops/overview`,
            },
            {
              path: ':id/gap-report',
              redirect: (to) => `/home/spaces/${String(to.params.id)}/ops/gaps`,
            },
            {
              path: ':id/kb-ops',
              redirect: (to) => `/home/spaces/${String(to.params.id)}/ops/overview`,
            },
          ],
        },
        {
          path: 'spaces/:id/join',
          name: 'SpaceJoin',
          component: () => import('@/views/space/SpaceJoinView.vue'),
          meta: { title: '加入空间', requiresAuth: true },
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
