<template>
  <el-breadcrumb separator="/" class="breadcrumb-nav">
    <el-breadcrumb-item :to="{ path: spaceId ? `/home/spaces/${spaceId}/knowledge-bases` : `/home/spaces` }">
      空间
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="spaceId" :to="{ path: `/home/spaces/${spaceId}/knowledge-bases` }">
      {{ spaceName }}
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="kbId" :to="kbLink">
      知识库
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="showDocuments && kbId">
      文档
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="moduleLabel">
      {{ moduleLabel }}
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="docName">
      {{ docName }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useSpaceStore } from '@/stores/space'

const props = defineProps<{
  kbName?: string
  docName?: string
}>()

const route = useRoute()
const spaceStore = useSpaceStore()

const spaceId = computed(() => String(route.params.id ?? ''))
const kbId = computed(() => {
  if (route.params.kbId) return String(route.params.kbId)
  if (route.query.kbId) return String(route.query.kbId)
  return ''
})

const spaceName = computed(() => spaceStore.currentSpace?.name || '知识空间')
const kbLink = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases`)
const showDocuments = computed(() => !props.docName && (route.name === 'Documents' || route.name === 'DocumentDetail'))
const moduleLabel = computed(() => {
  const name = route.name
  if (name === 'Search') return '知识搜索'
  if (name === 'SpaceSettings') return '空间设置'
  if (name === 'KbEvaluation') return '评估'
  if (name === 'DocumentTasks') return '任务列表'
  return ''
})

onMounted(async () => {
  if (spaceId.value && !spaceStore.currentSpace) {
    try {
      await spaceStore.fetchSpace(Number(spaceId.value))
    } catch {
      // ignore breadcrumb fetch failure
    }
  }
})
</script>

<style scoped>
.breadcrumb-nav {
  font-size: var(--text-sm);
  line-height: 1;
}

.breadcrumb-nav :deep(.el-breadcrumb__inner) {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  transition: color var(--transition-fast);
  padding: 2px 0;
}

.breadcrumb-nav :deep(.el-breadcrumb__inner.is-link) {
  font-weight: var(--weight-normal);
  color: var(--color-text-muted);
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

.breadcrumb-nav :deep(.el-breadcrumb__inner.is-link:hover) {
  color: var(--color-primary);
}

.breadcrumb-nav :deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--color-text-secondary);
  font-weight: var(--weight-medium);
}

.breadcrumb-nav :deep(.el-breadcrumb__separator) {
  color: var(--color-border);
  margin: 0 2px;
  font-weight: var(--weight-normal);
}
</style>
