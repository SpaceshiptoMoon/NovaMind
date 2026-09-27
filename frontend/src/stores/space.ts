/**
 * 空间（workspace/space）store
 *
 * 管理空间列表/公开空间/空间详情的 CRUD、当前空间选择、空间搜索关键词与结果。
 * 消费方：SpaceListView、SpaceSettingsView、SpaceJoinView、BreadcrumbNav、WorkspaceLayout。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { spaceApi } from '@/api/space'
import type { Space, SpaceConfig } from '@/api/types'

/**
 * 服务端响应补丁：剔除空间配置中遗留的 space_type 字段。
 * space_type 已下放为 KB 级配置，旧数据可能仍带该字段，展示前统一清除。
 */
function patchSpace(space: Space): Space {
  // space_type is now a KB-level config, not a space-level config.
  // Remove any stale space_type from space config if present.
  if (space.config && 'space_type' in space.config) {
    delete (space.config as Record<string, unknown>).space_type
  }
  return space
}

export const useSpaceStore = defineStore('space', () => {
  const spaces = ref<Space[]>([])
  const publicSpaces = ref<Space[]>([])
  const currentSpace = ref<Space | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const searchKeyword = ref('')
  const total = ref(0)
  const searchResults = ref<Space[]>([])
  const isSearching = ref(false)

  const spaceCount = computed(() => spaces.value.length)
  /** 空间列表视图：有关键词时展示搜索结果，否则展示全量列表 */
  const filteredSpaces = computed(() => {
    if (!searchKeyword.value) return spaces.value
    return searchResults.value
  })

  /** 拉取我的空间列表（分页） */
  async function fetchSpaces(params?: { skip?: number; limit?: number }) {
    loading.value = true
    error.value = null
    try {
      const data = await spaceApi.getSpaces(params)
      spaces.value = (data.items || []).map(patchSpace)
      total.value = data.total
      return spaces.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取空间列表失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchPublicSpaces(params?: { skip?: number; limit?: number }) {
    try {
      const data = await spaceApi.getPublicSpaces(params)
      publicSpaces.value = (data.items || []).map(patchSpace)
      return publicSpaces.value
    } catch {
      publicSpaces.value = []
    }
  }

  async function fetchSpace(spaceId: number) {
    loading.value = true
    error.value = null
    try {
      const space = await spaceApi.getSpace(spaceId)
      currentSpace.value = patchSpace(space)
      return currentSpace.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取空间详情失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createSpace(data: { name: string; visibility?: number; config?: SpaceConfig }) {
    const newSpace = patchSpace(await spaceApi.createSpace(data))
    spaces.value.unshift(newSpace)
    total.value++
    return newSpace
  }

  async function updateSpace(
    spaceId: number,
    data: { name?: string; visibility?: number; config?: SpaceConfig },
  ) {
    const updatedSpace = patchSpace(await spaceApi.updateSpace(spaceId, data))
    const index = spaces.value.findIndex((s) => s.id === spaceId)
    if (index !== -1) {
      spaces.value[index] = updatedSpace
    }
    if (currentSpace.value?.id === spaceId) {
      currentSpace.value = updatedSpace
    }
    return updatedSpace
  }

  /** 删除空间；若删的是当前空间，清空选中态 */
  async function deleteSpace(spaceId: number) {
    await spaceApi.deleteSpace(spaceId)
    spaces.value = spaces.value.filter((s) => s.id !== spaceId)
    total.value--
    if (currentSpace.value?.id === spaceId) {
      currentSpace.value = null
    }
  }

  function setCurrentSpace(space: Space | null) {
    currentSpace.value = space ? patchSpace(space) : null
  }

  function clearCurrentSpace() {
    currentSpace.value = null
  }

  function setSearchKeyword(keyword: string) {
    searchKeyword.value = keyword
  }

  /** 关键词搜索空间并写入搜索结果（空关键词清空结果，回到列表视图） */
  async function searchSpaces(keyword: string) {
    searchKeyword.value = keyword
    if (!keyword) {
      searchResults.value = []
      return
    }
    isSearching.value = true
    try {
      const data = await spaceApi.searchSpaces({ keyword })
      searchResults.value = (data.items || []).map(patchSpace)
    } catch {
      searchResults.value = []
    } finally {
      isSearching.value = false
    }
  }

  return {
    spaces,
    publicSpaces,
    currentSpace,
    loading,
    error,
    searchKeyword,
    searchResults,
    total,
    spaceCount,
    filteredSpaces,
    isSearching,
    fetchSpaces,
    fetchPublicSpaces,
    fetchSpace,
    createSpace,
    updateSpace,
    deleteSpace,
    setCurrentSpace,
    clearCurrentSpace,
    setSearchKeyword,
    searchSpaces,
  }
})
