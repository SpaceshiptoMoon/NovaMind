import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { spaceApi } from '@/api/space'
import type { Space, SpaceConfig } from '@/api/types'

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
      spaces.value = data.items || []
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
      publicSpaces.value = data.items || []
      return publicSpaces.value
    } catch {
      publicSpaces.value = []
    }
  }

  async function fetchSpace(spaceId: number) {
    loading.value = true
    error.value = null
    try {
      currentSpace.value = await spaceApi.getSpace(spaceId)
      return currentSpace.value
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取空间详情失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createSpace(data: { name: string; visibility?: number; config?: SpaceConfig }) {
    const newSpace = await spaceApi.createSpace(data)
    spaces.value.unshift(newSpace)
    total.value++
    return newSpace
  }

  async function updateSpace(spaceId: number, data: { name?: string; visibility?: number; config?: SpaceConfig }) {
    const updatedSpace = await spaceApi.updateSpace(spaceId, data)
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
    currentSpace.value = space
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
      searchResults.value = data.items || []
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
