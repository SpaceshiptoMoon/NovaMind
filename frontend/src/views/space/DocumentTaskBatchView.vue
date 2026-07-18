<template>
  <div class="document-task-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
        <section class="dashboard-panel">
          <div class="dashboard-panel__head">
            <div>
              <p class="dashboard-panel__eyebrow">Task Dashboard</p>
              <h1>任务列表</h1>
              <p class="dashboard-panel__desc">这里展示知识库文档处理的完整流水。按任务查看批次状态，展开后追踪到每个文档子项。</p>
            </div>

            <el-button class="refresh-button" plain :loading="loading" @click="fetchTasks">
              <el-icon><RefreshRight /></el-icon>
              刷新
            </el-button>
          </div>

          <div class="dashboard-grid">
            <article class="dashboard-stat dashboard-stat--primary">
              <span class="dashboard-stat__label">总任务数</span>
              <strong class="dashboard-stat__value">{{ total }}</strong>
              <span class="dashboard-stat__note">后端分页总量</span>
            </article>

            <article class="dashboard-stat">
              <span class="dashboard-stat__label">当前页任务</span>
              <strong class="dashboard-stat__value">{{ tasks.length }}</strong>
              <span class="dashboard-stat__note">本页已加载任务</span>
            </article>

            <article class="dashboard-stat">
              <span class="dashboard-stat__label">本页文档数</span>
              <strong class="dashboard-stat__value">{{ currentPageDocumentCount }}</strong>
              <span class="dashboard-stat__note">当前页任务包含的文档总数</span>
            </article>

            <article class="dashboard-stat">
              <span class="dashboard-stat__label">失败项</span>
              <strong class="dashboard-stat__value">{{ currentPageFailedCount }}</strong>
              <span class="dashboard-stat__note">当前页任务中的失败项</span>
            </article>
          </div>
        </section>

        <section class="task-feed">
          <header class="task-feed__header">
            <div>
              <p class="task-feed__eyebrow">Task Feed</p>
              <h2>处理消息流</h2>
            </div>
            <span class="task-feed__hint">点击展开任务，查看内部文档明细</span>
          </header>

          <div v-loading="loading" class="task-feed__body">
            <el-empty v-if="!tasks.length" description="暂无任务" />
            <template v-else>
              <div class="task-list">
                <article
                  v-for="task in tasks"
                  :key="task.id"
                  class="task-item"
                  :class="[
                    `task-item--${getTaskTone(task.status)}`,
                    { 'task-item--expanded': expandedTaskIds.includes(task.id) },
                  ]"
                >
                  <button class="task-item__summary" type="button" @click="toggleTask(task.id)">
                    <div class="task-item__main">
                      <div class="task-item__title-row">
                        <span class="task-status-dot" :class="`task-status-dot--${getTaskTone(task.status)}`" />
                        <span class="task-id">任务 {{ task.id }}</span>
                        <el-tag :type="getTaskStatusConfig(task.status).type" effect="plain" round size="small">
                          {{ getTaskStatusConfig(task.status).text }}
                        </el-tag>
                        <span class="task-action">{{ getTaskActionText(task.action) }}</span>
                      </div>

                      <div class="task-item__meta">
                        <span>文档数 {{ task.total_count }}</span>
                        <span>创建于 {{ formatDateTime(task.created_at) }}</span>
                        <span>完成于 {{ task.completed_at ? formatDateTime(task.completed_at) : '未完成' }}</span>
                      </div>

                      <div class="task-breakdown">
                        <span class="task-breakdown__item">待处理 {{ task.task_summary?.pending ?? 0 }}</span>
                        <span class="task-breakdown__item is-processing">处理中 {{ task.task_summary?.processing ?? 0 }}</span>
                        <span class="task-breakdown__item is-success">已完成 {{ task.task_summary?.completed ?? 0 }}</span>
                        <span class="task-breakdown__item is-danger">失败 {{ task.task_summary?.failed ?? 0 }}</span>
                        <span class="task-breakdown__item is-muted">取消 {{ task.task_summary?.cancelled ?? 0 }}</span>
                      </div>
                    </div>

                    <div class="task-item__side">
                      <div class="task-overview">
                        <span class="task-overview__label">成功率</span>
                        <strong class="task-overview__value">{{ getTaskSuccessPercent(task) }}%</strong>
                        <el-progress
                          :percentage="getTaskSuccessPercent(task)"
                          :stroke-width="8"
                          :show-text="false"
                          :color="getTaskProgressColor(task.status)"
                        />
                        <span class="task-overview__meta">已结束 {{ getTaskSettledCount(task) }} / {{ task.total_count || 0 }}</span>
                      </div>
                      <span class="task-item__toggle">{{ expandedTaskIds.includes(task.id) ? '收起详情' : '展开详情' }}</span>
                    </div>
                  </button>

                  <div v-if="expandedTaskIds.includes(task.id)" class="task-item__detail">
                    <div v-if="task.note || task.error_message" class="task-item__notice">
                      <p v-if="task.note">{{ task.note }}</p>
                      <p v-if="task.error_message" class="task-item__error">{{ task.error_message }}</p>
                    </div>

                    <el-table :data="task.items" row-key="id" class="detail-table">
                      <el-table-column label="任务项" width="96">
                        <template #default="{ row }">{{ row.id }}</template>
                      </el-table-column>

                      <el-table-column label="文档 ID" width="96" align="center">
                        <template #default="{ row }">{{ row.document_id }}</template>
                      </el-table-column>

                      <el-table-column label="文档" min-width="250">
                        <template #default="{ row }">
                          <div class="doc-cell">
                            <span class="doc-name">{{ getTaskDocumentName(row.document_id, row.pipeline_result, row.document_name) }}</span>
                          </div>
                        </template>
                      </el-table-column>

                      <el-table-column label="状态" width="120" align="center">
                        <template #default="{ row }">
                          <el-tag :type="getItemStatusConfig(row.status).type" effect="plain" round size="small">
                            {{ getItemStatusConfig(row.status).text }}
                          </el-tag>
                        </template>
                      </el-table-column>

                      <el-table-column label="进度" min-width="220">
                        <template #default="{ row }">
                          <div class="progress-cell">
                            <el-progress
                              :percentage="getTaskProgressPercent(row.step_progress)"
                              :stroke-width="7"
                              :show-text="false"
                              color="#0f766e"
                            />
                            <span>{{ getTaskProgressText(row.step_progress) }}</span>
                          </div>
                        </template>
                      </el-table-column>

                      <el-table-column prop="retry_count" label="重试" width="84" align="center" />

                      <el-table-column label="完成时间" width="180">
                        <template #default="{ row }">{{ row.completed_at ? formatDateTime(row.completed_at) : '-' }}</template>
                      </el-table-column>

                      <el-table-column label="错误信息" width="320">
                        <template #default="{ row }">
                          <el-tooltip
                            v-if="row.error_message"
                            :content="row.error_message"
                            placement="top-start"
                            effect="dark"
                            :show-after="200"
                            popper-class="task-error-tooltip"
                          >
                            <span class="error-text">{{ getErrorPreview(row.error_message) }}</span>
                          </el-tooltip>
                          <span v-else class="error-text">-</span>
                        </template>
                      </el-table-column>
                    </el-table>
                  </div>
                </article>
              </div>

              <Pagination
                v-model:page="page"
                v-model:page-size="pageSize"
                :total="total"
                :page-sizes="[10, 20, 50]"
                @change="handlePageChange"
              />
            </template>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, Document, List, RefreshRight, Search } from '@element-plus/icons-vue'

