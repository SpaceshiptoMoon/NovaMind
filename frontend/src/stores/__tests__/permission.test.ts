import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { getMyPermissions } = vi.hoisted(() => ({
  getMyPermissions: vi.fn(),
}))

vi.mock('@/api/user', () => ({
  userApi: { getMyPermissions },
}))

import { usePermissionStore } from '@/stores/permission'

describe('permission store — hasApp（应用级权限 deny-list）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    getMyPermissions.mockReset()
  })

  it('默认全开放：禁用列表为空时所有应用可用', async () => {
    getMyPermissions.mockResolvedValue({
      permissions: [],
      role_code: 'viewer',
      disabled_apps: [],
    })
    const store = usePermissionStore()
    await store.fetchPermissions()
    expect(store.hasApp('qa')).toBe(true)
    expect(store.hasApp('agent')).toBe(true)
    expect(store.hasApp('clawmate')).toBe(true)
  })

  it('被禁应用不可用，其他应用不受影响（应用相互隔离）', async () => {
    getMyPermissions.mockResolvedValue({
      permissions: [],
      role_code: 'viewer',
      disabled_apps: ['agent', 'skill'],
    })
    const store = usePermissionStore()
    await store.fetchPermissions()
    expect(store.hasApp('agent')).toBe(false)
    expect(store.hasApp('skill')).toBe(false)
    expect(store.hasApp('qa')).toBe(true)
    expect(store.hasApp('app')).toBe(true)
  })

  it('admin 短路：即使响应带禁用列表也全部可用', async () => {
    getMyPermissions.mockResolvedValue({
      permissions: [],
      role_code: 'admin',
      disabled_apps: ['agent'],
    })
    const store = usePermissionStore()
    await store.fetchPermissions()
    expect(store.isAdmin).toBe(true)
    expect(store.hasApp('agent')).toBe(true)
  })

  it('clear 重置禁用列表', async () => {
    getMyPermissions.mockResolvedValue({
      permissions: [],
      role_code: 'viewer',
      disabled_apps: ['qa'],
    })
    const store = usePermissionStore()
    await store.fetchPermissions()
    expect(store.hasApp('qa')).toBe(false)
    store.clear()
    expect(store.disabledApps).toEqual([])
    // clear 后无角色信息 → isAdmin=false，deny-list 空 → 可用
    expect(store.hasApp('qa')).toBe(true)
  })
})
