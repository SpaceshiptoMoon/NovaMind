import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const spaceApi = {
  getSpaces: vi.fn(),
  getPublicSpaces: vi.fn(),
  searchSpaces: vi.fn(),
  createSpace: vi.fn(),
  getSpace: vi.fn(),
  updateSpace: vi.fn(),
  deleteSpace: vi.fn(),
}

const normalizeSpaceTypes = vi.fn((config: any) => {
  const value = config?.space_type
  return Array.isArray(value) ? value : value ? [value] : []
})

vi.mock('@/api/space', () => ({ spaceApi }))
vi.mock('@/components/knowledge', () => ({ normalizeSpaceTypes }))

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
    expect(normalizeSpaceTypes).toHaveBeenCalledTimes(2)
    expect(spaces).toHaveLength(2)
    expect(store.total).toBe(2)
    expect(store.spaces[0]?.config?.space_type).toEqual(['team'])
  })

  it('updates both list and currentSpace after updateSpace', async () => {
    spaceApi.updateSpace.mockResolvedValue({
      id: 1,
      name: 'Alpha Updated',
      config: { space_type: 'public' },
    })

    const store = useSpaceStore()
    store.spaces = [{ id: 1, name: 'Alpha', config: { space_type: 'team' } }] as any
    store.currentSpace = { id: 1, name: 'Alpha', config: { space_type: 'team' } } as any

    const result = await store.updateSpace(1, { name: 'Alpha Updated' })

    expect(spaceApi.updateSpace).toHaveBeenCalledWith(1, { name: 'Alpha Updated' })
    expect(result.name).toBe('Alpha Updated')
    expect(store.spaces[0]?.name).toBe('Alpha Updated')
    expect(store.currentSpace?.name).toBe('Alpha Updated')
    expect(store.currentSpace?.config?.space_type).toEqual(['public'])
  })

  it('clears search results immediately when keyword is empty', async () => {
    const store = useSpaceStore()
    store.searchResults = [{ id: 1, name: 'Old' }] as any

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