import { documentApi } from '@/api/knowledge'
import type { DocumentTask } from '@/api/types'
import { KbSidebar, buildKbNavItems, taskStatusMap } from '@/components/knowledge'
import Pagination from '@/components/common/Pagination.vue'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const tasks = ref<DocumentTask[]>([])
const expandedTaskIds = ref<number[]>([])
const page = ref(1)
const pageSize = ref(10)
const total = ref(0)
const errorPreviewLength = 80

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const kbNavItems = computed(() =>
  buildKbNavItems({
    spaceId: spaceId.value,
    kbId: kbId.value,
    currentRouteName: route.name,
    icons: {
      document: Document,
      list: List,
      search: Search,
      evaluation: DataAnalysis,
    },
  })
)

const currentPageDocumentCount = computed(() => tasks.value.reduce((sum, task) => sum + (task.total_count || 0), 0))
const currentPageFailedCount = computed(() =>
  tasks.value.reduce((sum, task) => sum + (task.task_summary?.failed ?? 0), 0)
)

async function fetchTasks() {
  loading.value = true
  try {
    const data = await documentApi.getDocumentTasksOverview(spaceId.value, kbId.value, {
      skip: (page.value - 1) * pageSize.value,
      limit: pageSize.value,
    })

    tasks.value = data.items || []
    total.value = data.total || 0
    // 任务列表默认全部收起，不自动展开第一个任务
    expandedTaskIds.value = []
  } finally {
    loading.value = false
  }
}

