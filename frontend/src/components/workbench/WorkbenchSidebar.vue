<template>
  <aside class="workbench-sidebar" :class="{ collapsed }" aria-label="工作台侧栏">
    <!-- 品牌行：展开态右缘是收起箭头；折叠态下方紧跟显式展开钮（控件必须可见可点） -->
    <div class="brand-row" :title="collapsed ? 'NovaMind' : undefined">
      <span class="brand-mark"><UnicornIcon :size="18" /></span>
      <span v-if="!collapsed" class="brand-name">NovaMind</span>
      <button
        v-if="!collapsed"
        type="button"
        class="brand-collapse"
        title="收起侧栏"
        aria-label="收起侧栏"
        @click="collapsed = true"
      >
        <el-icon :size="14"><Fold /></el-icon>
      </button>
    </div>

    <!-- 折叠轨的展开钮（紧随 logo，与轨上图标同形态） -->
    <button
      v-if="collapsed"
      type="button"
      class="rail-expand"
      title="展开侧栏"
      aria-label="展开侧栏"
      @click="collapsed = false"
    >
      <el-icon :size="16"><Expand /></el-icon>
    </button>

    <!-- 主体滚动区：KB 登记册独占主体（空间切换器已上移顶栏、系统组沉底）；
         列表超长时本区整体滚动，品牌/系统沉首尾 -->
    <div class="sidebar-scroll">
      <KbRegister v-if="!collapsed && sidebarSpaceId" :space-id="sidebarSpaceId" />
    </div>

    <!-- 系统沉底：低频工具不占常驻行——展开态为文字行（点开向上弹菜单），
         折叠态为单图标（向右弹菜单）。分隔线只留这一条，锚定底缘 -->
    <div class="system-slot">
      <el-popover
        v-if="!collapsed"
        placement="top-start"
        :width="180"
        :show-arrow="false"
        trigger="click"
      >
        <template #reference>
          <button type="button" class="system-row" title="系统" aria-label="系统菜单">
            <el-icon :size="14"><Setting /></el-icon>
            <span class="system-row-text">系统</span>
            <el-icon :size="12" class="system-row-chevron"><ArrowUp /></el-icon>
          </button>
        </template>
        <SidebarSystemGroup class="popover-system" />
      </el-popover>
      <el-popover
        v-else
        placement="right-start"
        :width="180"
        :show-arrow="false"
        trigger="click"
      >
        <template #reference>
          <button type="button" class="collapsed-system" title="系统" aria-label="系统菜单">
            <el-icon :size="16"><Setting /></el-icon>
          </button>
        </template>
        <SidebarSystemGroup class="popover-system" />
      </el-popover>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * 登记簿式全局侧栏（全站唯一工作台导航）。
 *
 * 三原则落地：登记簿（字行纪律，结构区块恒定、增长只进 KB 滚动区）/
 * 墨迹即位置（3px 墨水左缘线，无底色 pill）/ 工具沉底知识居中（KB 区独占
 * 主体，系统/折叠沉首尾——空间切换器已上移全局顶栏 2026-11，系统组收成
 * 底缘单行弹菜单）。折叠为手动 + localStorage 持久化（<1024px 初始默认
 * 折叠）；折叠态只保留品牌块与系统图标。
 *
 * 路由同步链：watch 路由 :id → fetchSpace（store 内同 id 去重）+ 记录
 * 最近访问（首页直达与切换器「最近使用」的数据源）+ 拉当前空间 KB 登记册。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowUp, Expand, Fold, Setting } from '@element-plus/icons-vue'
import { useSpaceStore } from '@/stores/space'
import { useUserStore } from '@/stores/user'
import UnicornIcon from '@/components/common/UnicornIcon.vue'
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
  /* 底部呼吸：系统行抬离视口底缘（主流侧栏惯例） */
  padding-bottom: var(--space-3);
  overflow: hidden;
  transition: width var(--transition-base);
}

.workbench-sidebar.collapsed {
  width: var(--sidebar-width-collapsed);
}

/* ===== 品牌行 ===== */
/* 分隔线只留系统槽上一条：品牌行靠留白与切换器分区，不再画底线 */
.brand-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  height: 48px;
  padding: 0 var(--space-3);
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

/* ===== 系统沉底槽 ===== */
/* 全侧栏唯一保留的分隔线：锚定底缘工具区，与 KB 主体分区 */
.system-slot {
  flex-shrink: 0;
  border-top: 1px solid var(--color-border-light);
  padding-top: var(--space-1);
}

.system-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  height: 32px;
  padding: 0 var(--space-3);
  border: none;
  background: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  text-align: left;
  font-size: var(--text-sm);
  border-radius: var(--radius-md);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.system-row:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 字形列统一 18px 宽：与 KB 行/系统菜单项的文字起点同一竖线 */
.system-row .el-icon {
  flex-shrink: 0;
  width: 18px;
}

.system-row-chevron {
  margin-left: auto;
  color: var(--color-text-faint);
}

.collapsed .system-slot {
  display: flex;
  justify-content: center;
}

/* 折叠态系统图标钮：窄轨上与品牌/展开钮同轴居中 */
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

.collapsed-system:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 折叠轨的展开钮：与轨上图标钮同形态（36px 居中、hover 浅底） */
.rail-expand {
  align-self: center;
  margin-top: var(--space-1);
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

/* 主体滚动区：登记册按内容自然高度；超长整体滚动（系统已沉底不随滚） */
.sidebar-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  /* KB 区顶部与品牌行拉开一档呼吸 */
  padding-top: var(--space-2);
}

/* ===== 品牌行的收起箭头（展开态右缘）/ 折叠态整行为展开钮 ===== */
.brand-collapse {
  margin-left: auto;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: none;
  color: var(--color-text-faint);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition:
    color var(--transition-fast),
    background var(--transition-fast);
}

.brand-collapse:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

/* 弹层内的系统菜单（组件本身无分隔线，无需再覆盖） */
.popover-system {
  min-width: 160px;
}
</style>
