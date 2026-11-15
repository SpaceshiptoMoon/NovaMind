/**
 * 空间（workspace/space）store
 *
 * 管理空间列表/公开空间/空间详情的 CRUD、当前空间选择、空间搜索关键词与结果、
 * 当前空间 KB 登记册与最近空间持久化。
 * 消费方：WorkbenchSidebar、SpaceListView、SpaceSettingsView、SpaceJoinView、BreadcrumbNav。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { spaceApi } from '@/api/space'
import { knowledgeBaseApi } from '@/api/knowledge'
import type { KnowledgeBase, Space, SpaceConfig } from '@/api/types'

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

  // fetchSpace 同 id 去重（侧栏与 SpaceListView 壳双 watch 路由 :id）
  const spaceFetchingId = ref<number | null>(null)
  const spaceFetchInFlight = ref<Promise<Space | null> | null>(null)

  // 当前空间的活跃 KB 登记册（全局侧栏消费；归档库不入册）
  const currentSpaceKbs = ref<KnowledgeBase[]>([])
  const kbLoading = ref(false)

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
    // 同 id 去重：侧栏与 SpaceListView 壳都 watch 路由 :id，避免双请求
    if (currentSpace.value?.id === spaceId) return currentSpace.value
    if (spaceFetchingId.value === spaceId) return spaceFetchInFlight.value
    spaceFetchingId.value = spaceId
    loading.value = true
    error.value = null
    spaceFetchInFlight.value = (async () => {
      try {
        const space = await spaceApi.getSpace(spaceId)
        currentSpace.value = patchSpace(space)
        return currentSpace.value
      } catch (e) {
        error.value = e instanceof Error ? e.message : '获取空间详情失败'
        throw e
      } finally {
        loading.value = false
        spaceFetchingId.value = null
      }
    })()
    return spaceFetchInFlight.value
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

  /** 拉取当前空间的活跃知识库登记册（侧栏导航用；归档库不入册） */
  async function fetchCurrentSpaceKbs(spaceId: number, { force = false } = {}) {
    if (!force && currentSpaceKbs.value[0]?.space_id === spaceId) return currentSpaceKbs.value
    kbLoading.value = true
    try {
      const data = await knowledgeBaseApi.getKnowledgeBases(spaceId, { status: 1 })
      currentSpaceKbs.value = (data.items || []).filter(
        (kb): kb is KnowledgeBase => kb && typeof kb.id !== 'undefined',
      )
      return currentSpaceKbs.value
    } catch {
      currentSpaceKbs.value = []
      return currentSpaceKbs.value
    } finally {
      kbLoading.value = false
    }
  }

  /** 删除/归档 KB 后清空登记册缓存，下一次 fetchCurrentSpaceKbs 重拉 */
  function invalidateCurrentSpaceKbs() {
    currentSpaceKbs.value = []
  }

  // ===== 最近空间持久化（首页直达 + 切换器「最近使用」数据源） =====

  const LAST_SPACE_PREFIX = 'novamind:last-space:'
  const RECENT_SPACES_KEY = 'novamind:recent-spaces'

  function readRecentSpaces(): Record<number, number> {
    try {
      const raw = localStorage.getItem(RECENT_SPACES_KEY)
      const parsed = raw ? (JSON.parse(raw) as Record<string, number>) : {}
      const out: Record<number, number> = {}
      for (const [k, v] of Object.entries(parsed)) {
        const id = Number(k)
        if (Number.isFinite(id) && typeof v === 'number') out[id] = v
      }
      return out
    } catch {
      return {}
    }
  }

  /** 记录空间访问：写最近时间戳与「最近空间」指针（按用户隔离） */
  function touchSpaceAccess(spaceId: number, userId: number | null) {
    if (userId != null) {
      try {
        localStorage.setItem(`${LAST_SPACE_PREFIX}${userId}`, String(spaceId))
      } catch {
        /* 隐私模式等存储失败静默 */
      }
    }
    const recent = readRecentSpaces()
    recent[spaceId] = Date.now()
    try {
      localStorage.setItem(RECENT_SPACES_KEY, JSON.stringify(recent))
    } catch {
      /* 同上 */
    }
  }

  /** 读某用户的最近空间（无记录或存储不可用返回 null） */
  function getLastSpaceId(userId: number): number | null {
    const raw = localStorage.getItem(`${LAST_SPACE_PREFIX}${userId}`)
    const id = raw == null ? NaN : Number(raw)
    return Number.isFinite(id) && id > 0 ? id : null
  }

  /** 最近访问的 n 个空间（切换器「最近使用」组；含当前空间） */
  function recentSpaceIds(n: number): number[] {
    const entries = Object.entries(readRecentSpaces()).sort((a, b) => b[1] - a[1])
    return entries.slice(0, n).map(([id]) => Number(id))
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
    currentSpaceKbs,
    kbLoading,
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
    fetchCurrentSpaceKbs,
    invalidateCurrentSpaceKbs,
    touchSpaceAccess,
    getLastSpaceId,
    recentSpaceIds,
    createSpace,
    updateSpace,
    deleteSpace,
    setCurrentSpace,
    clearCurrentSpace,
    setSearchKeyword,
    searchSpaces,
  }
})
