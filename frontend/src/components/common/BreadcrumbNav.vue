<template>
  <el-breadcrumb separator="/" class="breadcrumb-nav">
    <el-breadcrumb-item :to="{ path: `/home/spaces` }">
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

const spaceName = computed(() => {
  return spaceStore.currentSpace?.name || '知识空间'
})

const kbLink = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases/${kbId.value}/documents`)
const showDocuments = computed(() => !props.docName && (route.name === 'Documents' || route.name === 'DocumentDetail'))

onMounted(async () => {
  if (spaceId.value && !spaceStore.currentSpace) {
    try {
      await spaceStore.fetchSpace(Number(spaceId.value))
    } catch {
      // 获取空间名称失败不影响导航
    }
  }
})
</script>

<style scoped>
.breadcrumb-nav {
  font-size: 13px;
  line-height: 1;
}

:deep(.el-breadcrumb__inner) {
  font-size: 13px;
  color: var(--color-text-muted, #8C8C8C);
  transition: color 0.2s;
}

:deep(.el-breadcrumb__inner.is-link) {
  font-weight: 400;
  color: var(--color-text-muted, #8C8C8C);
  display: inline-flex;
  align-items: center;
  gap: 3px;
}

:deep(.el-breadcrumb__inner.is-link:hover) {
  color: var(--color-primary, #4285F4);
}

:deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: var(--color-text, #1A1A1A);
  font-weight: 500;
}

:deep(.el-breadcrumb__separator) {
  color: var(--color-text-muted, #C0C4CC);
}
</style>