function toggleTask(taskId: number) {
  expandedTaskIds.value = expandedTaskIds.value.includes(taskId)
    ? expandedTaskIds.value.filter(id => id !== taskId)
    : [...expandedTaskIds.value, taskId]
}

function handlePageChange(nextPage: number, nextPageSize: number) {
  page.value = nextPage
  pageSize.value = nextPageSize
  fetchTasks()
}

function getTaskDocumentName(
  documentId: number,
  pipelineResult?: Record<string, unknown>,
  documentName?: string | null,
) {
  // 优先用后端关联的文档名（Documents.filename），其次用解析结果里的 filename，
  // 都缺失时才回退为占位符「文档 {id}」（仅文档被删除等极端情况）
  if (typeof documentName === 'string' && documentName) return documentName
  const filename = pipelineResult?.filename
  if (typeof filename === 'string' && filename) return filename
  return `文档 ${documentId}`
}

function getErrorPreview(errorMessage?: string | null) {
  if (!errorMessage) return '-'
  return errorMessage.length > errorPreviewLength
    ? `${errorMessage.slice(0, errorPreviewLength)}...`
    : errorMessage
}

function getItemStatusConfig(status?: number) {
  return taskStatusMap[status ?? 0] ?? { text: '未知', type: 'info' as const }
}

function getTaskStatusConfig(status?: number) {
  const map: Record<number, { text: string; type: 'info' | 'success' | 'warning' | 'danger' }> = {
    0: { text: '待处理', type: 'info' },
    1: { text: '处理中', type: 'warning' },
    2: { text: '已完成', type: 'success' },
    3: { text: '失败', type: 'danger' },
    4: { text: '部分失败', type: 'danger' },
    5: { text: '已取消', type: 'info' },
  }
  return map[status ?? 0] ?? { text: '未知', type: 'info' }
}

function getTaskActionText(action?: number) {
  const map: Record<number, string> = {
    0: '批量处理',
    1: '重新处理',
    2: '重试处理',
  }
  return map[action ?? 0] ?? '未知动作'
}

function getTaskTone(status?: number) {
  if (status === 2) return 'success'
  if (status === 1) return 'warning'
  if (status === 3 || status === 4) return 'danger'
  return 'neutral'
}

function getTaskProgressColor(status?: number) {
  const map: Record<string, string> = {
    success: '#0f766e',
    warning: '#d97706',
    danger: '#dc2626',
    neutral: '#64748b',
  }
  return map[getTaskTone(status)]
}

function getTaskSettledCount(task: DocumentTask) {
  const summary = task.task_summary
  return (summary?.completed ?? 0) + (summary?.failed ?? 0) + (summary?.cancelled ?? 0)
}

function getTaskSuccessPercent(task: DocumentTask) {
  const totalCount = task.total_count || 0
  if (!totalCount) return 0

  const summary = task.task_summary
  const completedCount = summary?.completed ?? 0
  return Math.min(100, Math.round((completedCount / totalCount) * 100))
}

function getTaskProgressPercent(stepProgress?: Record<string, unknown>) {
  if (!stepProgress) return 0
  const steps = ['parsed', 'split', 'embedded', 'indexed']
  const doneCount = steps.filter(step => stepProgress[step] === 'done').length
  return Math.round((doneCount / steps.length) * 100)
}

