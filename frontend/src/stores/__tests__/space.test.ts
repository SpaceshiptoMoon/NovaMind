import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Space } from '@/api/types'
import { createPinia, setActivePinia } from 'pinia'

// vi.mock 工厂会被提升到文件顶部，工厂引用的变量必须经 vi.hoisted 同步提升，
// 否则 mock 装配时机早于 const 声明 → "Cannot access 'spaceApi' before initialization"
const { spaceApi } = vi.hoisted(() => ({
  spaceApi: {
    getSpaces: vi.fn(),
    getPublicSpaces: vi.fn(),
    searchSpaces: vi.fn(),
    createSpace: vi.fn(),
    getSpace: vi.fn(),
    updateSpace: vi.fn(),
    deleteSpace: vi.fn(),
  },
}))

vi.mock('@/api/space', () => ({ spaceApi }))

import { useSpaceStore } from '../space'

const RECENT_KEY = 'novamind:recent-spaces'

describe('useSpaceStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('fetches spaces, normalizes config, and updates total', async () => {
    spaceApi.getSpaces.mockResolvedValue({
      items: [
        { id: 1, name: 'Alpha', config: { space_type: 'team' } },
        { id: 2, name: 'Beta', config: { space_type: ['private'] } },
      ],
      total: 2,
    })

    const store = useSpaceStore()
    const spaces = await store.fetchSpaces()

    expect(spaceApi.getSpaces).toHaveBeenCalledWith(undefined)
    expect(spaces).toHaveLength(2)
    expect(store.total).toBe(2)
    // space_type 已下放 KB 级配置：patchSpace 剔除空间配置中的遗留 space_type
    expect(store.spaces[0]?.config?.space_type).toBeUndefined()
    expect(store.spaces[1]?.config?.space_type).toBeUndefined()
  })

  it('updates both list and currentSpace after updateSpace', async () => {
    spaceApi.updateSpace.mockResolvedValue({
      id: 1,
      name: 'Alpha Updated',
      config: { space_type: 'public' },
    })

    const store = useSpaceStore()
    const fakeSpace = {
      id: 1,
      name: 'Alpha',
      config: { space_type: 'team' },
    } as unknown as Space
    store.spaces = [fakeSpace]
    store.currentSpace = fakeSpace

    const result = await store.updateSpace(1, { name: 'Alpha Updated' })

    expect(spaceApi.updateSpace).toHaveBeenCalledWith(1, { name: 'Alpha Updated' })
    expect(result.name).toBe('Alpha Updated')
    expect(store.spaces[0]?.name).toBe('Alpha Updated')
    expect(store.currentSpace?.name).toBe('Alpha Updated')
    expect(store.currentSpace?.config?.space_type).toBeUndefined()
  })

  it('clears search results immediately when keyword is empty', async () => {
    const store = useSpaceStore()
    store.searchResults = [{ id: 1, name: 'Old' } as unknown as Space]

    await store.searchSpaces('')

    expect(spaceApi.searchSpaces).not.toHaveBeenCalled()
    expect(store.searchResults).toEqual([])
    expect(store.searchKeyword).toBe('')
  })

  it('falls back to empty search results when search request fails', async () => {
    spaceApi.searchSpaces.mockRejectedValue(new Error('network'))

    const store = useSpaceStore()
    await store.searchSpaces('alpha')

    expect(spaceApi.searchSpaces).toHaveBeenCalledWith({ keyword: 'alpha' })
    expect(store.searchResults).toEqual([])
    expect(store.isSearching).toBe(false)
  })
})

// ===== 最近空间（切换器「最近使用」数据源；localStorage 响应式镜像） =====

describe('useSpaceStore recent spaces', () => {
  beforeEach(() => {
    // store 建立时读一次 localStorage 做镜像初始化，先清空再建 pinia
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('按最后访问时间倒序取前 n 个，再次访问刷新排序', () => {
    // Date.now() 同毫秒会让排序不确定，用假时钟固定先后
    vi.useFakeTimers()
    const store = useSpaceStore()

    vi.setSystemTime(1000)
    store.touchSpaceAccess(3, 1)
    vi.setSystemTime(2000)
    store.touchSpaceAccess(4, 1)
    vi.setSystemTime(3000)
    store.touchSpaceAccess(5, 1)
    expect(store.recentSpaceIds(2)).toEqual([5, 4])

    // 回访 3 → 升为最新（回归：镜像响应式更新，会话内列表不再停留在旧顺序）
    vi.setSystemTime(4000)
    store.touchSpaceAccess(3, 1)
    expect(store.recentSpaceIds(2)).toEqual([3, 5])
  })

  it('镜像与 localStorage 持久层同步写入', () => {
    const store = useSpaceStore()
    store.touchSpaceAccess(9, 1)

    expect(store.recentSpaceIds(5)).toEqual([9])
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? '{}')).toEqual({ 9: expect.any(Number) })
    expect(localStorage.getItem('novamind:last-space:1')).toBe('9')
  })

  it('deleteSpace 清理对应空间的最近访问记录（防幽灵条目）', async () => {
    spaceApi.deleteSpace.mockResolvedValue(undefined)
    const store = useSpaceStore()
    store.touchSpaceAccess(7, 1)
    store.touchSpaceAccess(8, 1)

    await store.deleteSpace(7)

    expect(store.recentSpaceIds(5)).toEqual([8])
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? '{}')).toEqual({
      8: expect.any(Number),
    })
  })
})
