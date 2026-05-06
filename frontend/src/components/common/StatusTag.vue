<template>
  <el-tag :type="tagType" :size="size" :effect="effect">
    {{ displayText }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

interface StatusConfig {
  text: string
  type: 'success' | 'warning' | 'danger' | 'info' | 'primary'
}

type StatusType = 'active' | 'inactive' | 'pending' | 'processing' | 'completed' | 'failed' | 'custom'

interface Props {
  status: StatusType | string
  text?: string
  size?: 'large' | 'default' | 'small'
  effect?: 'dark' | 'light' | 'plain'
  statusMap?: Record<string, StatusConfig>
}

const props = withDefaults(defineProps<Props>(), {
  size: 'default',
  effect: 'light',
  statusMap: () => ({}),
})

const defaultStatusMap: Record<string, StatusConfig> = {
  active: { text: '启用', type: 'success' },
  inactive: { text: '禁用', type: 'danger' },
  pending: { text: '待处理', type: 'warning' },
  processing: { text: '处理中', type: 'primary' },
  completed: { text: '已完成', type: 'success' },
  failed: { text: '失败', type: 'danger' },
}

const mergedStatusMap = computed(() => ({
  ...defaultStatusMap,
  ...props.statusMap,
}))

const statusConfig = computed(() => {
  return mergedStatusMap.value[props.status] || { text: props.status, type: 'info' as const }
})

const tagType = computed(() => statusConfig.value.type)

const displayText = computed(() => props.text || statusConfig.value.text)
</script>
