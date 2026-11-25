<template>
  <div class="space-list-view">

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 面包屑（含空间首页的「空间设置」动作）已全部上移全局顶栏
           （breadcrumbStore → AppHeader），本壳只留子路由出口 -->

      <!-- 子路由内容：key 含 kbId——同空间两个 KB 直跳（侧栏登记册）时强制重挂载，
           否则组件实例被复用、onMounted 拉取不重跑，右侧内容停在旧库 -->
      <div v-if="selectedSpaceId" class="content-body">
        <router-view
          :key="`${route.params.id || ''}-${route.params.kbId || (route.query.kbId as string) || ''}-${kbRefreshKey}`"
        />
      </div>

      <!-- 未选择空间时的欢迎页（始终显示，不依赖 loading 避免白屏） -->
      <div v-if="!selectedSpaceId" class="welcome-state">
        <EmptyState
          variant="default"
          headline="开始使用知识空间"
          description="从左侧栏选择或新建一个知识空间，开始管理知识库"
        />
      </div>
    </main>

  </div>
</template>

<script setup lang="ts">
/**
 * 知识空间子路由壳（纯壳）：KB 子路由出口 + 面包屑发布。
 *
 * 对应路由 /home/spaces（SpaceList）。空间选择/创建/管理已上提全局侧栏
 * （WorkbenchSidebar），面包屑与页头动作（空间设置）经 breadcrumbStore
 * 发布到全局顶栏渲染——本壳只承载 router-view 与欢迎空态。
 */

import { ref, computed, watchEffect, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { markRaw } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Setting } from '@element-plus/icons-vue'

import { useSpaceStore } from '@/stores/space'
import { useBreadcrumbStore } from '@/stores/breadcrumb'
import { knowledgeBaseApi } from '@/api/knowledge'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()
const breadcrumbStore = useBreadcrumbStore()

const selectedSpaceId = ref<number | null>(null)
const kbRefreshKey = ref(0)

// === 空间选择（侧栏列表） ===

// === 知识库上下文 ===

// 是否处于空间首页（KB 列表）——决定显示完整空间栏还是极简返回栏
const isSpaceHome = computed(() => !selectedSpaceId.value || route.name === 'KnowledgeBases')

// 子页面极简返回栏的返回目标（按路由名精确判定，不依赖 activeTab 字符串匹配）。
// 规则统一：空间级页面返回 KB 列表；KB 级页面返回 KB 列表；文档详情返回文档列表
const navBack = computed<{ label: string; to: string } | null>(() => {
  const sid = selectedSpaceId.value
  if (!sid) return null
  const kbIdParam =
    (route.params.kbId as string | undefined) ?? (route.query.kbId as string | undefined)
  const kbBase = `/home/spaces/${sid}/knowledge-bases`
  const docBase = kbIdParam ? `${kbBase}/${kbIdParam}/documents` : ''
  const name = route.name
  if (name === 'DocumentDetail') {
    // 从文档详情返回时，带上进入详情时的页码（详情页通过 query.fromPage 透传），
    // 让列表页恢复到进入时的页，而不是第 1 页。
    const fromPage = route.query.fromPage
    const pageSuffix = fromPage ? `?page=${fromPage}` : ''
    return kbIdParam
      ? { label: '返回文档管理', to: `${docBase}${pageSuffix}` }
      : { label: '返回知识库', to: kbBase }
  }
  // 其余全部子页面（文档管理/任务列表/知识检索/评估/配置向导/空间设置）统一返回 KB 列表
  return { label: '返回知识库', to: kbBase }
})

// 面包屑发布到全局顶栏（store 桥接）：所有空间页面统一上移——
// 空间首页链路短（仅空间名段）+ 附「空间设置」动作；子页面带返回目标。
// isSpaceHome / 链路 / 返回目标任一变化即整体覆盖
watchEffect(() => {
  if (!selectedSpaceId.value) {
    breadcrumbStore.clear()
    return
  }
  const isHome = isSpaceHome.value
  breadcrumbStore.set(
    crumbItems.value,
    isHome ? null : navBack.value,
    isHome
      ? {
          label: '空间设置',
          to: `/home/spaces/${selectedSpaceId.value}/settings`,
          icon: markRaw(Setting),
        }
      : null,
  )
})

// 离开空间壳时清空顶栏面包屑，避免其他页面残留上一页的链路
onBeforeUnmount(() => breadcrumbStore.clear())