function getTaskProgressText(stepProgress?: Record<string, unknown>) {
  if (!stepProgress) return '未开始'

  const labels: Record<string, string> = {
    parsed: '已解析',
    split: '已切分',
    embedded: '已向量化',
    indexed: '已入索引',
  }

  const doneSteps = Object.entries(labels)
    .filter(([key]) => stepProgress[key] === 'done')
    .map(([, label]) => label)

  return doneSteps.join(' / ') || '处理中'
}

function formatDateTime(value?: string | null) {
  return value ? formatDate(value) : '-'
}

function goToDetail(documentId: number) {
  router.push(`/home/spaces/${spaceId.value}/documents/${documentId}?kbId=${kbId.value}`)
}

watch([spaceId, kbId], () => {
  page.value = 1
  expandedTaskIds.value = []
  fetchTasks()
})

onMounted(fetchTasks)
</script>

<style scoped>
.document-task-view {
  padding-top: var(--space-2);
  height: 100%;
}

.kb-layout {
  display: flex;
  height: 100%;
}

.kb-content {
  flex: 1;
  min-width: 0;
  padding: var(--space-4) var(--space-5);
  overflow-y: auto;
  background: var(--color-bg);
}

.dashboard-panel,
.task-feed {
  border: 1px solid var(--color-border-light);
  border-radius: 24px;
  background: var(--color-bg-card);
  box-shadow: 0 12px 30px rgba(17, 24, 39, 0.05);
}

.dashboard-panel {
  margin-bottom: 16px;
  padding: 24px;
}

.dashboard-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.refresh-button {
  border-color: var(--color-border);
  background: var(--color-bg-card);
}

.dashboard-panel__eyebrow,
.task-feed__eyebrow {
  margin: 0 0 6px;
  color: var(--color-primary);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.dashboard-panel h1,
.task-feed h2 {
  margin: 0;
  color: var(--color-text);
  font-family: var(--font-display);
}

.dashboard-panel h1 {
  font-size: 30px;
  line-height: 1.1;
}

.dashboard-panel__desc {
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.dashboard-stat {
  position: relative;
  overflow: hidden;
  padding: 18px 18px 16px;
  border-radius: 18px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
}

.dashboard-stat--primary {
  background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
  border-color: transparent;
}

.dashboard-stat::after {
  content: '';
  position: absolute;
  right: -24px;
  bottom: -30px;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.06);
}

.dashboard-stat--primary::after {
  background: rgba(255, 255, 255, 0.12);
}

.dashboard-stat__label,
.dashboard-stat__note {
  position: relative;
  z-index: 1;
  display: block;
  font-size: 12px;
}

.dashboard-stat__label {
  color: var(--color-text-secondary);
}

.dashboard-stat--primary .dashboard-stat__label,
.dashboard-stat--primary .dashboard-stat__note {
  color: rgba(255, 255, 255, 0.78);
}

.dashboard-stat__value {
  position: relative;
  z-index: 1;
  display: block;
  margin: 8px 0 6px;
  color: var(--color-text);
  font-size: 30px;
  line-height: 1;
  font-weight: 700;
}

.dashboard-stat--primary .dashboard-stat__value {
  color: #ffffff;
}

.dashboard-stat__note {
  color: var(--color-text-muted);
}

.task-feed__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  padding: 22px 24px 16px;
  border-bottom: 1px solid var(--color-border-light);
}

.task-feed__hint {
  color: var(--color-text-muted);
  font-size: 13px;
}

.task-feed__body {
  padding: 16px 16px 8px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.task-item {
  position: relative;
  border: 1px solid var(--color-border-light);
  border-radius: 22px;
  background: var(--color-bg-card);
  overflow: hidden;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.task-item:hover {
  transform: translateY(-1px);
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.06);
}

.task-item--expanded {
  box-shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
}

.task-item--success {
  border-color: rgba(16, 185, 129, 0.22);
}

.task-item--warning {
  border-color: rgba(245, 158, 11, 0.26);
}

.task-item--danger {
  border-color: rgba(239, 68, 68, 0.24);
}

.task-item__summary {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border: 0;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.task-item__main {
  min-width: 0;
  flex: 1;
}

.task-item__title-row,
.task-item__meta,
.task-breakdown {
  display: flex;
  gap: 10px;
  align-items: center;
}

.task-item__title-row {
  margin-bottom: 6px;
}

.task-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: var(--color-text-faint);
  box-shadow: 0 0 0 4px rgba(156, 163, 175, 0.14);
}

.task-status-dot--success {
  background: var(--color-success);
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.12);
}

