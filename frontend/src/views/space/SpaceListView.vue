<template>
  <div class="space-list-view">

    <!-- 主内容区 -->
    <main class="main-content">
      <!-- 空间首页：面包屑 + 空间设置。新建知识库与知识运营的大入口由子页面
           （KnowledgeBaseView）页头区承载——父层只留导航与设置 -->
      <div v-if="isSpaceHome" class="content-header content-header--full">
        <div class="header-left">
          <BreadcrumbNav v-if="selectedSpaceId" :items="crumbItems" />
        </div>
        <div class="header-actions">
          <el-button
            v-if="selectedSpaceId"
            size="small"
            circle
            aria-label="空间设置"
            title="空间设置"
            @click="switchTab('settings')"
          >
            <el-icon><Setting /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- 子页面：极简返回栏（返回键 + 分段面包屑） -->
      <div v-else class="content-header content-header--slim">
        <BreadcrumbNav
          :items="crumbItems"
          :back-label="navBack?.label"
          @back="handleNavBack"
          @navigate="(to: string) => router.push(to)"
        />
      </div>

      <!-- 子路由内容 -->
      <div v-if="selectedSpaceId" class="content-body">
        <router-view :key="`${route.params.id || ''}-${kbRefreshKey}`" />
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
 * 知识空间子路由壳（纯壳）：面包屑/返回栏 + KB 子路由出口。
 *
 * 对应路由 /home/spaces（SpaceList）。空间选择/创建/管理已上提全局侧栏
 * （WorkbenchSidebar），本壳只承载面包屑、返回导航与 router-view。
 */

import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Setting } from '@element-plus/icons-vue'

import { useSpaceStore } from '@/stores/space'
import { knowledgeBaseApi } from '@/api/knowledge'
import BreadcrumbNav from '@/components/common/BreadcrumbNav.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const selectedSpaceId = ref<number | null>(null)
const kbRefreshKey = ref(0)

// === 空间选择（侧栏列表） ===

// === Tab 导航 ===

function switchTab(tab: string) {
  if (selectedSpaceId.value) {
    router.push(`/home/spaces/${selectedSpaceId.value}/${tab}`)
  }
}

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

function handleNavBack() {
  if (navBack.value) router.push(navBack.value.to)
}

// 分段面包屑链：所有 KB 子页面统一三段「空间名 → KB 实体名 → 功能名」，
// 空间级页面两段「空间名 → 功能名」——同类页面链路长度一致，头部布局稳定
const crumbItems = computed(() => {
  const items: Array<{ label: string; to?: string }> = []
  const sid = selectedSpaceId.value
  if (!sid) return items

  const kbIdParam =
    (route.params.kbId as string | undefined) ?? (route.query.kbId as string | undefined)
  const kbBase = `/home/spaces/${sid}/knowledge-bases`

  const isKbHome = route.name === 'KnowledgeBases'
  items.push({
    label: spaceStore.currentSpace?.name || '知识空间',
    to: isKbHome ? undefined : kbBase,
  })

  // KB 级页面：统一插入 KB 实体段（真实名；映射未命中时异步拉取后自动更新）
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



.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
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

.content-header {
  display: flex;
  align-items: center;
  background: var(--color-bg-card);
  border-bottom: 1px solid var(--color-border);
  box-shadow: var(--shadow-xs);
  flex-shrink: 0;
}

/* 空间首页：完整栏 —— 发丝线 + 大留白，无阴影 */
.content-header--full {
  justify-content: space-between;
  padding: var(--space-5) var(--space-8);
}

/* 子页面：极简返回栏 */
.content-header--slim {
  gap: var(--space-3);
  padding: 0 var(--space-6);
  height: 44px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

/* ===== Header 按钮：Linear 极简风（扁平 · 发丝线 · hover 浅底，无阴影/上浮） ===== */
.header-actions {
  gap: var(--space-2);
}

.header-actions :deep(.el-button) {
  border-radius: var(--radius-md);
  font-weight: var(--weight-medium);
  transition:
    background-color var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

/* 实心主操作（新建知识库）：与全局主按钮同一 token，随亮暗主题反转 */
.header-actions :deep(.el-button.el-button--primary) {
  border: none;
  padding: 6px 14px;
  font-size: 14px;
  height: auto;
  transition: background-color var(--transition-fast);
}

.header-actions :deep(.el-button.el-button--primary) span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.header-actions :deep(.el-button.el-button--primary:active) {
  transform: translateY(0);
}

/* 次级按钮（新建知识空间）：描边样式，hover 浅底，层级低于主按钮 */
.header-actions :deep(.el-button:not(.is-text):not(.is-circle):not(.el-button--primary)) {
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  padding: 6px 14px;
  font-size: 14px;
  height: auto;
  box-shadow: none;
  transition:
    background var(--transition-fast),
    color var(--transition-fast),
    border-color var(--transition-fast);
}

.header-actions :deep(.el-button:not(.is-text):not(.is-circle):not(.el-button--primary) span) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.header-actions :deep(.el-button:not(.is-text):not(.is-circle):not(.el-button--primary):hover) {
  color: var(--color-text);
  border-color: var(--color-border);
  background: var(--color-bg-hover);
  transform: none;
  box-shadow: none;
}

/* 圆形图标按钮：发丝线，透明底，hover 浅底 */
.header-actions :deep(.el-button.is-circle) {
  width: 30px;
  height: 30px;
  border: 1px solid var(--color-border);
  background: transparent;
  color: var(--color-text-secondary);
  box-shadow: none;
}

.header-actions :deep(.el-button.is-circle:hover) {
  color: var(--color-text);
  border-color: var(--color-border);
  background: var(--color-bg-hover);
  transform: none;
  box-shadow: none;
}

/* 文字按钮：hover 浅底 */
.header-actions :deep(.el-button.is-text:hover) {
  color: var(--color-text);
  background: var(--color-bg-hover);
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
