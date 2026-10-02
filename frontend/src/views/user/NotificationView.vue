<template>
  <div class="notification-view">
    <PageHeader title="通知中心">
      <el-button :disabled="notifStore.unreadCount === 0" @click="handleMarkAllRead">
        全部标记为已读
      </el-button>
      <el-button @click="settingsOpen = !settingsOpen">
        <el-icon><Setting /></el-icon>
        通知偏好
      </el-button>
    </PageHeader>

    <!-- 通知偏好设置 -->
    <div v-if="settingsOpen" v-loading="prefsLoading" class="prefs-card">
      <div class="prefs-row">
        <div class="prefs-label">
          <span class="prefs-title">站内通知</span>
          <span class="prefs-desc">在通知中心与顶栏铃铛接收通知</span>
        </div>
        <el-switch v-model="prefs.in_app_enabled" @change="handleSavePrefs" />
      </div>
      <div class="prefs-row">
        <div class="prefs-label">
          <span class="prefs-title">邮件通知</span>
          <span class="prefs-desc">重要事件同步发送到账户邮箱</span>
        </div>
        <el-switch v-model="prefs.email_enabled" @change="handleSavePrefs" />
      </div>
      <div class="prefs-row prefs-column">
        <div class="prefs-label">
          <span class="prefs-title">接收类型</span>
          <span class="prefs-desc">不勾选任何类型时接收全部类型</span>
        </div>
        <el-checkbox-group v-model="prefs.types_enabled" @change="handleSavePrefs">
          <el-checkbox
            v-for="(label, type) in typeLabels"
            :key="type"
            :value="type"
            :label="label"
            >{{ label }}</el-checkbox
          >
        </el-checkbox-group>
      </div>
    </div>

    <!-- 全部 / 未读 筛选 -->
    <div class="filter-tabs" role="tablist">
      <button
        role="tab"
        :aria-selected="filter === 'all'"
        :class="['filter-tab', { active: filter === 'all' }]"
        @click="setFilter('all')"
      >
        全部
        <span class="tab-count">{{ allTotal }}</span>
      </button>
      <button
        role="tab"
        :aria-selected="filter === 'unread'"
        :class="['filter-tab', { active: filter === 'unread' }]"
        @click="setFilter('unread')"
      >
        未读
        <span class="tab-count">{{ notifStore.unreadCount }}</span>
      </button>
    </div>

    <div v-loading="loading" class="notification-content">
      <EmptyState
        v-if="!loading && items.length === 0"
        :headline="emptyHeadline"
        :description="emptyDescription"
        variant="data"
      >
        <el-button @click="openPrefs">配置通知偏好</el-button>
      </EmptyState>
      <template v-else-if="!loading || items.length > 0">
        <ul class="notification-list">
          <li
            v-for="n in items"
            :key="n.id"
            :class="['notification-item', { unread: !n.is_read }]"
            @click="handleClick(n)"
          >
            <span class="type-icon" :title="getTypeLabel(n.type)">
              <el-icon><component :is="iconFor(n.type)" /></el-icon>
            </span>
            <div class="item-main">
              <div class="item-title">{{ n.title }}</div>
              <div class="item-desc">{{ n.content }}</div>
            </div>
            <div class="item-side">
              <time class="item-time" :datetime="n.created_at" :title="formatDate(n.created_at)">
                {{ formatRelativeTime(n.created_at) }}
              </time>
              <span v-if="!n.is_read" class="unread-dot" aria-label="未读" />
            </div>
          </li>
        </ul>
        <Pagination
          v-if="total > pageSize"
          v-model:page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          @change="fetchNotifications"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 站内通知中心页。
 *
 * 对应路由 /home/notifications：全部/未读筛选分页列表（后端 unread_only），
 * 点击行标记已读并按 link 跳转，支持全部已读与通知偏好（站内/邮件/接收类型），
 * 偏好区首次展开时才拉取。筛选计数与顶栏铃铛同源（notification store）。
 */

