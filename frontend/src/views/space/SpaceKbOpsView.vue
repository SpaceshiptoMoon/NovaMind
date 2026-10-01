<template>
  <div class="kbops-page">
    <PageHeader
      title="知识运营"
      description="复审建议处置 · 重复内容治理 · 文档价值洞察"
    >
      <template #actions>
        <el-select v-model="kbFilter" placeholder="矛盾扫描知识库" style="width: 190px" clearable>
          <el-option v-for="kb in kbOptions" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <el-button
          type="warning"
          plain
          :loading="scanning"
          :disabled="!kbFilter"
          @click="onScan"
        >
          矛盾检测
        </el-button>
      </template>
    </PageHeader>

    <el-tabs v-model="activeTab" class="kbops-tabs">
      <!-- ===== Tab 1：复审建议（B2/D 人工裁决队列） ===== -->
      <el-tab-pane :label="`复审建议 (${suggestions.length})`" name="suggestions">
        <el-table
          v-loading="loadingSuggestions"
          :data="suggestions"
          class="kbops-table"
          empty-text="没有待处置的建议——新版识别与矛盾检测的产出会出现在这里"
        >
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <el-tag :type="row.suggestion_type === 'contradiction' ? 'danger' : 'warning'" size="small">
                {{ typeLabel(row.suggestion_type) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="涉及文档" min-width="160">
            <template #default="{ row }">
              <span class="doc-ids">#{{ row.old_doc_id ?? '—' }} ↔ #{{ row.new_doc_id ?? '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="判定依据" min-width="280">
            <template #default="{ row }">
              <span class="reason-text" :title="row.reason">{{ row.reason || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="得分" width="90" align="center">
            <template #default="{ row }">
              <span v-if="row.score != null">{{ (row.score / 100).toFixed(0) }}%</span>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                type="primary"
                :loading="resolvingId === row.id"
                @click="onResolve(row, 'accepted')"
              >
                {{ row.suggestion_type === 'new_version' ? '采纳并替换' : '确认矛盾' }}
              </el-button>
              <el-button size="small" :loading="resolvingId === row.id" @click="onResolve(row, 'dismissed')">
                忽略
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ===== Tab 2：重复文档（D1，仅展示） ===== -->
      <el-tab-pane :label="`重复内容 (${duplicates.length})`" name="duplicates">
        <el-alert
          type="info"
          :closable="false"
          show-icon
          class="tab-note"
          title="平台不自动合并重复内容——确认后请通过「采纳并替换」建议流或文档生命周期操作处理"
        />
        <el-table
          v-loading="loadingDuplicates"
          :data="duplicates"
          class="kbops-table"
          empty-text="没有发现重复内容"
        >
          <el-table-column label="重复类型" width="150">
            <template #default="{ row }">
              <el-tag :type="row.group_type === 'exact_hash' ? 'danger' : 'info'" size="small">
                {{ row.group_type === 'exact_hash' ? '完全相同内容' : '同名不同版' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="包含文档" min-width="400">
            <template #default="{ row }">
              <div class="dup-docs">
                <span
                  v-for="doc in row.documents"
                  :key="doc.document_id"
                  class="dup-doc-chip"
                  :class="{ retired: doc.lifecycle_status !== 'active' }"
                >
                  #{{ doc.document_id }} {{ doc.filename }}
                </span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ===== Tab 3：文档价值（D3 贡献统计） ===== -->
      <el-tab-pane label="文档价值" name="value">
        <div class="value-panels">
          <div class="value-panel">
            <div class="panel-title">最常支撑回答（被引用于 AI 回答的次数）</div>
            <el-table
              v-loading="loadingStats"
              :data="supportStats"
              class="kbops-table"
              empty-text="暂无问答引用数据"
            >
              <el-table-column label="文档" min-width="220">
                <template #default="{ row }">
                  <span class="doc-ids">#{{ row.document_id }}</span>
                  <span class="doc-name">{{ docName(row.document_id) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="支撑回答" width="120" align="center">
                <template #default="{ row }">
                  <el-tag type="success" effect="plain" size="small">{{ row.support_count }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div class="value-panel">
            <div class="panel-title">被点击核验（用户点开引用来源核对的次数）</div>
            <el-table
              v-loading="loadingStats"
              :data="clickStats"
              class="kbops-table"
              empty-text="暂无引用点击数据"
            >
              <el-table-column label="文档" min-width="220">
                <template #default="{ row }">
                  <span class="doc-ids">#{{ row.document_id }}</span>
                  <span class="doc-name">{{ docName(row.document_id) }}</span>
                </template>
              </el-table-column>
              <el-table-column label="点击核验" width="120" align="center">
                <template #default="{ row }">
                  <el-tag type="primary" effect="plain" size="small">{{ row.click_count }}</el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
/** 知识运营管理页（kb-ops 前端批次）：建议处置/重复治理/文档价值三面合一 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { spaceApi } from '@/api/space'
import { knowledgeBaseApi, spaceStatsApi } from '@/api/knowledge'
import { documentApi } from '@/api/knowledge/document'
import type {
  KbOpsDuplicateGroup,
  KbOpsSuggestion,
} from '@/api/types'
import PageHeader from '@/components/common/PageHeader.vue'

const route = useRoute()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const activeTab = ref('suggestions')
const resolvingId = ref<number | null>(null)
const scanning = ref(false)

// ===== 复审建议 =====
const suggestions = ref<KbOpsSuggestion[]>([])
const loadingSuggestions = ref(false)

// ===== 重复文档 =====
const duplicates = ref<KbOpsDuplicateGroup[]>([])
const loadingDuplicates = ref(false)

// ===== 文档价值 =====
const loadingStats = ref(false)
const supportStats = ref<Array<{ document_id: number; support_count: number }>>([])
const clickStats = ref<Array<{ document_id: number; click_count: number }>>([])
const docNames = ref<Record<number, string>>({})

// ===== KB 选择（矛盾扫描用） =====
const kbFilter = ref<number | null>(null)
const kbOptions = ref<Array<{ id: number; name: string }>>([])

const TYPE_LABELS: Record<string, string> = {
  new_version: '疑似新版',
  contradiction: '内容矛盾',
}

function typeLabel(t: string): string {
  return TYPE_LABELS[t] ?? t
}

/** 文档名解析（拉建议/重复组里的文档 id 批量查名，失败显示占位） */
function docName(docId: number): string {
  return docNames.value[docId] ?? `文档 ${docId}`
}

async function resolveDocNames() {
  // 知识库级文档查询兜底：逐 KB 拉文档清单建 id→name 映射（量级可控）
  for (const kb of kbOptions.value) {
    try {
      const resp = await documentApi.getDocuments(spaceId.value, kb.id, { limit: 200 })
      for (const d of resp.items) {
        docNames.value[d.id] = d.filename
      }
    } catch {
      // 单 KB 失败跳过（名称缺失仅影响展示）
    }
  }
}

async function loadSuggestions() {
  loadingSuggestions.value = true
  try {
    const data = await spaceStatsApi.getReviewSuggestions(spaceId.value)
    suggestions.value = data.items
  } catch {
    suggestions.value = []
  } finally {
    loadingSuggestions.value = false
  }
}

async function loadDuplicates() {
  loadingDuplicates.value = true
  try {
    const data = await spaceStatsApi.getDuplicates(spaceId.value)
    duplicates.value = data.items
  } catch {
    duplicates.value = []
  } finally {
    loadingDuplicates.value = false
  }
}

async function loadValueStats() {
  loadingStats.value = true
  try {
    const data = await spaceStatsApi.getCitationStats(spaceId.value)
    supportStats.value = data.support_stats
    clickStats.value = data.items
  } catch {
    supportStats.value = []
    clickStats.value = []
  } finally {
    loadingStats.value = false
  }
}

async function onResolve(row: KbOpsSuggestion, action: 'accepted' | 'dismissed') {
  if (action === 'accepted' && row.suggestion_type === 'new_version') {
    // 替换是下线旧文档的实质操作，二次确认
    try {
      await ElMessageBox.confirm(
        `确认以文档 #${row.new_doc_id} 替换 #${row.old_doc_id}？旧文档将下线（不再被检索召回，可恢复）。`,
        '采纳替换建议',
        { confirmButtonText: '确认替换', cancelButtonText: '再想想', type: 'warning' },
      )
    } catch {
      return
    }
  }
  resolvingId.value = row.id
  try {
    const result = await spaceStatsApi.resolveSuggestion(spaceId.value, row.id, action)
    if (action === 'accepted' && row.suggestion_type === 'new_version') {
      ElMessage.success(`已替换：文档 #${result.superseded_doc_id} 已下线`)
    } else if (action === 'accepted') {
      ElMessage.success('已确认矛盾，双方文档 owner 将收到通知')
    } else {
      ElMessage.info('已忽略该建议')
    }
    await loadSuggestions()
  } catch {
    ElMessage.error('处置失败，请重试')
  } finally {
    resolvingId.value = null
  }
}

async function onScan() {
  if (!kbFilter.value) return
  scanning.value = true
  try {
    const result = await spaceStatsApi.runContradictionScan(spaceId.value, kbFilter.value)
    if (result.suggestions_created > 0) {
      ElMessage.success(`检测到 ${result.suggestions_created} 条疑似矛盾，已进入建议队列`)
    } else {
      ElMessage.info('本轮未发现内容矛盾')
    }
    await loadSuggestions()
    activeTab.value = 'suggestions'
  } catch {
    ElMessage.error('矛盾检测失败（需配置 LLM 模型），请稍后重试')
  } finally {
    scanning.value = false
  }
}

onMounted(async () => {
  // KB 选项（矛盾扫描下拉 + 文档名解析）
  try {
    const kbs = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    kbOptions.value = kbs.items.map((k) => ({ id: k.id, name: k.name }))
  } catch {
    kbOptions.value = []
  }
  void spaceApi.getSpaces().catch(() => null) // 预热空间权限（401 会在全局拦截器处理）
  await Promise.all([loadSuggestions(), loadDuplicates(), loadValueStats()])
  await resolveDocNames()
})
</script>

<style scoped>
.kbops-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.kbops-tabs {
  min-width: 0;
}

.kbops-table {
  width: 100%;
}

.tab-note {
  margin-bottom: 12px;
}

.reason-text {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text-secondary);
}

.doc-ids {
  color: var(--color-text-muted);
  font-family: monospace;
  flex-shrink: 0;
}

.doc-name {
  margin-left: 8px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--color-text);
}

.dup-docs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
}

.dup-doc-chip {
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  background: var(--color-bg-hover);
  color: var(--color-text-secondary);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dup-doc-chip.retired {
  text-decoration: line-through;
  opacity: 0.6;
}

.value-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: 8px;
}

@media (max-width: 900px) {
  .value-panels {
    grid-template-columns: 1fr;
  }
}
</style>
