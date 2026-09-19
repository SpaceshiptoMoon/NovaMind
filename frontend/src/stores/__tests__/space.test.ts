import { beforeEach, describe, expect, it, vi } from 'vitest'
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