// 分段面包屑链（顶栏切换器已承载空间名，链路自 KB 级起）：
// KB 子页面「KB 实体名 → 功能名」，空间级子页「功能名」；空间首页为空
// （仅余「空间设置」动作）——链路长度随层级走，头部不虚占
const crumbItems = computed(() => {
  const items: Array<{ label: string; to?: string }> = []
  const sid = selectedSpaceId.value
  if (!sid) return items

  const kbIdParam =
    (route.params.kbId as string | undefined) ?? (route.query.kbId as string | undefined)
  const kbBase = `/home/spaces/${sid}/knowledge-bases`

  // KB 级页面：KB 实体段（真实名；映射未命中时异步拉取后自动更新）
  if (kbIdParam) {
    const kbIdNum = Number(kbIdParam)
    items.push({
      label: kbNameMap.value[kbIdNum] || currentKbName.value || '知识库',
      to: kbBase,
    })
  }

  if (route.name === 'Documents') items.push({ label: '文档管理' })
  if (route.name === 'DocumentDetail') {
    // 末段带 to 即可点（BreadcrumbNav 约定）；从详情返回文档列表时恢复进入时的页码
    const fromPage = route.query.fromPage
    items.push({
      label: '文档管理',
      to: `${kbBase}/${kbIdParam}/documents${fromPage ? `?page=${fromPage}` : ''}`,
    })
  }
  if (route.name === 'Search') items.push({ label: '知识检索' })
  if (route.name === 'SpaceSettings') items.push({ label: '空间设置' })
  if (route.name === 'KbEvaluation') items.push({ label: '评估' })
  if (route.name === 'DocumentTasks') items.push({ label: '任务列表' })
  if (route.name === 'KbConfig') items.push({ label: '配置向导' })
  if (route.name === 'KbWiki') items.push({ label: 'Wiki' })

  // 知识运营区四子页：共用「知识运营」段（可点回区首）+ 当前页名段
  const opsPageNames: Record<string, string> = {
    SpaceOpsOverview: '工作台',
    SpaceOpsGaps: '缺口与失败',
    SpaceOpsQueue: '待办队列',
    SpaceOpsHealth: '资产健康',
  }
  const opsPage = opsPageNames[String(route.name)]
  if (opsPage) {
    items.push({ label: '知识运营', to: `/home/spaces/${sid}/ops` })
    items.push({ label: opsPage })
  }

  return items
})

// KB 名映射（直跳子页面时异步拉取；DocumentView/KbConfigView 自行取名不受影响）
const kbNameMap = ref<Record<number, string>>({})
const currentKbName = ref('')

async function ensureKbName(kbId: number) {
  if (kbNameMap.value[kbId]) return
  try {
    const kb = await knowledgeBaseApi.getKnowledgeBase(selectedSpaceId.value!, kbId)
    kbNameMap.value = { ...kbNameMap.value, [kbId]: kb.name }
  } catch {
    // 拉取失败保留兜底文案
  }
}

watch(
  () => route.params.kbId,
  (kbId) => {
    if (kbId && selectedSpaceId.value) {
      ensureKbName(Number(kbId))
    }
  },
  { immediate: true },
)

// === 路由同步 ===

/** 跟随 :id 参数同步选中空间；空间不存在时区分「无 KB 直跳 KB 列表」与「回空间列表」。 */
watch(
  () => route.params.id,
  async (id) => {
    if (!id) {
      selectedSpaceId.value = null
      spaceStore.clearCurrentSpace()
      return
    }

    const nextSpaceId = Number(id)
    selectedSpaceId.value = nextSpaceId

    try {
      await spaceStore.fetchSpace(nextSpaceId)
    } catch {
      const exists = spaceStore.spaces.some((space) => space.id === nextSpaceId)
      selectedSpaceId.value = null
      spaceStore.clearCurrentSpace()

      if (route.params.id === id) {
        await router.replace(
          exists ? `/home/spaces/${nextSpaceId}/knowledge-bases` : '/home/spaces',
        )
      }
    }
  },
  { immediate: true },
)

// 路由切换时主动释放焦点，避免页面上残留闪烁光标
watch(
  () => route.fullPath,
  () => {
    nextTick(() => {
      if (document.activeElement && document.activeElement !== document.body) {
        ;(document.activeElement as HTMLElement).blur()
      }
    })
  },
)

// === 初始化 ===
// 空间列表拉取与「未带 :id 跳第一个空间」均已上提：前者归 WorkbenchSidebar，
// 后者归 /home 路由守卫（直达最近空间）。

onMounted(() => {
  // 避免浏览器自动聚焦第一个输入框导致页面上出现闪烁光标
  nextTick(() => {
    if (document.activeElement && document.activeElement !== document.body) {
      ;(document.activeElement as HTMLElement).blur()
    }
  })
})
</script>

<style scoped>
.space-list-view {
  display: flex;
  height: 100%;
}

/* ===== Main Content ===== */

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  background: var(--color-bg);
}

.content-body {
  flex: 1;
  padding: var(--space-6) var(--space-8);
  overflow-y: auto;
}

/* 窄视口：内容区留白收紧，给双侧栏让位 */
@media (max-width: 1100px) {
  .content-body {
    padding: var(--space-4) var(--space-3);
  }
}

.welcome-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ===== Dialog shared ===== */

</style>
