import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const request = {
  post: vi.fn(),
  get: vi.fn(),
  put: vi.fn(),
}

const tokenManager = {
  getToken: vi.fn(),
  setToken: vi.fn(),
  getRefreshToken: vi.fn(),
  setRefreshToken: vi.fn(),
  clearToken: vi.fn(),
}

const push = vi.fn()

vi.mock('@/api', () => ({
  request,
  tokenManager,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

function createJwt(payload: Record<string, unknown>) {
  const encoded = btoa(JSON.stringify(payload)).replace(/\+/g, '-').replace(/\//g, '_')
  return `header.${encoded}.signature`
}

async function loadStore() {
  vi.resetModules()
  return import('../user')
}

describe('useUserStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('sets tokens, fetches profile, and redirects when password change is required', async () => {
    const token = createJwt({
      user_id: 7,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    const profile = {
      id: 7,
      username: 'nova',
      email: 'nova@example.com',
      phone: null,
      is_admin: true,
      status: 1,
      last_login_at: null,
      created_at: '2026-07-16T00:00:00Z',
      updated_at: null,
    }

    request.post.mockResolvedValue({
      access_token: token,
      refresh_token: 'refresh-token',
      token_type: 'bearer',
      expires_in: 3600,
      must_change_password: true,
    })
    request.get.mockResolvedValue(profile)
    tokenManager.getToken.mockReturnValue(token)

    const { useUserStore } = await loadStore()
    const store = useUserStore()
    const result = await store.login('nova', 'secret')

    expect(request.post).toHaveBeenCalledWith('/user/users/login', {
      username: 'nova',
      password: 'secret',
    })
    expect(tokenManager.setToken).toHaveBeenCalledWith(token)
    expect(tokenManager.setRefreshToken).toHaveBeenCalledWith('refresh-token')
    expect(request.get).toHaveBeenCalledWith('/user/users/7')
    expect(store.user).toEqual(profile)
    expect(localStorage.getItem('user')).toBe(JSON.stringify(profile))
    expect(push).toHaveBeenCalledWith('/home/change-password?forced=1')
    expect(result.must_change_password).toBe(true)
    expect(store.loading).toBe(false)
  })

  it('clears auth when fetching profile fails', async () => {
    const token = createJwt({
      user_id: 9,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    const error = new Error('profile failed')

    tokenManager.getToken.mockReturnValue(token)
    request.get.mockRejectedValue(error)

    const { useUserStore } = await loadStore()
    const store = useUserStore()

    await expect(store.fetchProfile()).rejects.toThrow('profile failed')
    expect(tokenManager.clearToken).toHaveBeenCalledTimes(1)
    expect(store.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('updates profile state and local cache', async () => {
    const token = createJwt({
      user_id: 11,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    const updated = {
      id: 11,
      username: 'updated',
      email: 'updated@example.com',
      phone: '18800000000',
      is_admin: false,
      status: 1,
      last_login_at: null,
      created_at: '2026-07-16T00:00:00Z',
      updated_at: '2026-07-16T01:00:00Z',
    }

    tokenManager.getToken.mockReturnValue(token)
    request.put.mockResolvedValue(updated)

    const { useUserStore } = await loadStore()
    const store = useUserStore()
    const result = await store.updateProfile({ username: 'updated' })

    expect(request.put).toHaveBeenCalledWith('/user/users/11', { username: 'updated' })
    expect(result).toEqual(updated)
    expect(store.user).toEqual(updated)
    expect(localStorage.getItem('user')).toBe(JSON.stringify(updated))
  })

  it('clears expired token during init', async () => {
    const expiredToken = createJwt({
      user_id: 5,
      exp: Math.floor(Date.now() / 1000) - 60,
    })

    tokenManager.getToken.mockReturnValue(expiredToken)
    localStorage.setItem('user', JSON.stringify({ id: 5, username: 'stale' }))

    const { useUserStore } = await loadStore()
    const store = useUserStore()

    expect(tokenManager.clearToken).toHaveBeenCalledTimes(1)
    expect(store.user).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('restores cached user for valid token and removes malformed cache', async () => {
    const token = createJwt({
      user_id: 3,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })
    const cachedUser = {
      id: 3,
      username: 'cached',
      email: 'cached@example.com',
      phone: null,
      is_admin: false,
      status: 1,
      last_login_at: null,
      created_at: '2026-07-16T00:00:00Z',
      updated_at: null,
    }

    tokenManager.getToken.mockReturnValue(token)
    localStorage.setItem('user', JSON.stringify(cachedUser))

    let userModule = await loadStore()
    let store = userModule.useUserStore()

    expect(store.user).toEqual(cachedUser)
    expect(store.isLoggedIn).toBe(true)

    vi.clearAllMocks()
    setActivePinia(createPinia())
    tokenManager.getToken.mockReturnValue(token)
    localStorage.setItem('user', '{broken')

    userModule = await loadStore()
    store = userModule.useUserStore()

    expect(store.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })

  it('clears auth on logout even when backend logout fails', async () => {
    const token = createJwt({
      user_id: 1,
      exp: Math.floor(Date.now() / 1000) + 3600,
    })

    request.post.mockRejectedValue(new Error('logout failed'))
    tokenManager.getToken.mockReturnValue(token)
    localStorage.setItem(
      'user',
      JSON.stringify({
        id: 1,
        username: 'nova',
        email: 'nova@example.com',
        phone: null,
        is_admin: false,
        status: 1,
        last_login_at: null,
        created_at: '2026-07-16T00:00:00Z',
        updated_at: null,
      }),
    )

    const { useUserStore } = await loadStore()
    const store = useUserStore()

    await expect(store.logout()).resolves.toBeUndefined()
    expect(request.post).toHaveBeenCalledWith('/user/users/logout')
    expect(tokenManager.clearToken).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('user')).toBeNull()
    expect(store.user).toBeNull()
  })

  it('resets loading and does not persist auth when login fails', async () => {
    request.post.mockRejectedValue(new Error('login failed'))

    const { useUserStore } = await loadStore()
    const store = useUserStore()

    await expect(store.login('nova', 'wrong')).rejects.toThrow('login failed')
    expect(store.loading).toBe(false)
    expect(tokenManager.setToken).not.toHaveBeenCalled()
    expect(tokenManager.setRefreshToken).not.toHaveBeenCalled()
    expect(store.user).toBeNull()
    expect(localStorage.getItem('user')).toBeNull()
  })
})