.task-status-dot--warning {
  background: var(--color-warning);
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);
}

.task-status-dot--danger {
  background: var(--color-danger);
  box-shadow: 0 0 0 4px rgba(239, 68, 68, 0.12);
}

.task-id {
  color: var(--color-text);
  font-size: 16px;
  font-weight: 700;
}

.task-action {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 0 9px;
  border-radius: 999px;
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: 11px;
  font-weight: 600;
}

.task-item__meta,
.task-breakdown__item,
.task-item__toggle,
.error-text,
.progress-cell span {
  color: var(--color-text-muted);
  font-size: 12px;
}

.error-cell {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.error-text {
  flex: 1;
  min-width: 0;
  line-height: 1.5;
  overflow: hidden;
  word-break: break-word;
}

.task-breakdown {
  margin-top: 10px;
  flex-wrap: nowrap;
  gap: 12px;
  overflow: hidden;
}

.task-breakdown__item {
  display: inline-flex;
  align-items: center;
  font-weight: 600;
  white-space: nowrap;
  flex-shrink: 0;
}

.task-breakdown__item::before {
  content: '';
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: 999px;
  background: var(--color-text-faint);
  flex-shrink: 0;
}

.task-breakdown__item.is-processing {
  color: var(--color-warning);
}

.task-breakdown__item.is-processing::before {
  background: var(--color-warning);
}

.task-breakdown__item.is-success {
  color: var(--color-success);
}

.task-breakdown__item.is-success::before {
  background: var(--color-success);
}

.task-breakdown__item.is-danger {
  color: var(--color-danger);
}

.task-breakdown__item.is-danger::before {
  background: var(--color-danger);
}

.task-breakdown__item.is-muted {
  color: var(--color-text-muted);
}

.task-breakdown__item.is-muted::before {
  background: var(--color-text-muted);
}

.task-item__side {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
  width: 168px;
  flex-shrink: 0;
}

.task-overview {
  width: 100%;
  padding: 10px 12px;
  border-radius: 14px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
}

.task-overview__label {
  display: block;
  color: var(--color-text-muted);
  font-size: 12px;
}

.task-overview__value {
  display: block;
  margin: 4px 0 8px;
  color: var(--color-text);
  font-size: 22px;
  line-height: 1;
}

.task-overview__meta {
  display: block;
  margin-top: 6px;
  color: var(--color-text-muted);
  font-size: 12px;
}

.task-item__toggle {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  background: var(--color-bg-hover);
  font-weight: 600;
}

.task-item__detail {
  padding: 0 14px 14px;
}

.task-item__notice {
  margin: 0 0 12px;
  padding: 14px 16px;
  border-radius: 16px;
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
}

.task-item__notice p {
  margin: 0;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.task-item__notice p + p {
  margin-top: 6px;
}

.task-item__error {
  color: var(--color-danger);
}

.detail-table {
  width: 100%;
  border: 1px solid var(--color-border-light);
  border-radius: 16px;
  overflow: hidden;
}

.detail-table :deep(.el-table__inner-wrapper::before) {
  display: none;
}

.detail-table :deep(th.el-table__cell) {
  background: var(--color-bg-card-elevated);
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 700;
}

.doc-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.doc-name {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

@media (max-width: 1100px) {
  .dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .kb-content {
    padding: var(--space-3);
  }

  .dashboard-panel__head,
  .task-feed__header,
  .task-item__summary {
    flex-direction: column;
    align-items: flex-start;
  }

  .dashboard-grid {
    grid-template-columns: 1fr;
  }

  .task-item__side {
    align-items: flex-start;
    width: 100%;
  }

  .task-breakdown {
    flex-wrap: wrap;
  }

  .task-overview {
    max-width: 220px;
  }
}
</style>

<!-- 非 scoped：el-tooltip 的 popper 被 teleport 到 body，scoped 样式无法命中 -->
<style>
.task-error-tooltip.el-popper {
  max-width: 420px;
  white-space: normal;
  word-break: break-word;
  line-height: 1.5;
}
</style>
