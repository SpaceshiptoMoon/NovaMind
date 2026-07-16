import { beforeEach, describe, expect, it, vi } from 'vitest'

const request = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}

vi.mock('../index', () => ({
  request,
}))

async function loadUserApi() {
  vi.resetModules()
  return import('../user')
}

describe('userApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('maps login, refresh, and logout to auth endpoints', async () => {
    const { userApi } = await loadUserApi()

    await userApi.login({ username: 'nova', password: 'secret' } as any)
    await userApi.refreshToken('refresh-token')
    await userApi.logout()

    expect(request.post).toHaveBeenNthCalledWith(1, '/user/users/login', {
      username: 'nova',
      password: 'secret',
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/user/users/refresh', {
      refresh_token: 'refresh-token',
    })
    expect(request.post).toHaveBeenNthCalledWith(3, '/user/users/logout')
  })

  it('maps user management endpoints with ids and payloads', async () => {
    const { userApi } = await loadUserApi()

    await userApi.getUsers({ skip: 10, limit: 20 })
    await userApi.getUser(7)
    await userApi.createUser({ username: 'nova' } as any)
    await userApi.updateUser(7, { email: 'nova@example.com' } as any)
    await userApi.deleteUser(7)
    await userApi.toggleUserStatus(7)
    await userApi.logoutAll(7)

    expect(request.get).toHaveBeenNthCalledWith(1, '/user/users', { skip: 10, limit: 20 })
    expect(request.get).toHaveBeenNthCalledWith(2, '/user/users/7')
    expect(request.post).toHaveBeenNthCalledWith(1, '/user/users', { username: 'nova' })
    expect(request.put).toHaveBeenNthCalledWith(1, '/user/users/7', { email: 'nova@example.com' })
    expect(request.delete).toHaveBeenNthCalledWith(1, '/user/users/7')
    expect(request.patch).toHaveBeenNthCalledWith(1, '/user/users/7/status')
    expect(request.post).toHaveBeenNthCalledWith(2, '/user/users/7/logout-all')
  })

  it('maps password recovery and change-password flows', async () => {
    const { userApi } = await loadUserApi()

    await userApi.changePassword('old-pass', 'new-pass')
    await userApi.forgotPassword('nova@example.com')
    await userApi.resetPassword('token-123', 'new-pass')
    await userApi.adminResetPassword(9)

    expect(request.post).toHaveBeenNthCalledWith(1, '/user/users/me/change-password', {
      old_password: 'old-pass',
      new_password: 'new-pass',
    })
    expect(request.post).toHaveBeenNthCalledWith(2, '/user/auth/forgot-password', {
      email: 'nova@example.com',
    })
    expect(request.post).toHaveBeenNthCalledWith(3, '/user/auth/reset-password', {
      token: 'token-123',
      new_password: 'new-pass',
    })
    expect(request.post).toHaveBeenNthCalledWith(4, '/user/users/9/reset-password')
  })
})
