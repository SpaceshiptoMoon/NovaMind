<template>
  <div class="model-fan">
    <el-select
      :model-value="innerValue || defaultModelName"
      placeholder="选择模型"
      size="small"
      class="model-select"
      popper-class="model-select-popper"
      @update:model-value="select"
    >
      <el-option-group v-if="llmModels.length" label="LLM 文本模型">
        <el-option
          v-for="item in llmModels"
          :key="item.name"
          :label="item.name"
          :value="item.name"
        />
      </el-option-group>
      <el-option-group v-if="vlmModels.length" label="VLM 视觉模型">
        <el-option
          v-for="item in vlmModels"
          :key="item.name"
          :label="item.name"
          :value="item.name"
        />
      </el-option-group>
    </el-select>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  modelValue?: string
  models: Record<string, { max_tokens: number; temperature: number; top_p: number; model_type: string }>
  defaultModelName?: string
}>(), {
  modelValue: '',
  models: () => ({}),
  defaultModelName: '',
})

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const innerValue = computed(() => props.modelValue)

const llmModels = computed(() =>
  Object.entries(props.models)
    .filter(([, v]) => v.model_type !== 'vlm')
    .map(([name]) => ({ name })),
)

const vlmModels = computed(() =>
  Object.entries(props.models)
    .filter(([, v]) => v.model_type === 'vlm')
    .map(([name]) => ({ name })),
)

function select(value: string) {
  emit('update:modelValue', value)
}
</script>

<style scoped>
.model-fan {
  display: inline-flex;
  align-items: center;
}
.model-select {
  width: 220px;
}
</style>

<style>
.model-select-popper {
  min-width: 220px !important;
}
</style>
