import type { Router } from 'vue-router'
import { tokenManager } from '@/api'

export function setupRouterGuards(router: Router) {
  router.beforeEach((to, _from) => {
    const title = to.meta.title
    document.title = title ? `${title} - NovaMind` : 'NovaMind'

    const token = tokenManager.getToken()
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

    if (requiresAdmin) {
      const userStr = localStorage.getItem('user')
      if (userStr) {
        try {
          const user = JSON.parse(userStr)
          if (!user.is_admin) {
            return { path: '/403' }
          }
        } catch {
          tokenManager.clearToken()
          localStorage.removeItem('user')
          return { path: '/login', query: { redirect: to.fullPath } }
        }
      } else {
        return { path: '/login', query: { redirect: to.fullPath } }
      }
    }

    return true
  })

  router.afterEach(() => {
    window.scrollTo(0, 0)
  })
}
