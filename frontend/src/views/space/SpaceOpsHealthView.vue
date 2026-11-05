<template>
  <div class="ops-health" v-loading="loading">
    <!-- 生命周期统计条 -->
    <div class="ops-panel">
      <div class="panel-title">文档生命周期</div>
      <p class="panel-desc">检索默认只召回 active；superseded/archived 为退役态（可恢复）</p>
      <div class="lifecycle-grid">
        <div class="life-block">
          <span class="life-num">{{ overview?.documents.active ?? '—' }}</span>
          <span class="life-label">生效中 active</span>
        </div>
        <div class="life-block">
          <span class="life-num">{{ overview?.documents.superseded ?? '—' }}</span>
          <span class="life-label">被替代 superseded</span>
        </div>
        <div class="life-block">
          <span class="life-num">{{ overview?.documents.archived ?? '—' }}</span>
          <span class="life-label">已归档 archived</span>
        </div>
        <div class="life-block">
          <span class="life-num">{{ overview?.documents.draft ?? '—' }}</span>
          <span class="life-label">草稿 draft</span>
        </div>
        <div class="life-block life-total">
          <span class="life-num">{{ overview?.documents.total ?? '—' }}</span>
          <span class="life-label">合计 · {{ overview?.kb_count ?? 0 }} 个知识库</span>
        </div>
      </div>
    </div>

    <!-- 重复内容 -->
    <div class="ops-panel">
      <div class="panel-head">
        <div class="panel-head-text">
          <div class="panel-title">重复内容</div>
          <p class="panel-desc">仅展示数据面；处置走待办队列的建议流，平台不自动合并</p>
        </div>
      </div>
      <el-empty v-if="!duplicateGroups.length" description="未发现重复内容" :image-size="64" />
      <div v-else class="dup-list">
        <div v-for="(group, i) in duplicateGroups" :key="i" class="dup-card">
          <div class="dup-head">
            <el-tag
              :type="group.group_type === 'exact_hash' ? 'danger' : 'info'"
              size="small"
              effect="plain"
            >
              {{ group.group_type === 'exact_hash' ? '完全相同内容' : '同名不同版本' }}
            </el-tag>
            <span class="dup-key" :title="group.key">{{ group.key }}</span>
            <span class="dup-count">{{ group.documents.length }} 份</span>
          </div>
          <div class="dup-docs">
            <span
              v-for="doc in group.documents"
              :key="doc.document_id"
              class="dup-doc"
              :class="{ 'dup-doc--retired': doc.lifecycle_status !== 'active' }"
              :title="`${doc.filename}（${doc.lifecycle_status}）`"
            >
              {{ doc.filename }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- 文档价值三面板 -->
    <div class="value-grid">
      <div class="ops-panel">
        <div class="panel-title">最常支撑回答</div>
        <el-empty v-if="!supportTop.length" description="暂无引用数据" :image-size="64" />
        <ol v-else class="rank-list">
          <li v-for="row in supportTop" :key="row.document_id" class="rank-item">
            <span class="rank-name" :title="docName(row.document_id)">
              {{ docName(row.document_id) }}
            </span>
            <span class="rank-num">{{ row.support_count }} 次</span>
          </li>
        </ol>
      </div>
      <div class="ops-panel">
        <div class="panel-title">被点击核验最多</div>
        <el-empty v-if="!clickTop.length" description="暂无点击数据" :image-size="64" />
        <ol v-else class="rank-list">
          <li v-for="row in clickTop" :key="row.document_id" class="rank-item">
            <span class="rank-name" :title="docName(row.document_id)">
              {{ docName(row.document_id) }}
            </span>
            <span class="rank-num">{{ row.click_count }} 次</span>
          </li>
        </ol>
      </div>
      <div class="ops-panel">
        <div class="panel-title">零引用候选</div>
        <p class="panel-desc">从未被引用或点击的文档，治理候选（下线/合并前先人工确认）</p>
        <el-empty
          v-if="!zeroRefDocs.length"
          description="暂无零引用文档或名单还在加载"
          :image-size="64"
        />
        <ol v-else class="rank-list">
          <li v-for="doc in zeroRefDocs" :key="doc.id" class="rank-item">
            <span class="rank-name" :title="doc.filename">{{ doc.filename }}</span>
            <span class="rank-num">{{ kbLabel(doc.kb_id) }}</span>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 资产健康页：生命周期统计 → 重复内容 → 文档价值三榜（支撑/点击/零引用）。
 *
 * 零引用候选 = 空间文档全集（docNames 兜底法拉到的部分）减去被引用集合——
 * 覆盖受 200/KB 采样上限约束，只作治理线索不作精确审计。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { documentApi, knowledgeBaseApi, spaceStatsApi } from '@/api/knowledge'
import { useOpsDocNames } from '@/composables/useOpsDocNames'
import type { KbOpsOverview, KbOpsDuplicates, KbOpsCitationStats } from '@/api/types'

const route = useRoute()
const spaceId = computed(() => parseInt(String(route.params.id), 10))

const loading = ref(false)
const overview = ref<KbOpsOverview | null>(null)
const duplicates = ref<KbOpsDuplicates | null>(null)
const citationStats = ref<KbOpsCitationStats | null>(null)
const kbNames = ref<Record<number, string>>({})
const { resolveDocNames, docName } = useOpsDocNames(spaceId)

const duplicateGroups = computed(() => duplicates.value?.items ?? [])
const supportTop = computed(() => (citationStats.value?.support_stats ?? []).slice(0, 10))
const clickTop = computed(() => (citationStats.value?.items ?? []).slice(0, 10))

/** 零引用候选：文档全集减去（支撑∪点击）已引用集合，取前 10。 */
const zeroRefDocs = computed(() => {
  const cited = new Set<number>([
    ...(citationStats.value?.support_stats ?? []).map((s) => s.document_id),
    ...(citationStats.value?.items ?? []).map((s) => s.document_id),
  ])
  const allDocs = docCache.value
  return allDocs.filter((doc) => !cited.has(doc.id)).slice(0, 10)
})

// docNames 只存 id→名映射，零引用列表还需要 kb_id——缓存完整文档行
const docCache = ref<Array<{ id: number; filename: string; kb_id: number }>>([])

function kbLabel(kbId: number): string {
  return kbNames.value[kbId] ?? `KB ${kbId}`
}

onMounted(async () => {
  loading.value = true
  try {
    const [ov, dup, cit] = await Promise.all([
      spaceStatsApi.getOpsOverview(spaceId.value),
      spaceStatsApi.getDuplicates(spaceId.value),
      spaceStatsApi.getCitationStats(spaceId.value, { limit: 10 }),
    ])
    overview.value = ov
    duplicates.value = dup
    citationStats.value = cit
  } catch (e) {
    console.warn('[SpaceOpsHealth] 加载失败', e)
  } finally {
    loading.value = false
  }
  // 文档全集（名称解析 + 零引用候选）与 KB 名映射
  try {
    const kbs = await knowledgeBaseApi.getKnowledgeBases(spaceId.value)
    kbNames.value = Object.fromEntries((kbs.items ?? []).map((k) => [k.id, k.name]))
    const lists = await Promise.all(
      (kbs.items ?? []).map((kb) =>
        documentApi
          .getDocuments(spaceId.value, kb.id, { limit: 200 })
          .then((r) => r.items ?? [])
          .catch(() => []),
      ),
    )
    docCache.value = lists.flat()
    await resolveDocNames()
  } catch {
    docCache.value = []
  }
})
</script>

<style scoped>
.ops-health {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.ops-panel {
  background: var(--ops-panel);
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 14px 16px;
  min-width: 0;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.panel-head-text {
  min-width: 0;
}

.panel-title {
  font-family: var(--ops-serif);
  font-size: 15px;
  font-weight: 400;
  letter-spacing: 0.03em;
  color: var(--color-text);
  margin-bottom: 4px;
}

.panel-desc {
  margin: 0 0 10px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.lifecycle-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

/* 生命周期统计 = 注线式数字列（无框，竖发丝线分隔），与小 KPI 行同语言 */
.life-block {
  padding: 4px 14px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.life-block + .life-block {
  border-left: 1px solid var(--ops-line);
}

.life-total {
  background: var(--ops-panel-hover);
  margin: -4px -14px;
  padding: 4px 14px;
  border-left: 1px solid var(--ops-line);
}

.life-num {
  font-size: 24px;
  font-weight: 600;
  color: var(--color-text);
  font-variant-numeric: tabular-nums;
}

.life-label {
  font-size: 11px;
  color: var(--color-text-muted);
}

.dup-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.dup-card {
  border: 1px solid var(--ops-line);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dup-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.dup-key {
  font-size: 12px;
  color: var(--color-text-faint);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}

.dup-count {
  font-size: 12px;
  color: var(--color-text-secondary);
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.dup-docs {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.dup-doc {
  font-size: 12px;
  color: var(--color-text);
  background: var(--color-bg-hover);
  border-radius: 6px;
  padding: 3px 8px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dup-doc--retired {
  color: var(--color-text-faint);
  text-decoration: line-through;
}

.value-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.rank-list {
  list-style: none;
  margin: 0;
  padding: 0;
  counter-reset: rank;
  display: flex;
  flex-direction: column;
}

.rank-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 7px 0;
  border-bottom: 1px solid var(--ops-line);
  font-size: 13px;
}

.rank-item:last-child {
  border-bottom: none;
}

.rank-item::before {
  counter-increment: rank;
  content: counter(rank);
  font-size: 11px;
  color: var(--color-text-faint);
  width: 16px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.rank-name {
  color: var(--color-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.rank-num {
  color: var(--color-text-secondary);
  font-size: 12px;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

@media (max-width: 900px) {
  .lifecycle-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  /* 两列下第三格是第二行行首：去左线补横线 */
  .life-block:nth-child(3),
  .life-block:nth-child(5) {
    border-left: none;
    border-top: 1px solid var(--ops-line);
    padding-top: 10px;
  }

  .value-grid {
    grid-template-columns: 1fr;
  }
}
</style>