import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import {
  Bell,
  User,
  Document,
  Search,
  Compass,
  Finished,
  Lock,
  Reading,
  TrendCharts,
  AlarmClock,
  Warning,
  Message,
} from '@element-plus/icons-vue'
import type { Component } from 'vue'
import { notificationApi } from '@/api/notification'
import { useNotificationStore } from '@/stores/notification'
import { formatDate, formatRelativeTime } from '@/utils/format'
import type { Notification } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Pagination from '@/components/common/Pagination.vue'

const router = useRouter()
const notifStore = useNotificationStore()
const loading = ref(false)
const items = ref<Notification[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

type NotificationFilter = 'all' | 'unread'
const filter = ref<NotificationFilter>('all')
// 「全部」计数独立于当前筛选维护：切到未读后 total 变为未读总数，不能覆盖它
const allTotal = ref(0)

const emptyHeadline = computed(() => (filter.value === 'unread' ? '没有未读通知' : '暂无通知'))

const emptyDescription = computed(() =>
  filter.value === 'unread'
    ? '全部通知都已处理。可在通知偏好中调整接收范围。'
    : '有新通知会第一时间出现在这里。可在通知偏好中调整接收范围。',
)

// 通知偏好（展开区，展开时拉取）
const settingsOpen = ref(false)
const prefsLoading = ref(false)
const prefs = reactive({
  in_app_enabled: true,
  email_enabled: true,
  types_enabled: [] as string[],
})

const typeLabels: Record<string, string> = {
  system: '系统',
  space_invite: '空间邀请',
  document_ready: '文档处理',
  resume_completed: '简历挖掘',
  research_done: '深度研究',
  skill_review: '技能审核',
  password_reset: '密码重置',
  wiki_ready: 'Wiki 生成',
  kb_ops_weekly_digest: '知识运营周报',
  kb_review_due: '复审提醒',
  kb_contradiction_confirmed: '内容矛盾',
}

// 类型 → 图标：统一中性色，仅靠形状区分类型（克制即层级，不上装饰色）
const typeIcons: Record<string, Component> = {
  system: Bell,
  space_invite: User,
  document_ready: Document,
  resume_completed: Search,
  research_done: Compass,
  skill_review: Finished,
  password_reset: Lock,
  wiki_ready: Reading,
  kb_ops_weekly_digest: TrendCharts,
  kb_review_due: AlarmClock,
  kb_contradiction_confirmed: Warning,
}

function getTypeLabel(type: string): string {
  return typeLabels[type] || '通知'
}

function iconFor(type: string): Component {
  return typeIcons[type] || Message
}

function setFilter(next: NotificationFilter) {
  if (filter.value === next) return
  filter.value = next
  currentPage.value = 1
  fetchNotifications()
}

function openPrefs() {
  settingsOpen.value = true
}

async function fetchPrefs() {
  prefsLoading.value = true
  try {
    const res = await notificationApi.getPreferences()
    prefs.in_app_enabled = res.in_app_enabled
    prefs.email_enabled = res.email_enabled
    prefs.types_enabled = res.types_enabled || []
  } catch {
    // 静默：偏好加载失败不阻塞通知列表
  } finally {
    prefsLoading.value = false
  }
}

async function handleSavePrefs() {
  try {
    const res = await notificationApi.updatePreferences({
      in_app_enabled: prefs.in_app_enabled,
      email_enabled: prefs.email_enabled,
      types_enabled: prefs.types_enabled,
    })
    // 以服务端返回为准回填（防并发覆盖）
    prefs.in_app_enabled = res.in_app_enabled
    prefs.email_enabled = res.email_enabled
    prefs.types_enabled = res.types_enabled || []
    ElMessage.success('偏好已保存')
  } catch {
    ElMessage.error('保存偏好失败')
  }
}

/** 按筛选与分页拉取通知列表，未读数回写 store 供顶栏铃铛徽标同源同步。 */
async function fetchNotifications() {
  loading.value = true
  try {
    const res = await notificationApi.getNotifications({
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
      unread_only: filter.value === 'unread',
    })
    items.value = res.items
    total.value = res.total
    if (filter.value === 'all') {
      allTotal.value = res.total
    }
    // 未读数经 store 同步（header 徽标同源收敛）
    notifStore.unreadCount = res.unread_count
  } catch {
    ElMessage.error('加载通知失败')
  } finally {
    loading.value = false
  }
}

async function handleMarkAllRead() {
  try {
    await notifStore.markAllRead()
    ElMessage.success('已全部标记为已读')
    await fetchNotifications()
  } catch {
    ElMessage.error('操作失败')
  }
}

/** 点击通知行：未读则先标记已读，携带 link 时跳转对应页面。 */
async function handleClick(n: Notification) {
  if (!n.is_read) {
    await notifStore.markRead(n.id)
    n.is_read = true
    notifStore.unreadCount = Math.max(0, notifStore.unreadCount - 1)
  }
  if (n.link) {
    router.push(n.link)
  }
}

onMounted(() => {
  fetchNotifications()
})

// 偏好区懒加载：首次展开时拉取
watch(settingsOpen, (open) => {
  if (open && !prefsLoading.value) fetchPrefs()
})
</script>

<style scoped>
.notification-view {
  /* flex column 容器内 margin:auto 会吞掉 stretch 致整页退化 fit-content 宽（实测坑），显式撑满 */
  width: 100%;
  max-width: 860px;
  margin: 0 auto;
  padding: var(--space-6);
}

.prefs-card {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
  margin-bottom: var(--space-4);
}

.prefs-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-2) 0;
}

