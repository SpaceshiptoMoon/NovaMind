import { beforeEach, describe, expect, it, vi } from 'vitest'

const { getToken, clearToken } = vi.hoisted(() => ({
  getToken: vi.fn(),
  clearToken: vi.fn(),
}))

const { mockPermissionStore, configureMockPermissionStore } = vi.hoisted(() => {
  const state = {
    loaded: false,
    isAdmin: false,
    permissions: new Set<string>(),
  }

  let fetchPermissionsImpl = async () => {
    state.loaded = true
  }

  const store = {
    get loaded() {
      return state.loaded
    },
    get isAdmin() {
      return state.isAdmin
    },
    hasPermission(code: string | string[]) {
      const codes = Array.isArray(code) ? code : [code]
      if (state.isAdmin) return true
      return codes.some((c) => state.permissions.has(c))
    },
    fetchPermissions: vi.fn(async () => {
      await fetchPermissionsImpl()
    }),
    clear: vi.fn(() => {
      state.loaded = false
      state.isAdmin = false
      state.permissions.clear()
    }),
  }

  function configureMockPermissionStore(overrides?: {
    loaded?: boolean
    isAdmin?: boolean
    permissions?: Set<string>
    fetchPermissionsImpl?: () => Promise<void>
  }) {
    if (overrides?.loaded !== undefined) state.loaded = overrides.loaded
    if (overrides?.isAdmin !== undefined) state.isAdmin = overrides.isAdmin
    if (overrides?.permissions !== undefined) state.permissions = overrides.permissions
    if (overrides?.fetchPermissionsImpl !== undefined) {
      fetchPermissionsImpl = overrides.fetchPermissionsImpl
    }
  }

  return { mockPermissionStore: store, configureMockPermissionStore }
})

vi.mock('@/api', () => ({
  tokenManager: {
    getToken,
    clearToken,
  },
}))

vi.mock('@/stores/permission', () => ({
  usePermissionStore: () => mockPermissionStore,
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

  it('redirects unauthenticated users to login with redirect query', async () => {
    getToken.mockReturnValue(null)
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/spaces', fullPath: '/home/spaces', meta: { title: 'Spaces' } },
      {},
    )

    expect(document.title).toBe('Spaces - NovaMind')
    expect(result).toEqual({ path: '/login', query: { redirect: '/home/spaces' } })
  })

  it('redirects logged-in users away from login page', async () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/login', fullPath: '/login', meta: { requiresAuth: false, title: 'Login' } },
      {},
    )

    expect(result).toEqual({ path: '/home' })
  })

  it('blocks non-admin users from admin routes', async () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/admin/users', fullPath: '/home/admin/users', meta: { requiresAdmin: true } },
      {},
    )

    expect(result).toEqual({ path: '/403' })
  })

  it('allows admin users into admin routes', async () => {
    getToken.mockReturnValue('token')
    configureMockPermissionStore({ loaded: false, isAdmin: true, permissions: new Set() })
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/admin/users', fullPath: '/home/admin/users', meta: { requiresAdmin: true } },
      {},
    )

    expect(result).toBe(true)
  })

  it('clears auth and redirects to login when permission fetch fails', async () => {
    getToken.mockReturnValue('token')
    configureMockPermissionStore({
      loaded: false,
      isAdmin: false,
      permissions: new Set(),
      fetchPermissionsImpl: async () => {
        throw new Error('network error')
      },
    })
    localStorage.setItem('user', JSON.stringify({ is_admin: true }))
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/spaces', fullPath: '/home/spaces', meta: { requiresAdmin: true } },
      {},
    )

    expect(clearToken).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('user')).toBeNull()
    expect(result).toEqual({ path: '/login', query: { redirect: '/home/spaces' } })
  })

  it('blocks users without required permission', async () => {
    getToken.mockReturnValue('token')
    configureMockPermissionStore({ loaded: true, isAdmin: false, permissions: new Set() })
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/admin/roles', fullPath: '/home/admin/roles', meta: { requiresPermission: 'role.manage' } },
      {},
    )

    expect(result).toEqual({ path: '/403' })
  })

  it('allows users with required permission', async () => {
    getToken.mockReturnValue('token')
    configureMockPermissionStore({ loaded: true, isAdmin: false, permissions: new Set(['role.manage']) })
    const router = createMockRouter()
    setupRouterGuards(router as any)

    const result = await router.getBeforeGuard()(
      { path: '/home/admin/roles', fullPath: '/home/admin/roles', meta: { requiresPermission: 'role.manage' } },
      {},
    )

    expect(result).toBe(true)
  })

  it('scrolls to top after each navigation', () => {
    getToken.mockReturnValue('token')
    const router = createMockRouter()
    setupRouterGuards(router as any)

    router.getAfterGuard()()

    expect(window.scrollTo).toHaveBeenCalledWith(0, 0)
  })
})
