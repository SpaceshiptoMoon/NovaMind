<template>
  <div class="document-task-view">
    <div class="kb-layout">
      <KbSidebar :nav-items="kbNavItems" />

      <div class="kb-content">
        <div class="section-head">
          <div>
            <h3 class="section-title">任务列表</h3>
            <p class="section-desc">一条任务记录代表一次用户触发的处理动作，展开查看各文档子项状态。</p>
          </div>
          <el-button text @click="fetchTasks">刷新</el-button>
        </div>

        <div v-loading="loading" class="task-wrap">
          <el-empty v-if="tasks.length === 0" description="暂无任务" />
          <el-collapse v-else v-model="expandedTaskIds">
            <el-collapse-item
              v-for="task in tasks"
              :key="task.id"
              :name="String(task.id)"
              class="task-item"
            >
              <template #title>
                <div class="task-title">
                  <div class="task-main">
                    <span class="task-id">任务 #{{ task.id }}</span>
                    <el-tag :type="getTaskStatusConfig(task.status).type" effect="plain" size="small">
                      {{ getTaskStatusConfig(task.status).text }}
                    </el-tag>
                    <span class="task-action">{{ getTaskActionText(task.action) }}</span>
                  </div>
                  <div class="task-meta">
                    <span>{{ task.total_count }} 个文档</span>
                    <span>{{ formatDate(task.created_at) }}</span>
                  </div>
                </div>
              </template>

              <div class="task-summary">
                <div class="summary-chip">待处理 {{ task.task_summary?.pending ?? 0 }}</div>
                <div class="summary-chip">处理中 {{ task.task_summary?.processing ?? 0 }}</div>
                <div class="summary-chip">完成 {{ task.task_summary?.completed ?? 0 }}</div>
                <div class="summary-chip">失败 {{ task.task_summary?.failed ?? 0 }}</div>
                <div class="summary-chip">取消 {{ task.task_summary?.cancelled ?? 0 }}</div>
              </div>

              <div v-if="task.note" class="task-note">{{ task.note }}</div>
              <div v-if="task.error_message" class="task-error">{{ task.error_message }}</div>

              <el-table :data="task.items" size="small" class="task-table">
                <el-table-column prop="document_id" label="文档ID" width="88" />
                <el-table-column label="文件" min-width="200">
                  <template #default="{ row }">
                    <div class="task-name-cell">
                      <span>{{ getTaskDocumentName(row.document_id, row.pipeline_result) }}</span>
                      <el-button text size="small" @click="goToDetail(row.document_id)">详情</el-button>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="110" align="center">
                  <template #default="{ row }">
                    <el-tag :type="getItemStatusConfig(row.status).type" effect="plain" size="small">
                      {{ getItemStatusConfig(row.status).text }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="进度" min-width="220">
                  <template #default="{ row }">
                    <div class="progress-cell">
                      <el-progress :percentage="getTaskProgressPercent(row.step_progress)" :stroke-width="6" />
                      <span class="progress-text">{{ getTaskProgressText(row.step_progress) }}</span>
                    </div>
                  </template>
                </el-table-column>
                <el-table-column prop="retry_count" label="重试" width="70" align="center" />
                <el-table-column label="错误信息" min-width="220">
                  <template #default="{ row }">
                    <span class="task-error-text">{{ row.error_message || '-' }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </el-collapse-item>
          </el-collapse>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, Document, List, Search } from '@element-plus/icons-vue'

import { documentApi } from '@/api/document'
import type { DocumentTask } from '@/api/types'
import KbSidebar from '@/components/common/KbSidebar.vue'
import type { KbNavItem } from '@/components/common/KbSidebar.vue'
import { taskStatusMap } from '@/utils/document'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()

const spaceId = computed(() => Number(route.params.id))
const kbId = computed(() => Number(route.params.kbId))

const kbNavItems = computed<KbNavItem[]>(() => {
  const sid = spaceId.value
  const kid = kbId.value
  return [
    { label: '文档管理', to: `/home/spaces/${sid}/knowledge-bases/${kid}/documents`, route: 'Documents', active: route.name === 'Documents' || route.name === 'DocumentDetail', icon: Document },
    { label: '任务列表', to: `/home/spaces/${sid}/knowledge-bases/${kid}/tasks`, route: 'DocumentTasks', active: route.name === 'DocumentTasks', icon: List },
    { label: '搜索', to: `/home/spaces/${sid}/search?kbId=${kid}`, route: 'Search', active: route.name === 'Search', icon: Search },
    { label: '测评', to: `/home/spaces/${sid}/knowledge-bases/${kid}/evaluation`, route: 'KbEvaluation', active: route.name === 'KbEvaluation', icon: DataAnalysis },
  ]
})

const loading = ref(false)
const tasks = ref<DocumentTask[]>([])
const expandedTaskIds = ref<string[]>([])

async function fetchTasks() {
  loading.value = true
  try {
    const data = await documentApi.getDocumentTasksOverview(spaceId.value, kbId.value, {
      skip: 0,
      limit: 50,
    })
    tasks.value = data.items || []
  } finally {
    loading.value = false
  }
}

function getTaskDocumentName(documentId: number, pipelineResult?: Record<string, unknown>) {
  if (pipelineResult && typeof pipelineResult.filename === 'string') return pipelineResult.filename
  return `文档 ${documentId}`
}

function getItemStatusConfig(status: number | undefined) {
  return taskStatusMap[status ?? 0] ?? { text: '未知', type: 'info' as const }
}

function getTaskStatusConfig(status: number | undefined) {
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

function getTaskActionText(action: number | undefined) {
  const map: Record<number, string> = {
    0: '批量处理',
    1: '重新处理',
    2: '重试处理',
  }
  return map[action ?? 0] ?? '未知动作'
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
  return Object.entries(labels)
    .filter(([key]) => stepProgress[key] === 'done')
    .map(([, label]) => label)
    .join(' / ') || '处理中'
}

function goToDetail(documentId: number) {
  router.push(`/home/spaces/${spaceId.value}/documents/${documentId}?kbId=${kbId.value}`)
}

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
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-3);
}

.section-title {
  margin: 0 0 var(--space-1);
  font-size: var(--text-lg);
  color: var(--color-text);
}

.section-desc {
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.task-wrap {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-xs);
  padding: var(--space-2);
}

.task-item {
  border-radius: var(--radius-md);
  overflow: hidden;
}

.task-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-4);
  width: 100%;
  padding-right: var(--space-3);
}

.task-main {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.task-id {
  font-weight: var(--weight-semibold);
  color: var(--color-text);
}

.task-action,
.task-meta {
  color: var(--color-text-muted);
  font-size: var(--text-sm);
}

.task-meta {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.task-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.summary-chip {
  padding: 6px 10px;
  border-radius: 999px;
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.task-note {
  margin-bottom: var(--space-2);
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
}

.task-error {
  margin-bottom: var(--space-3);
  color: var(--color-danger);
  font-size: var(--text-sm);
}

.task-table {
  border-top: 1px solid var(--color-border-light);
}

.task-name-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2);
}

.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.progress-text,
.task-error-text {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}
</style>
