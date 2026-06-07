<template>
  <div class="notification-view">
    <PageHeader title="通知中心" />
    <div class="notification-toolbar">
      <el-button type="primary" link :disabled="unreadCount === 0" @click="handleMarkAllRead">
        全部标记为已读
      </el-button>
    </div>
    <div v-loading="loading" class="notification-content">
      <EmptyState v-if="!loading && items.length === 0" title="暂无通知" type="list" />
      <div v-else class="notification-items">
        <div
          v-for="n in items"
          :key="n.id"
          :class="['notification-card', { unread: !n.is_read }]"
          @click="handleClick(n)"
        >
          <div class="card-header">
            <StatusTag :label="getTypeLabel(n.type)" :status="n.is_read ? 'default' : 'primary'" />
            <span class="card-time">{{ formatTime(n.created_at) }}</span>
          </div>
          <div class="card-title">{{ n.title }}</div>
          <div class="card-content">{{ n.content }}</div>
        </div>
      </div>
      <Pagination
        v-if="total > pageSize"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="total"
        @change="fetchNotifications"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { notificationApi } from '@/api/notification'
import type { Notification } from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Pagination from '@/components/common/Pagination.vue'

const router = useRouter()
const loading = ref(false)
const items = ref<Notification[]>([])
const total = ref(0)
const unreadCount = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)

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

function formatTime(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}天前`
  return d.toLocaleDateString()
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
    unreadCount.value = res.unread_count
  } catch {
    ElMessage.error('加载通知失败')
  } finally {
    loading.value = false
  }
}

async function handleMarkAllRead() {
  try {
    await notificationApi.markAllRead()
    ElMessage.success('已全部标记为已读')
    await fetchNotifications()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function handleClick(n: Notification) {
  if (!n.is_read) {
    try {
      await notificationApi.markRead(n.id)
      n.is_read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    } catch {
      // 静默处理
    }
  }
  if (n.link) {
    router.push(n.link)
  }
}

onMounted(() => {
  fetchNotifications()
})
</script>

<style scoped>
.notification-view {
  padding: var(--space-6);
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
  transition: background var(--transition-fast), border-color var(--transition-fast);
}

.notification-card:hover {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
}

.notification-card.unread {
  background: var(--color-primary-muted, rgba(64, 158, 255, 0.06));
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
