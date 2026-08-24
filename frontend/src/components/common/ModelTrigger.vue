<template>
  <el-popover
    trigger="click"
    placement="top-start"
    :width="260"
    popper-class="model-trigger-popper"
    :show-arrow="false"
    :offset="6"
    @show="visible = true"
    @hide="visible = false"
  >
    <template #reference>
      <button class="model-trigger" type="button" :title="currentLabel">
        <span class="model-trigger-icon">
          <el-icon :size="14"><MagicStick /></el-icon>
        </span>
        <span class="model-trigger-label">{{ currentLabel }}</span>
        <el-icon :size="12" class="model-trigger-arrow" :class="{ open: visible }">
          <ArrowDown />
        </el-icon>
      </button>
    </template>

    <div class="model-menu">
      <!-- Auto：跟随智能体默认配置 -->
      <button
        class="model-menu-item"
        :class="{ active: !modelValue }"
        type="button"
        @click="choose('')"
      >
        <span class="model-menu-name">Auto</span>
        <span class="model-menu-desc">跟随智能体配置</span>
        <el-icon v-if="!modelValue" :size="14" class="model-menu-check"><Check /></el-icon>
      </button>

      <template v-if="llmModels.length">
        <div class="model-menu-group">LLM 文本模型</div>
        <button
          v-for="m in llmModels"
          :key="m.name"
          class="model-menu-item"
          :class="{ active: modelValue === m.name }"
          type="button"
          @click="choose(m.name)"
        >
          <span class="model-menu-name">{{ m.name }}</span>
          <el-icon v-if="modelValue === m.name" :size="14" class="model-menu-check"><Check /></el-icon>
        </button>
      </template>

      <template v-if="vlmModels.length">
        <div class="model-menu-group">VLM 视觉模型</div>
        <button
          v-for="m in vlmModels"
          :key="m.name"
          class="model-menu-item"
          :class="{ active: modelValue === m.name }"
          type="button"
          @click="choose(m.name)"
        >
          <span class="model-menu-name">{{ m.name }}</span>
          <el-icon v-if="modelValue === m.name" :size="14" class="model-menu-check"><Check /></el-icon>
        </button>
      </template>

      <div v-if="!llmModels.length && !vlmModels.length" class="model-menu-empty">
        暂无可用模型
      </div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { MagicStick, ArrowDown, Check } from '@element-plus/icons-vue'

type ModelMeta = { max_tokens: number; temperature: number; top_p: number; model_type: string }

const props = withDefaults(
  defineProps<{
    modelValue?: string
    models: Record<string, ModelMeta>
  }>(),
  {
    modelValue: '',
    models: () => ({}),
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const visible = ref(false)

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

const currentLabel = computed(() => (props.modelValue ? props.modelValue : 'Auto'))

function choose(value: string) {
  emit('update:modelValue', value)
  visible.value = false
}
</script>

<style scoped>
.model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text-secondary);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
}

.model-trigger:hover {
  background: var(--color-bg-hover);
  color: var(--color-text);
  border-color: var(--color-border);
}

.model-trigger-icon {
  display: inline-flex;
  align-items: center;
  color: var(--color-primary);
}

.model-trigger-label {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-trigger-arrow {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.model-trigger-arrow.open {
  transform: rotate(180deg);
}

.model-menu {
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: 320px;
  overflow-y: auto;
  margin: -4px -6px;
  padding: 4px 6px;
}

.model-menu-group {
  font-size: 11px;
  font-weight: 600;
  color: var(--color-text-muted);
  padding: 8px 8px 4px;
  letter-spacing: 0.03em;
}

.model-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 8px;
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--color-text);
  font-size: var(--text-sm);
  cursor: pointer;
  text-align: left;
  transition: background var(--transition-fast);
}

.model-menu-item:hover {
  background: var(--color-bg-hover);
}

.model-menu-item.active {
  background: var(--color-bg-hover);
  color: var(--color-text);
}

.model-menu-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.model-menu-desc {
  font-size: 11px;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.model-menu-item.active .model-menu-desc {
  color: var(--color-text-muted);
  opacity: 0.8;
}

.model-menu-check {
  color: var(--color-primary);
  flex-shrink: 0;
}

.model-menu-empty {
  padding: var(--space-4);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--color-text-muted);
}
</style>

<style>
/* el-popover 内容非 scoped，需全局穿透 */
.model-trigger-popper.el-popover.el-popper {
  padding: 8px !important;
  border-radius: var(--radius-lg) !important;
}
</style>