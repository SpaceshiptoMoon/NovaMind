<template>
  <div class="search-bar">
    <el-input
      v-model="searchValue"
      :placeholder="placeholder"
      :clearable="clearable"
      :disabled="disabled"
      @keyup.enter="handleSearch"
      @clear="handleClear"
    >
      <template #prefix>
        <el-icon><Search /></el-icon>
      </template>
      <template #append v-if="showButton">
        <el-button :icon="Search" @click="handleSearch" />
      </template>
    </el-input>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Search } from '@element-plus/icons-vue'

interface Props {
  modelValue?: string
  placeholder?: string
  clearable?: boolean
  disabled?: boolean
  showButton?: boolean
  debounce?: number
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  placeholder: '请输入关键词搜索',
  clearable: true,
  disabled: false,
  showButton: false,
  debounce: 300,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  search: [value: string]
  clear: []
}>()

const searchValue = ref(props.modelValue)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.modelValue,
  (val) => {
    searchValue.value = val
  },
)

watch(searchValue, (val) => {
  emit('update:modelValue', val)

  if (props.debounce > 0) {
    if (debounceTimer) {
      clearTimeout(debounceTimer)
    }
    debounceTimer = setTimeout(() => {
      emit('search', val)
    }, props.debounce)
  }
})

const handleSearch = () => {
  if (debounceTimer) {
    clearTimeout(debounceTimer)
  }
  emit('search', searchValue.value)
}

const handleClear = () => {
  emit('clear')
}
</script>

<style scoped>
.search-bar {
  display: inline-block;
  width: 100%;
}
</style>
