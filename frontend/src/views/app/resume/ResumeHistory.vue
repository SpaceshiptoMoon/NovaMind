<template>
  <div class="resume-history">
    <div class="page-header">
      <div class="page-header-left">
        <el-button text @click="router.push('/home/apps')">
          <el-icon><ArrowLeft /></el-icon>
          应用中心
        </el-button>
        <el-divider direction="vertical" />
        <h2>历史记录</h2>
      </div>
      <el-button type="primary" @click="router.push('/home/apps/resume')">
        <el-icon><Plus /></el-icon>
        新建解析
      </el-button>
    </div>

    <!-- 状态筛选栏 -->
    <div class="filter-bar">
      <button
        v-for="opt in statusOptions"
        :key="opt.value"
        class="filter-chip"
        :class="{ 'is-active': activeFilter === opt.value }"
        @click="setFilter(opt.value)"
      >
        <span v-if="opt.value !== null" class="filter-dot" :style="{ background: statusConfig(opt.value).dotColor }" />
        {{ opt.label }}
      </button>
    </div>

    <div v-if="sessions.length" class="session-list" v-loading="loading">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-row"
        @click="handleView(session)"
      >
        <div class="session-icon" :style="{ background: statusConfig(session.status).bgColor }">
          <el-icon :size="20" :color="statusConfig(session.status).dotColor">
            <Document />
          </el-icon>
        </div>

        <div class="session-main">
          <div class="session-title">{{ session.resume_filename || '未命名文件' }}</div>
          <div class="session-meta">
            <span class="meta-item">{{ getCandidateName(session) }}</span>
            <span class="meta-divider">·</span>
            <span class="meta-item">{{ formatDate(session.created_at) }}</span>
          </div>
        </div>

        <div class="session-status">
          <span class="status-dot" :style="{ background: statusConfig(session.status).dotColor }" />
          <span class="status-text" :style="{ color: statusConfig(session.status).textColor }">
            {{ statusConfig(session.status).label }}
          </span>
        </div>

        <div class="session-actions" @click.stop>
          <el-button type="primary" link size="small" @click="handleView(session)">
            查看报告
          </el-button>
          <el-button
            type="primary"
            link
            size="small"
            :disabled="session.status !== 5"
            @click="handleDownload(session)"
          >
            下载
          </el-button>
          <el-popconfirm
            title="确定删除该记录？删除后不可恢复"
            confirm-button-text="删除"
            cancel-button-text="取消"
            confirm-button-type="danger"
            @confirm="handleDelete(session)"
          >
            <template #reference>
              <el-button type="danger" link size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </div>
      </div>
    </div>

    <EmptyState
      v-else-if="!loading"
      headline="暂无记录"
      :description="activeFilter !== null ? '该状态下没有记录' : '还没有简历分析记录，快去上传一份简历吧'"
    >
      <el-button v-if="activeFilter === null" type="primary" @click="router.push('/home/apps/resume')">上传简历</el-button>
      <el-button v-else @click="setFilter(null)">查看全部</el-button>
    </EmptyState>

    <Pagination
      v-if="sessions.length"
      :page="currentPage"
      :page-size="pageSize"
      :total="total"
      :page-sizes="[10, 20, 50]"
      @update:page="(p: number) => { currentPage = p; fetchData() }"
      @update:page-size="(s: number) => { pageSize = s; currentPage = 1; fetchData() }"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, ArrowLeft, Document } from '@element-plus/icons-vue'
import { appApi, type ResumeSession } from '@/api/app'
import Pagination from '@/components/common/Pagination.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const router = useRouter()

const loading = ref(false)
const sessions = ref<ResumeSession[]>([])
const total = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const activeFilter = ref<number | null>(null)

const statusOptions: { label: string; value: number | null }[] = [
  { label: '全部', value: null },
  { label: '解析中', value: 1 },
  { label: '分析中', value: 2 },
  { label: '追问中', value: 4 },
  { label: '已完成', value: 5 },
  { label: '失败', value: 0 },
]

interface StatusStyle {
  label: string
  dotColor: string
  textColor: string
  bgColor: string
}

const statusConfigMap: Record<number, StatusStyle> = {
  0: { label: '失败', dotColor: '#EF4444', textColor: '#EF4444', bgColor: '#FEF2F2' },
  1: { label: '解析中', dotColor: '#F59E0B', textColor: '#D97706', bgColor: '#FFFBEB' },
  2: { label: '分析中', dotColor: '#F59E0B', textColor: '#D97706', bgColor: '#FFFBEB' },
  4: { label: '追问中', dotColor: '#6366F1', textColor: '#6366F1', bgColor: '#EEF2FF' },
  5: { label: '已完成', dotColor: '#22C55E', textColor: '#16A34A', bgColor: '#F0FDF4' },
}

function statusConfig(status: number): StatusStyle {
  return statusConfigMap[status] || { label: '未知', dotColor: '#9CA3AF', textColor: '#9CA3AF', bgColor: '#F9FAFB' }
}

function setFilter(value: number | null) {
  activeFilter.value = value
  currentPage.value = 1
  fetchData()
}

function getCandidateName(row: ResumeSession): string {
  return row.structured_resume?.personal_info?.name || '-'
}

function formatDate(date: string | null): string {
  if (!date) return '-'
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

async function fetchData() {
  loading.value = true
  try {
    const data = await appApi.listSessions(
      pageSize.value,
      (currentPage.value - 1) * pageSize.value,
      activeFilter.value ?? undefined,
    )
    sessions.value = data.sessions
    total.value = data.total
  } catch {
    ElMessage.error('获取历史记录失败')
  } finally {
    loading.value = false
  }
}

function handleView(row: ResumeSession) {
  router.push(`/home/apps/resume/session/${row.id}`)
}

async function handleDownload(row: ResumeSession) {
  try {
    await appApi.downloadReport(row.id)
  } catch {
    ElMessage.error('下载失败')
  }
}

async function handleDelete(row: ResumeSession) {
  try {
    await appApi.deleteSession(row.id)
    ElMessage.success('删除成功')
    fetchData()
  } catch {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.resume-history {
  padding: var(--space-10) var(--space-5);
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
}

.page-header-left {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.page-header h2 {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-2xl);
  font-weight: var(--weight-bold);
  color: var(--color-text);
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  gap: var(--space-2);
  margin-bottom: var(--space-5);
  flex-wrap: wrap;
}

.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-1) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: 999px;
  background: var(--color-bg-card);
  font-size: var(--text-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.filter-chip:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
}

.filter-chip.is-active {
  background: var(--color-primary-subtle);
  border-color: var(--color-primary);
  color: var(--color-primary);
  font-weight: var(--weight-medium);
}

.filter-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.session-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.session-row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-5);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-xl);
  cursor: pointer;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-xs);
}

.session-row:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.session-icon {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-lg);
}

.session-main {
  flex: 1;
  min-width: 0;
}

.session-title {
  font-family: var(--font-display);
  font-size: var(--text-md);
  font-weight: var(--weight-semibold);
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: var(--space-1);
}

.session-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}

.meta-divider {
  color: var(--color-border);
}

.session-status {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 80px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-text {
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
}

.session-actions {
  flex-shrink: 0;
  display: flex;
  gap: var(--space-1);
  opacity: 0;
  transition: opacity var(--transition-fast);
}

.session-row:hover .session-actions {
  opacity: 1;
}
</style>
