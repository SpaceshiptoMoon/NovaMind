<template>
  <aside class="chat-sidebar" :class="{ compact, 'mobile-open': mobileOpen }">
    <div class="sidebar-top">
      <button
        v-if="isNarrowViewport"
        class="sidebar-toggle-btn"
        :title="mobileOpen ? '收起会话列表' : '展开会话列表'"
        @click="emit('update:mobileOpen', !mobileOpen)"
      >
        <el-icon :size="16">
          <Expand v-if="!mobileOpen" />
          <Close v-else />
        </el-icon>
      </button>
      <button v-if="showBack" class="back-btn" @click="emit('back')">
        <el-icon :size="14"><ArrowLeft /></el-icon>
        <span>返回</span>
      </button>
      <button class="new-chat-btn" @click="emit('new')">
        <el-icon :size="16"><Plus /></el-icon>
        <span>{{ newLabel }}</span>
      </button>
    </div>
    <div class="conversation-list">
      <div
        v-for="conv in sessions"
        :key="conv.id"
        class="conv-item"
        :class="{ active: currentSessionId === conv.id }"
        @click="emit('select', conv.id)"
      >
        <span class="conv-title">{{ conv.title }}</span>
        <button class="conv-delete" @click.stop="emit('delete', conv.id)">
          <el-icon :size="12"><Delete /></el-icon>
        </button>
      </div>
      <div v-if="sessions.length === 0 && !loading" class="sidebar-empty">
        <span>{{ emptyText }}</span>
      </div>
    </div>
  </aside>
</template>

<script setup lang="ts">
/**
 * 聊天会话侧栏（单聊/群聊共用）：新建 + 会话列表 + 删除。
 *
 * 纯展示件：会话数据由父层组装成 {id,title} 传入，选中/新建/删除动作上抛；
 * 窄屏（≤720px）改绝对定位悬浮抽屉，开合态经 v-model:mobileOpen 由父层托管
 * （父层在选中会话后收起让位主区）。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowLeft, Close, Delete, Expand, Plus } from '@element-plus/icons-vue'

export interface SidebarSession {
  id: string
  title: string
}

withDefaults(
  defineProps<{
    sessions: SidebarSession[]
    currentSessionId: string | null
    loading?: boolean
    /** 新建按钮文案（新对话/新会话） */
    newLabel?: string
    emptyText?: string
    /** 是否显示返回按钮（单聊返回智能体占位页；群聊无） */
    showBack?: boolean
    /** 紧凑宽度（工作台内 220px，独立页 260px） */
    compact?: boolean
    mobileOpen?: boolean
  }>(),
  {
    loading: false,
    newLabel: '新对话',
    emptyText: '暂无对话',
    showBack: false,
    compact: false,
    mobileOpen: false,
  },
)

const emit = defineEmits<{
  (e: 'select', sessionId: string): void
  (e: 'new'): void
  (e: 'delete', sessionId: string): void
  (e: 'back'): void
  (e: 'update:mobileOpen', v: boolean): void
}>()

// 窄屏（≤720px）侧栏改悬浮抽屉；选中会话后由父层收起让位主区
const isNarrowViewport = ref(window.innerWidth <= 720)
function onResize() {
  isNarrowViewport.value = window.innerWidth <= 720
  if (!isNarrowViewport.value) emit('update:mobileOpen', false)
}
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<style scoped>
.chat-sidebar {
  width: 260px;
  border-right: 1px solid var(--color-border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  /* 与工作台目录栏同底色：左两栏（目录+会话）一体暖灰，聊天画布独白聚焦 */
  background: var(--color-bg-sidebar);
}

.chat-sidebar.compact {
  width: 220px;
}

/* 窄屏断点：固定 220px 侧栏不收缩，会把聊天主区挤到不可用（320px 下仅剩 ~50px）；
   断点内改绝对定位悬浮，主区占满全宽，经顶栏按钮开合 */
@media (max-width: 720px) {
  .chat-sidebar {
    position: absolute;
    z-index: 30;
    height: 100%;
    box-shadow: var(--shadow-lg);
    transform: translateX(-100%);
    transition: transform 0.25s ease;
  }

  .chat-sidebar.mobile-open {
    transform: translateX(0);
  }
}

.sidebar-top {
  padding: var(--space-4);
  border-bottom: 1px solid var(--color-border-light);
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.sidebar-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-base);
}

.sidebar-toggle-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: var(--space-2) var(--space-3);
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
  background: transparent;
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
}

.back-btn:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.new-chat-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-md);
  background: var(--color-bg-card);
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition: all var(--transition-base);
}

.new-chat-btn:hover {
  border-color: var(--color-border);
  background: var(--color-bg-hover);
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-2);
}

.conv-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-3) var(--space-3);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background var(--transition-fast);
  margin-bottom: 2px;
  position: relative;
}

.conv-item:hover {
  background: var(--color-bg-hover);
}

.conv-item.active {
  /* 与目录栏 list-item.active 同款中性选中语言（灰底+墨色指示条），两栏一体 */
  background: var(--color-bg-hover);
}

.conv-item.active .conv-title {
  color: var(--color-text);
  font-weight: var(--weight-medium);
}

.conv-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 6px;
  bottom: 6px;
  width: 3px;
  border-radius: 2px;
  background: var(--color-text);
}

.conv-title {
  flex: 1;
  font-size: var(--text-sm);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: var(--leading-normal);
}

.conv-delete {
  opacity: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  transition: all var(--transition-fast);
  flex-shrink: 0;
}

.conv-item:hover .conv-delete {
  opacity: 1;
}

.conv-delete:hover {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.sidebar-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8) var(--space-4);
  font-size: var(--text-sm);
  color: var(--color-text-faint);
}
</style>
