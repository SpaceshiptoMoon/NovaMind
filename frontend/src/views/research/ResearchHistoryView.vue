<template>
  <div class="research-history-view">
    <!-- 页面标题 -->
    <div class="page-header">
      <div class="page-header-left">
        <el-button text @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          返回研究
        </el-button>
        <el-divider direction="vertical" />
        <h2>研究历史</h2>
      </div>
      <router-link :to="`/home/research/${spaceId}`">
        <el-button type="primary">
          <el-icon><Plus /></el-icon>
          新建研究
        </el-button>
      </router-link>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-select v-model="statusFilter" placeholder="状态筛选" clearable style="width: 140px" @change="fetchData">
        <el-option label="全部" value="" />
        <el-option label="进行中" value="running" />
        <el-option label="已完成" value="completed" />
        <el-option label="失败" value="failed" />
      </el-select>
    </div>

    <!-- 研究列表 -->
    <el-table :data="researchStore.history" v-loading="loading" stripe>
      <el-table-column prop="query" label="研究问题" min-width="250">
        <template #default="{ row }">
          <div class="query-cell">
            <span class="query-text">{{ row.query }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="research_mode" label="模式" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="getModeType(row.research_mode)" size="small">
            {{ getModeText(row.research_mode) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <StatusTag :status="row.status" :status-map="researchStatusMap" size="small" />
        </template>
      </el-table-column>
      <el-table-column label="耗时" width="100" align="center">
        <template #default="{ row }">
          {{ row.stats?.elapsed_seconds ? `${row.stats.elapsed_seconds}s` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="来源数" width="90" align="center">
        <template #default="{ row }">
          {{ row.stats?.sources_count || '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button type="primary" link size="small" @click="handleView(row)">
            查看报告
          </el-button>
          <el-button type="danger" link size="small" @click="handleDelete(row)">
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <Pagination
      :page="currentPage"
      :page-size="pageSize"
      :total="researchStore.total"
      :page-sizes="[10, 20, 50]"
      @update:page="(p: number) => { currentPage = p; fetchData() }"
      @update:page-size="(s: number) => { pageSize = s; currentPage = 1; fetchData() }"
    />

    <!-- 报告详情弹窗 -->
    <el-dialog v-model="detailVisible" title="研究报告" width="700px" top="5vh">
      <div v-if="detailData" class="detail-content">
        <div class="detail-meta">
          <span>问题: {{ detailData.query }}</span>
          <span>模式: {{ getModeText(detailData.research_mode) }}</span>
          <span>耗时: {{ detailData.stats?.elapsed_seconds ? `${detailData.stats.elapsed_seconds}s` : '-' }}</span>
        </div>

        <div v-if="detailData.search_summary?.sources?.length" class="detail-sources">
          <h4>关键来源</h4>
          <el-tag
            v-for="source in detailData.search_summary.sources"
            :key="source"
            size="small"
            type="info"
          >
            {{ source }}
          </el-tag>
        </div>

        <div class="detail-report">
          <h4>报告内容</h4>
          <div class="report-text">{{ detailData.final_report || '暂无报告内容' }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, ArrowLeft } from '@element-plus/icons-vue'
import { useResearchStore } from '@/stores/research'
import { researchApi } from '@/api/research'
import StatusTag from '@/components/common/StatusTag.vue'
import Pagination from '@/components/common/Pagination.vue'
import type { Research } from '@/api/types'

const route = useRoute()
const router = useRouter()
const researchStore = useResearchStore()

const spaceId = computed(() => Number(route.params.spaceId))

const loading = ref(false)
const statusFilter = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const detailVisible = ref(false)
const detailData = ref<Research | null>(null)

// 模式映射
const modeMap: Record<string, { text: string; type: string }> = {
  quick: { text: '快速', type: 'info' },
  standard: { text: '标准', type: '' },
  deep: { text: '深度', type: 'warning' },
}

function getModeText(mode: string): string {
  return modeMap[mode]?.text || mode
}

function getModeType(mode: string): string {
  return modeMap[mode]?.type || 'info'
}

// 状态映射
const researchStatusMap: Record<string, { text: string; type: 'success' | 'warning' | 'danger' | 'info' | 'primary' }> = {
  pending: { text: '等待中', type: 'info' },
  running: { text: '进行中', type: 'warning' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
  cancelled: { text: '已取消', type: 'info' },
}

function formatDate(date: string): string {
  try {
    return new Date(date).toLocaleDateString('zh-CN') + ' ' +
      new Date(date).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return '-'
  }
}

function goBack() {
  router.push(`/home/research/${spaceId.value}`)
}

async function fetchData() {
  loading.value = true
  try {
    await researchStore.fetchHistory(spaceId.value, {
      limit: pageSize.value,
      offset: (currentPage.value - 1) * pageSize.value,
      status: statusFilter.value || undefined,
    })
  } catch {
    ElMessage.error('获取研究历史失败')
  } finally {
    loading.value = false
  }
}

async function handleView(row: Research) {
  try {
    detailData.value = await researchApi.getResearchDetail(spaceId.value, row.session_id)
  } catch {
    detailData.value = row
  }
  detailVisible.value = true
}

async function handleDelete(row: Research) {
  try {
    await ElMessageBox.confirm(
      `确定要删除研究记录 "${row.query.slice(0, 30)}..." 吗？`,
      '提示',
      {
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    await researchStore.deleteResearch(spaceId.value, row.session_id)
    ElMessage.success('已删除')
  } catch {
    // 取消
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style scoped>
.research-history-view {
  padding: 20px;
  max-width: 1100px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #F0EDEA;
}

.page-header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: #1A1A1A;
}

.filter-bar {
  margin-bottom: 16px;
}

.query-cell {
  display: flex;
  align-items: center;
}

.query-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #1A1A1A;
}

.detail-meta {
  display: flex;
  gap: 24px;
  margin-bottom: 16px;
  font-size: 13px;
  color: #8C8C8C;
}

.detail-sources {
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #F0EDEA;
}

.detail-sources h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: #1A1A1A;
}

.detail-sources .el-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}

.detail-report h4 {
  margin: 0 0 12px;
  font-size: 14px;
  color: #1A1A1A;
}

.report-text {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.8;
  max-height: 500px;
  overflow-y: auto;
  padding: 16px;
  background: #F0EDEA;
  border-radius: 8px;
  border: 1px solid #F0EDEA;
  font-size: 14px;
  color: #1A1A1A;
}
</style>
