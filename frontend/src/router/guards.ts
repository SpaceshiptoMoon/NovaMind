import type { Router } from 'vue-router'
import { tokenManager } from '@/api'
import { usePermissionStore } from '@/stores/permission'

export function setupRouterGuards(router: Router) {
  router.beforeEach(async (to, _from) => {
    const title = to.meta.title
    document.title = title ? `${title} - NovaMind` : 'NovaMind'

    const token = tokenManager.getToken()
    const permStore = usePermissionStore()

    // 只要持有 token 就在路由进入前预加载权限，确保组件挂载前权限/角色状态就绪
    if (token && !permStore.loaded) {
      try {
        await permStore.fetchPermissions()
      } catch {
        tokenManager.clearToken()
        localStorage.removeItem('user')
        permStore.clear()
        return { path: '/login', query: { redirect: to.fullPath } }
      }
    }

    const requiresAuth = to.meta.requiresAuth !== false
    const requiresAdmin = to.meta.requiresAdmin === true

    if (!requiresAuth) {
      if (to.path === '/login' && token) {
        return { path: '/home' }
      }
      return true
    }

    if (!token) {
      return { path: '/login', query: { redirect: to.fullPath } }
    }

    if (requiresAdmin && !permStore.isAdmin) {
      return { path: '/403' }
    }

    const requiresPermission = to.meta.requiresPermission as string | string[] | undefined
    if (requiresPermission && !permStore.hasPermission(requiresPermission)) {
      return { path: '/403' }
    }

    return true
  })

  router.afterEach(() => {
    window.scrollTo(0, 0)
  })
}
