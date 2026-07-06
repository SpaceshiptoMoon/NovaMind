import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { spaceApi } from '@/api/space'
import { normalizeSpaceTypes } from '@/utils/document'
import type { Space, SpaceConfig } from '@/api/types'

/** 归一化 Space 数据中的 space_type（兼容旧数据中的字符串格式） */
function patchSpace(space: Space): Space {
  if (space.config) {
    space.config.space_type = normalizeSpaceTypes(space.config)
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
  const filteredSpaces = computed(() => {
    if (!searchKeyword.value) return spaces.value
    return searchResults.value
  })

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

  async function updateSpace(spaceId: number, data: { name?: string; visibility?: number; config?: SpaceConfig }) {
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
