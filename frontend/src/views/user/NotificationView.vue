<template>
  <div class="notification-view">
    <PageHeader title="通知中心">
      <el-button text @click="settingsOpen = !settingsOpen">
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

    <div class="notification-toolbar">
      <el-button
        type="primary"
        link
        :disabled="notifStore.unreadCount === 0"
        @click="handleMarkAllRead"
      >
        全部标记为已读
      </el-button>
    </div>
    <div v-loading="loading" class="notification-content">
      <EmptyState v-if="!loading && items.length === 0" headline="暂无通知" />
      <div v-else class="notification-items">
        <div
          v-for="n in items"
          :key="n.id"
          :class="['notification-card', { unread: !n.is_read }]"
          @click="handleClick(n)"
        >
          <div class="card-header">
            <StatusTag :label="getTypeLabel(n.type)" :status="n.is_read ? 'default' : 'primary'" />
            <span class="card-time">{{ formatRelativeTime(n.created_at) }}</span>
          </div>
          <div class="card-title">{{ n.title }}</div>
          <div class="card-content">{{ n.content }}</div>
        </div>
      </div>
      <Pagination
        v-if="total > pageSize"
        v-model:page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        @change="fetchNotifications"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import { notificationApi } from '@/api/notification'
import { useNotificationStore } from '@/stores/notification'
import { formatRelativeTime } from '@/utils/format'
import type { Notification } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Pagination from '@/components/common/Pagination.vue'

const router = useRouter()
const notifStore = useNotificationStore()
const loading = ref(false)
const items = ref<Notification[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

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
}

function getTypeLabel(type: string): string {
  return typeLabels[type] || '通知'
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

async function fetchNotifications() {
  loading.value = true
  try {
    const res = await notificationApi.getNotifications({
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
    })
    items.value = res.items
    total.value = res.total
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

async function handleClick(n: Notification) {
  if (!n.is_read) {
    await notifStore.markRead(n.id)
    n.is_read = true
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

.notification-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-4);
}

.notification-card {
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border-light);
  margin-bottom: var(--space-3);
  cursor: pointer;
  transition:
    background var(--transition-fast),
    border-color var(--transition-fast);
}

.notification-card:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
}

.notification-card.unread {
  background: var(--color-primary-muted);
  border-left: 3px solid var(--color-primary);
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.card-time {
  font-size: var(--text-xs);
  color: var(--color-text-placeholder, #c0c4cc);
}

.card-title {
  font-size: var(--text-sm);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  margin-bottom: var(--space-1);
}

.card-content {
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  line-height: 1.6;
}
</style>
