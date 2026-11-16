<template>
  <aside class="workbench-sidebar" :class="{ collapsed }" aria-label="工作台侧栏">
    <!-- 品牌行：折叠态只显 Logo；logo 收进 18px 字形列，品牌名与其余行文字同一条 38px 竖线 -->
    <div class="brand-row" :title="collapsed ? 'NovaMind' : undefined">
      <span class="brand-mark"><UnicornIcon :size="18" /></span>
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

    <!-- 折叠/展开钮：壳控制区（紧跟切换器，不沉底）——离用户的常用区近，不贴视口底缘 -->
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

    <!-- 当前空间 KB 登记册（唯一滚动区，占满主体高度；折叠态不显示——48px 辨识不了 KB） -->
    <KbRegister v-if="!collapsed && sidebarSpaceId" :space-id="sidebarSpaceId" />

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

/**
 * 侧栏空间上下文：路由 :id 优先，无空间参数的页面（全局检索/系统页/通知页）
 * 回退最近空间——结构区块恒定是位置感的前提，KB 登记册不随页面消失。
 */
const sidebarSpaceId = computed(() => routeSpaceId.value ?? spaceStore.currentSpace?.id ?? null)

// 路由同步链：空间上下文 + 最近访问 + KB 登记册。
// 无空间参数的页面（全局检索/系统页）不清空上下文——KB 登记册回退最近
// 空间（结构区块恒定）；刷新落地且无上下文时从「最近空间」恢复。
watch(
  routeSpaceId,
  async (spaceId) => {
    if (spaceId) {
      const uid = userStore.getUserIdFromToken()
      spaceStore.touchSpaceAccess(spaceId, uid)
      try {
        await spaceStore.fetchSpace(spaceId)
        await spaceStore.fetchCurrentSpaceKbs(spaceId)
      } catch {
        // 空间不存在/无权限：SpaceListView 壳的兜底回退逻辑接管
      }
      return
    }
    if (!spaceStore.currentSpace) {
      const uid = userStore.getUserIdFromToken()
      const lastId = uid != null ? spaceStore.getLastSpaceId(uid) : null
      const fallback = lastId ?? spaceStore.spaces[0]?.id ?? null
      if (!fallback) return
      if (!spaceStore.spaces.length) {
        try {
          await spaceStore.fetchSpaces()
        } catch {
          return
        }
      }
      try {
        await spaceStore.fetchSpace(fallback)
        await spaceStore.fetchCurrentSpaceKbs(fallback)
      } catch {
        // 最近空间已不可达：侧栏保持「选择空间」占位
      }
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

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  flex-shrink: 0;
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
/* ===== 切换器槽：横向零内边距——行自身 12px 左缘与全侧栏行对齐 ===== */
.switcher-slot {
  padding: var(--space-2) 0 var(--space-2);
}

.collapsed .switcher-slot {
  display: flex;
  justify-content: center;
  padding: var(--space-2) 0;
}

/* 系统图标（popover reference 是 aside 直接子节点）：窄轨上与品牌/切换器同轴居中 */
.collapsed-system {
  align-self: center;
  margin-top: var(--space-1);
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

/* KB 登记册（flex:1）独自占满主体高度，把系统组自然压到底——无需弹性补位
   （历史教训：补位 div 若也是 flex:1 会与登记册平分高度，登记区被腰斩） */

/* ===== 折叠/展开钮：壳控制区行（切换器下方），与其余行同一缩进与右圆角语言 ===== */
.collapse-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 36px;
  margin: 0;
  padding: 0 var(--space-3);
  border: none;
  background: none;
  color: var(--color-text-faint);
  font-size: var(--text-xs);
  cursor: pointer;
  border-radius: 0 var(--radius-md) var(--radius-md) 0;
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

/* 折叠态：窄轨上居中的图标钮（全角圆角，与轨上其他图标同轴） */
.collapsed .collapse-toggle {
  justify-content: center;
  align-self: center;
  width: 36px;
  padding: 0;
  border-radius: var(--radius-md);
}

.collapse-toggle:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 字形列统一 18px 宽：折叠钮/系统项/KB 行的文字起点落在同一竖线 */
.toggle-icon {
  flex-shrink: 0;
  width: 18px;
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
