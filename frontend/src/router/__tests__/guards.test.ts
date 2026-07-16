import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getToken, clearToken } = vi.hoisted(() => ({
  getToken: vi.fn(),
  clearToken: vi.fn(),
}))

vi.mock('@/api', () => ({
  tokenManager: {
    getToken,
    clearToken,
  },
}))

import { setupRouterGuards } from '../guards'

type Guard = (to: any, from: any) => any

function createMockRouter() {
  let beforeGuard: Guard | undefined
  let afterGuard: (() => void) | undefined

  return {
    beforeEach(guard: Guard) {
      beforeGuard = guard
    },
    afterEach(guard: () => void) {
      afterGuard = guard
    },
    getBeforeGuard() {
      if (!beforeGuard) throw new Error('beforeEach guard not registered')
      return beforeGuard
    },
    getAfterGuard() {
      if (!afterGuard) throw new Error('afterEach guard not registered')
      return afterGuard
    },
  }
}

describe('setupRouterGuards', () => {
  beforeEach(() => {
    getToken.mockReset()
    clearToken.mockReset()
    localStorage.clear()
    document.title = ''
    vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  })

  it('redirects unauthenticated users to login with redirect query', () => {
    getToken.mockReturnValue(null)
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = router.getBeforeGuard()(
      { path: '/home/spaces', fullPath: '/home/spaces', meta: { title: 'Spaces' } },
      {},
    )

    expect(document.title).toBe('Spaces - NovaMind')
    expect(result).toEqual({ path: '/login', query: { redirect: '/home/spaces' } })
  })

  it('redirects logged-in users away from login page', () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = router.getBeforeGuard()(
      { path: '/login', fullPath: '/login', meta: { requiresAuth: false, title: 'Login' } },
      {},
    )

    expect(result).toEqual({ path: '/home' })
  })

  it('blocks non-admin users from admin routes', () => {
    getToken.mockReturnValue('token')
    localStorage.setItem('user', JSON.stringify({ is_admin: false }))
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = router.getBeforeGuard()(
      { path: '/home/admin/users', fullPath: '/home/admin/users', meta: { requiresAdmin: true } },
      {},
    )

    expect(result).toEqual({ path: '/403' })
  })

  it('clears auth and redirects to login when stored user payload is invalid', () => {
    getToken.mockReturnValue('token')
    localStorage.setItem('user', '{broken json')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = router.getBeforeGuard()(
      { path: '/home/admin/users', fullPath: '/home/admin/users', meta: { requiresAdmin: true } },
      {},
    )

    expect(clearToken).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('user')).toBeNull()
    expect(result).toEqual({ path: '/login', query: { redirect: '/home/admin/users' } })
  })

  it('redirects to login for admin routes when token exists but cached user is missing', () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = router.getBeforeGuard()(
      { path: '/home/admin/users', fullPath: '/home/admin/users', meta: { requiresAdmin: true } },
      {},
    )

    expect(result).toEqual({ path: '/login', query: { redirect: '/home/admin/users' } })
  })

  it('scrolls to top after each navigation', () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    router.getAfterGuard()()

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0)
  })
})
