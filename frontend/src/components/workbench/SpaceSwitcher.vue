<template>
  <div class="space-switcher">
    <el-popover
      v-model:visible="panelVisible"
      placement="bottom-start"
      :width="264"
      :show-arrow="false"
      popper-class="space-register-popper"
      trigger="click"
    >
      <template #reference>
        <!-- 切换器行：22px 首字墨块 + 空间名 + chevron；开关由 popover 的 trigger="click" 全权管理
             （勿再手动翻转 panelVisible——与 trigger 双翻转会一次点击开即关） -->
        <button type="button" class="switcher-row" :title="spaceName">
          <span v-if="currentSpace" class="switcher-avatar" :style="{ background: avatarColor(currentSpace.name) }">{{
            currentSpace.name.charAt(0)
          }}</span>
          <span v-else class="switcher-avatar switcher-avatar--empty">—</span>
          <span class="switcher-name">{{ spaceName }}</span>
          <el-icon :size="12" class="switcher-chevron"><ArrowDown /></el-icon>
        </button>
      </template>

      <!-- 空间注册面板：搜索常驻 + （>8 空间）最近使用 + 全部空间滚动 -->
      <div class="register-panel">
        <el-input
          v-model="searchText"
          size="default"
          placeholder="搜索空间"
          clearable
          :prefix-icon="Search"
          class="panel-search"
        />

        <div class="panel-body">
          <template v-if="showRecentGroup">
            <div class="panel-group-label">最近使用</div>
            <button
              v-for="space in recentSpaces"
              :key="`recent-${space.id}`"
              type="button"
              class="panel-row"
              :class="{ current: space.id === currentSpaceId }"
              @click="selectSpace(space.id)"
            >
              <span class="row-avatar" :style="{ background: avatarColor(space.name) }">{{
                space.name.charAt(0)
              }}</span>
              <span class="row-name">{{ space.name }}</span>
              <span v-if="space.id === currentSpaceId" class="row-current">当前</span>
            </button>
            <div class="panel-divider" />
          </template>

          <div class="panel-group-label">全部空间 {{ filteredSpaces.length }}</div>
          <div class="panel-list">
            <button
              v-for="space in filteredSpaces"
              :key="space.id"
              type="button"
              class="panel-row"
              :class="{ current: space.id === currentSpaceId }"
              :title="space.name"
              @click="selectSpace(space.id)"
            >
              <span class="row-avatar" :style="{ background: avatarColor(space.name) }">{{
                space.name.charAt(0)
              }}</span>
              <span class="row-name">{{ space.name }}</span>
              <span v-if="space.id === currentSpaceId" class="row-current">当前</span>
            </button>
            <div v-if="filteredSpaces.length === 0" class="panel-empty">没有匹配的空间</div>
          </div>
        </div>

        <div class="panel-footer">
          <button type="button" class="footer-action" @click="openCreateDialog">
            <el-icon :size="12"><Plus /></el-icon>
            新建空间
          </button>
          <button type="button" class="footer-action" @click="openManageDialog">
            <el-icon :size="12"><Collection /></el-icon>
            管理空间
          </button>
        </div>
      </div>
    </el-popover>

    <!-- 创建空间（共享弹窗：首页空态与面板 footer 同一实现） -->
    <SpaceCreateDialog v-model:visible="createVisible" />

    <!-- 管理空间弹窗（自 SpaceListView 平移：表格 + 单删/批量删） -->
    <el-dialog v-model="manageVisible" title="管理空间" width="640px" destroy-on-close>
      <div v-if="selectedSpaceIds.length > 0" class="batch-bar">
        <span class="batch-count">已选 {{ selectedSpaceIds.length }} 项</span>
        <el-button size="small" @click="selectedSpaceIds = []">取消选择</el-button>
        <el-button type="danger" size="small" @click="handleBatchDeleteSpaces">批量删除</el-button>
      </div>

      <el-table
        :data="spaceStore.spaces"
        v-loading="manageLoading"
        :element-loading-text="batchProgressText"
        stripe
        @selection-change="handleSpaceSelectionChange"
      >
        <el-table-column type="selection" width="45" />
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="visibility" label="可见性" width="80" align="center">
          <template #default="{ row }">
            <el-tag type="info" size="small">{{ visibilityText(row.visibility) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="160">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button type="danger" link size="small" @click="handleDeleteSpace(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
/**
 * 空间切换器：侧栏首行当前空间 + 注册面板（搜索 / 最近使用 / 全部空间）。
 *
 * 规模伸缩：空间 3 个时面板一屏即全部；50+ 时搜索框常驻起效、列表滚动，
 * 侧栏本体一个像素不变长。最近使用组仅空间 >8 时渲染（与全量重复无意义）。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Collection, Plus, Search } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import type { Space } from '@/api/types'
import { avatarColor } from './avatar'
import SpaceCreateDialog from './SpaceCreateDialog.vue'

const route = useRoute()
const router = useRouter()
const spaceStore = useSpaceStore()

const panelVisible = ref(false)
const searchText = ref('')
const createVisible = ref(false)
const manageVisible = ref(false)

const currentSpace = computed(() => spaceStore.currentSpace)
const currentSpaceId = computed(() => currentSpace.value?.id ?? null)
const spaceName = computed(() => currentSpace.value?.name || '选择空间')

// 最近使用组：空间 >8 才渲染（数据源 store 的访问时间戳）
const showRecentGroup = computed(() => spaceStore.spaces.length > 8)
const recentSpaces = computed(() => {
  const ids = spaceStore.recentSpaceIds(3)
  return ids
    .map((id) => spaceStore.spaces.find((s) => s.id === id))
    .filter((s): s is Space => !!s)
})

const filteredSpaces = computed(() => {
  const kw = searchText.value.trim().toLowerCase()
  const list = [...spaceStore.spaces].sort((a, b) => a.name.localeCompare(b.name, 'zh'))
  if (!kw) return list
  return list.filter((s) => s.name.toLowerCase().includes(kw))
})

/** 选空间：跳该空间 KB 列表（fetchSpace 由路由 watch 链接管） */
function selectSpace(spaceId: number) {
  panelVisible.value = false
  if (spaceId === currentSpaceId.value) return
  void router.push(`/home/spaces/${spaceId}/knowledge-bases`)
}

function openCreateDialog() {
  panelVisible.value = false
  createVisible.value = true
}

function openManageDialog() {
  panelVisible.value = false
  manageVisible.value = true
}

// ===== 管理空间（自 SpaceListView 平移） =====

const manageLoading = ref(false)
const selectedSpaceIds = ref<number[]>([])
const batchProgressText = ref('')

function visibilityText(visibility?: number): string {
  if (visibility === undefined) return '未知'
  return ({ 0: '私有', 1: '团队', 2: '公开' } as Record<number, string>)[visibility] || '未知'
}

function formatDate(date: string): string {
  try {
    return (
      new Date(date).toLocaleDateString('zh-CN') +
      ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    )
  } catch {
    return '-'
  }
}

function handleSpaceSelectionChange(rows: Space[]) {
  selectedSpaceIds.value = rows.map((r) => r.id)
}

async function handleDeleteSpace(space: Space) {
  try {
    await ElMessageBox.confirm(
      `确定要删除空间 "${space.name}" 吗？此操作将删除所有关联知识库和文档，且不可恢复。`,
      '警告',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'error' },
    )
    manageLoading.value = true
    await spaceStore.deleteSpace(space.id)
    ElMessage.success('空间已删除')
    if (Number(route.params.id) === space.id) {
      void router.replace('/home/spaces')
    }
    void spaceStore.fetchSpaces()
  } catch {
    // 用户取消 / 错误提示由拦截器处理
  } finally {
    manageLoading.value = false
  }
}

/** 逐个串行删除选中空间（高危操作不并行），进度写进表格 loading 文本。 */
async function handleBatchDeleteSpaces() {
  if (selectedSpaceIds.value.length === 0) return

  try {
    await ElMessageBox.confirm(
      `确定要删除选中的 ${selectedSpaceIds.value.length} 个空间吗？此操作将删除所有关联知识库和文档，且不可恢复。`,
      '批量删除',
      { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'error' },
    )
  } catch {
    return
  }

  manageLoading.value = true
  const ids = [...selectedSpaceIds.value]
  let failCount = 0
  let index = 0
  batchProgressText.value = `正在删除 0/${ids.length} ...`

  for (const id of ids) {
    batchProgressText.value = `正在删除 ${index + 1}/${ids.length} ...`
    try {
      await spaceStore.deleteSpace(id)
    } catch {
      failCount++
    }
    index++
  }

  selectedSpaceIds.value = []
  if (failCount === 0) {
    ElMessage.success(`已删除 ${ids.length} 个空间`)
  } else {
    ElMessage.warning(`${ids.length - failCount} 个删除成功，${failCount} 个删除失败`)
  }

  if (route.params.id && ids.includes(Number(route.params.id))) {
    void router.replace('/home/spaces')
  }
  void spaceStore.fetchSpaces()
  manageLoading.value = false
}
</script>

<style scoped>
.switcher-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  height: 40px;
  padding: 0 var(--space-3);
  border: none;
  background: none;
  color: var(--color-text);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
}

