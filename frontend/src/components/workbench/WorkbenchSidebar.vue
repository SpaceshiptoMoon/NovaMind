<template>
  <aside class="workbench-sidebar" :class="{ collapsed }" aria-label="工作台侧栏">
    <!-- 品牌行：折叠态只显 Logo -->
    <div class="brand-row" :title="collapsed ? 'NovaMind' : undefined">
      <UnicornIcon :size="24" />
      <span v-if="!collapsed" class="brand-name">NovaMind</span>
    </div>

    <!-- 空间切换器：折叠态退化为当前空间墨块（点击展开侧栏） -->
    <div class="switcher-slot">
      <SpaceSwitcher v-if="!collapsed" />
      <button
        v-else
        type="button"
        class="collapsed-space"
        :title="spaceStore.currentSpace?.name || '展开侧栏'"
        aria-label="展开侧栏"
        @click="collapsed = false"
      >
        <span
          v-if="spaceStore.currentSpace"
          class="collapsed-avatar"
          :style="{ background: avatarColor(spaceStore.currentSpace.name) }"
          >{{ spaceStore.currentSpace.name.charAt(0) }}</span
        >
        <el-icon v-else :size="16"><Collection /></el-icon>
      </button>
    </div>

    <!-- 当前空间 KB 登记册（唯一滚动区；折叠态不显示——48px 辨识不了 KB） -->
    <KbRegister v-if="!collapsed && routeSpaceId" />

    <div class="sidebar-flex-fill" />

    <!-- 系统组：折叠态收成单图标弹菜单 -->
    <SidebarSystemGroup v-if="!collapsed" />
    <el-popover v-else placement="right-start" :width="180" :show-arrow="false" trigger="click">
      <template #reference>
        <button type="button" class="collapsed-system" title="系统" aria-label="系统菜单">
          <el-icon :size="16"><Setting /></el-icon>
        </button>
      </template>
      <SidebarSystemGroup :collapsed="false" class="popover-system" />
    </el-popover>

    <!-- 折叠/展开钮（底部 pinned） -->
    <button
      type="button"
      class="collapse-toggle"
      :title="collapsed ? '展开侧栏' : '收起侧栏'"
      :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
      @click="toggleCollapsed"
    >
      <el-icon :size="14" class="toggle-icon"><Fold v-if="!collapsed" /><Expand v-else /></el-icon>
      <span v-if="!collapsed" class="toggle-text">收起侧栏</span>
    </button>
  </aside>
</template>

<script setup lang="ts">
/**
 * 登记簿式全局侧栏（全站唯一工作台导航）。
 *
 * 三原则落地：登记簿（字行纪律，结构区块恒定、增长只进 KB 滚动区）/
 * 墨迹即位置（3px 墨水左缘线，无底色 pill）/ 工具沉底知识居中（KB 区占
 * 主面积，切换器/系统/折叠沉首尾）。折叠为手动 + localStorage 持久化
 * （<1024px 初始默认折叠）；折叠态只保留品牌块/当前空间墨块/系统图标。
 *
 * 路由同步链：watch 路由 :id → fetchSpace（store 内同 id 去重）+ 记录
 * 最近访问（首页直达与切换器「最近使用」的数据源）+ 拉当前空间 KB 登记册。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Collection, Expand, Fold, Setting } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import { useUserStore } from '@/stores/user'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
import { avatarColor } from './avatar'
import SpaceSwitcher from './SpaceSwitcher.vue'
import KbRegister from './KbRegister.vue'
import SidebarSystemGroup from './SidebarSystemGroup.vue'

const COLLAPSED_KEY = 'novamind:sidebar-collapsed'
/** 折叠的初始默认视口阈值：平板及以下以内容为优先 */
const COLLAPSE_VIEWPORT = 1024

const route = useRoute()
const spaceStore = useSpaceStore()
const userStore = useUserStore()

const collapsed = ref(false)

function initCollapsed() {
  const saved = localStorage.getItem(COLLAPSED_KEY)
  if (saved === '1' || saved === '0') {
    collapsed.value = saved === '1'
    return
  }
  collapsed.value = window.innerWidth < COLLAPSE_VIEWPORT
}

watch(collapsed, (value) => {
  try {
    localStorage.setItem(COLLAPSED_KEY, value ? '1' : '0')
  } catch {
    /* 存储不可用时仅本次会话生效 */
  }
})

function toggleCollapsed() {
  collapsed.value = !collapsed.value
}

const routeSpaceId = computed(() => {
  const raw = route.params.id
  const first = Array.isArray(raw) ? raw[0] : raw
  const id = first == null ? NaN : Number(first)
  return Number.isFinite(id) && id > 0 ? id : null
})

// 路由同步链：空间上下文 + 最近访问 + KB 登记册
watch(
  routeSpaceId,
  async (spaceId) => {
    if (!spaceId) {
      spaceStore.clearCurrentSpace()
      return
    }
    const uid = userStore.getUserIdFromToken()
    spaceStore.touchSpaceAccess(spaceId, uid)
    try {
      await spaceStore.fetchSpace(spaceId)
      await spaceStore.fetchCurrentSpaceKbs(spaceId)
    } catch {
      // 空间不存在/无权限：SpaceListView 壳的兜底回退逻辑接管
    }
  },
  { immediate: true },
)

onMounted(() => {
  initCollapsed()
  if (!spaceStore.spaces.length) {
    void spaceStore.fetchSpaces().catch(() => {
      // 侧栏不阻塞主内容，列表为空时切换器显示「选择空间」
    })
  }
})
</script>

<style scoped>
.workbench-sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border-light);
  overflow: hidden;
  transition: width var(--transition-base);
}

.workbench-sidebar.collapsed {
  width: var(--sidebar-width-collapsed);
}

/* ===== 品牌行 ===== */
.brand-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 48px;
  padding: 0 var(--space-3);
  border-bottom: 1px solid var(--color-border-light);
}

.collapsed .brand-row {
  justify-content: center;
  padding: 0;
}

.brand-name {
  font-family: var(--font-display);
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  letter-spacing: var(--tracking-tight);
  white-space: nowrap;
}

/* ===== 切换器槽 ===== */
.switcher-slot {
  padding: var(--space-2) var(--space-2) 0;
}

.collapsed .switcher-slot {
  padding: var(--space-2) var(--space-1) 0;
}

.collapsed-space,
.collapsed-system {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.collapsed-space:hover,
.collapsed-system:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.collapsed-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: var(--radius-sm);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

/* 登记册的弹性补位：结构区块沉底 */
.sidebar-flex-fill {
  flex: 1;
  min-height: 0;
}

.collapsed .sidebar-flex-fill {
  flex: 0;
}

/* ===== 折叠钮 ===== */
.collapse-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 36px;
  margin: var(--space-2);
  padding: 0 var(--space-3);
  border: none;
  background: none;
  color: var(--color-text-faint);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.collapsed .collapse-toggle {
  justify-content: center;
  padding: 0;
}

.collapse-toggle:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.toggle-icon {
  flex-shrink: 0;
}

.toggle-text {
  white-space: nowrap;
}

/* 折叠态系统弹菜单内的系统组（去边线适配弹层） */
.popover-system {
  border-top: none;
  padding-top: 0;
}
</style>