.prefs-column {
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-2);
}

.prefs-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.prefs-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.prefs-desc {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

/* 全部/未读 分段筛选（shadcn segmented 味：灰槽 + 白卡活动态） */
.filter-tabs {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  background: var(--color-bg-input);
  border-radius: var(--radius-md);
  margin-bottom: var(--space-4);
}

.filter-tab {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 5px var(--space-3);
  border: none;
  border-radius: calc(var(--radius-md) - 2px);
  background: transparent;
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    color var(--transition-fast);
}

.filter-tab:hover {
  color: var(--color-text);
}

.filter-tab.active {
  background: var(--color-bg-card);
  color: var(--color-text);
  font-weight: var(--weight-medium);
  box-shadow: var(--shadow-xs);
}

.tab-count {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  line-height: 1;
  padding: 3px 6px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
}

.filter-tab.active .tab-count {
  background: var(--color-primary-subtle);
  color: var(--color-text-secondary);
}

.notification-content {
  min-height: 200px;
}

/* 列表行式（单卡容器 + 发丝线分行），替代逐条大卡片提高扫读密度 */
.notification-list {
  list-style: none;
  margin: 0;
  padding: 0;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.notification-item {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.notification-item + .notification-item {
  border-top: 1px solid var(--color-border-light);
}

.notification-item:hover {
  background: var(--color-bg-hover);
}

.notification-item.unread {
  background: var(--color-primary-muted);
}

.notification-item.unread:hover {
  background: var(--color-bg-hover);
}

.type-icon {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: var(--color-primary-subtle);
  color: var(--color-primary);
  font-size: 18px;
}

.item-main {
  flex: 1;
  min-width: 0; /* 防长内容撑破 flex 行（抗压缩规范） */
}

.item-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-normal);
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.notification-item.unread .item-title {
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.item-desc {
  font-size: var(--text-sm);
  color: var(--color-text-muted);
  line-height: 1.5;
  margin-top: 2px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-side {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: var(--space-2);
}

.item-time {
  font-size: var(--text-xs);
  /* 用 muted 而非 faint：12px 小字叠加 2.4:1 低对比不可辨（评审 P3），muted 含 hover title 兜底 */
  color: var(--color-text-muted);
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}

.unread-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-info);
}

/* 窄屏：图标列收窄、侧栏时间保持，文本列自然收缩 */
@media (max-width: 640px) {
  .notification-view {
    padding: var(--space-4);
  }

  .notification-item {
    padding: var(--space-3);
  }

  .type-icon {
    width: 30px;
    height: 30px;
    font-size: 15px;
  }
}
</style>
