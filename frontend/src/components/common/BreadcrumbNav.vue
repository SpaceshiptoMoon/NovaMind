<template>
  <el-breadcrumb separator="/" class="breadcrumb-nav">
    <el-breadcrumb-item :to="{ path: `/home/spaces/${spaceId}/knowledge-bases` }">
      返回
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="kbName" :to="kbLink">
      {{ kbName }}
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="showDocuments && kbName">
      文档
    </el-breadcrumb-item>
    <el-breadcrumb-item v-if="docName">
      {{ docName }}
    </el-breadcrumb-item>
  </el-breadcrumb>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps<{
  kbName?: string
  docName?: string
}>()

const route = useRoute()

const spaceId = computed(() => String(route.params.id ?? ''))
const kbId = computed(() => {
  if (route.params.kbId) return String(route.params.kbId)
  if (route.query.kbId) return String(route.query.kbId)
  return ''
})

const kbLink = computed(() => `/home/spaces/${spaceId.value}/knowledge-bases/${kbId.value}/documents`)
const showDocuments = computed(() => !props.docName && (route.name === 'Documents' || route.name === 'DocumentDetail'))
</script>

<style scoped>
.breadcrumb-nav {
  font-size: 12px;
  line-height: 1;
}

:deep(.el-breadcrumb__inner) {
  font-size: 12px;
  color: #8C8C8C;
}

:deep(.el-breadcrumb__inner.is-link) {
  font-weight: 400;
  color: #8C8C8C;
}

:deep(.el-breadcrumb__inner.is-link:hover) {
  color: #4285F4;
}

:deep(.el-breadcrumb__item:last-child .el-breadcrumb__inner) {
  color: #1A1A1A;
  font-weight: 500;
}
</style>