.switcher-row:hover {
  background: var(--color-bg-hover);
}

.switcher-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.switcher-avatar--empty {
  background: var(--color-bg-hover);
}

.switcher-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  text-align: left;
}

.switcher-chevron {
  flex-shrink: 0;
  color: var(--color-text-faint);
  transition: transform var(--transition-fast);
}

/* ===== 注册面板 ===== */
.panel-search {
  margin-bottom: var(--space-2);
}

.panel-body {
  max-height: min(46vh, 420px);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.panel-group-label {
  font-size: var(--text-xs);
  color: var(--color-text-faint);
  padding: var(--space-1) var(--space-1) var(--space-1);
}

.panel-divider {
  height: 1px;
  background: var(--color-border-light);
  margin: var(--space-1) 0;
}

.panel-list {
  overflow-y: auto;
  min-height: 0;
}

.panel-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  height: 32px;
  padding: 0 var(--space-2);
  border: none;
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.panel-row:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 当前行 = 墨线 + semibold + 尾标「当前」（文字，非图标） */
.panel-row.current {
  color: var(--color-primary);
  font-weight: var(--weight-semibold);
}

.panel-row.current::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  bottom: 7px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--color-primary);
}

.row-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.row-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-sm);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-current {
  flex-shrink: 0;
  font-size: var(--text-xs);
  font-weight: var(--weight-normal);
  color: var(--color-text-faint);
}

.panel-empty {
  padding: var(--space-3);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
  text-align: center;
}

.panel-footer {
  display: flex;
  border-top: 1px solid var(--color-border-light);
  margin-top: var(--space-2);
  padding-top: var(--space-2);
  gap: var(--space-1);
}

.footer-action {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  height: 30px;
  border: none;
  background: none;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.footer-action:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.batch-count {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
}
</style>
