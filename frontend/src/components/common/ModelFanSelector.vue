<template>
  <div class="model-fan" ref="wrapperRef">
    <button
      class="fan-trigger"
      :class="{ active: open }"
      @click.stop="toggle"
    >
      <span class="fan-trigger-label">{{ shortName }}</span>
      <svg class="fan-trigger-arrow" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="6 9 12 15 18 9" />
      </svg>
    </button>

    <transition name="fan-pop">
      <div v-if="open" class="fan-panel">
        <div class="fan-header">选择模型</div>
        <div class="fan-list">
          <template v-if="llmModels.length">
            <div class="fan-group-label">LLM 文本模型</div>
            <button
              v-for="item in llmModels"
              :key="item.name"
              class="fan-item"
              :class="{ selected: item.name === innerValue }"
              @click.stop="select(item.name)"
            >
              <span class="fan-check">
                <svg v-if="item.name === innerValue" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
              <span class="fan-item-text">{{ item.name }}</span>
            </button>
          </template>
          <template v-if="vlmModels.length">
            <div class="fan-group-label">VLM 视觉模型</div>
            <button
              v-for="item in vlmModels"
              :key="item.name"
              class="fan-item"
              :class="{ selected: item.name === innerValue }"
              @click.stop="select(item.name)"
            >
              <span class="fan-check">
                <svg v-if="item.name === innerValue" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              </span>
              <span class="fan-item-text">{{ item.name }}</span>
            </button>
          </template>
        </div>
        <div class="fan-footer" />
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  models: Record<string, { max_tokens: number; temperature: number; top_p: number; model_type?: string }>
  modelValue: string
  defaultModelName: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const wrapperRef = ref<HTMLElement>()
const open = ref(false)

const innerValue = computed({
  get: () => props.modelValue,
  set: (v: string) => emit('update:modelValue', v),
})

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

const shortName = computed(() => {
  const name = props.modelValue || props.defaultModelName || '默认'
  return name.length > 10 ? name.slice(0, 9) + '..' : name
})

function toggle() {
  open.value = !open.value
}

function select(name: string) {
  innerValue.value = name
  open.value = false
}

function onClickOutside(e: MouseEvent) {
  if (!wrapperRef.value) return
  if (!wrapperRef.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => document.addEventListener('click', onClickOutside, true))
onUnmounted(() => document.removeEventListener('click', onClickOutside, true))
</script>

<style scoped>
.model-fan {
  position: relative;
  flex-shrink: 0;
}

/* ===== Trigger — shows current model name ===== */
.fan-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  height: 32px;
  padding: 0 var(--space-2);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  color: var(--color-text-secondary);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-base);
  max-width: 140px;
}

.fan-trigger:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.fan-trigger.active {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: var(--color-primary-muted);
}

.fan-trigger-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.fan-trigger-arrow {
  flex-shrink: 0;
  transition: transform var(--transition-slow);
}

.fan-trigger.active .fan-trigger-arrow {
  transform: rotate(180deg);
}

/* ===== Panel — semi-circle top, list inside ===== */
.fan-panel {
  position: absolute;
  bottom: 40px;
  right: 0;
  min-width: 200px;
  max-width: 280px;
  background: var(--color-bg-card);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-2xl) var(--radius-2xl) var(--radius-2xl) var(--radius-sm);
  box-shadow: var(--shadow-lg);
  z-index: var(--z-dropdown);
  overflow: hidden;
}

.fan-header {
  padding: var(--space-2) var(--space-4) var(--space-1);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.fan-list {
  padding: var(--space-1) var(--space-2);
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.fan-group-label {
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--color-text-muted);
  letter-spacing: 0.3px;
}

.fan-footer {
  height: var(--space-2);
}

/* ===== Item ===== */
.fan-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-xl);
  background: transparent;
  color: var(--color-text);
  font-family: var(--font-body);
  font-size: var(--text-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
  text-align: left;
}

.fan-item:hover {
  background: var(--color-bg-hover);
}

.fan-item.selected {
  background: var(--color-primary-muted);
  color: var(--color-primary);
}

.fan-check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1.5px solid var(--color-border);
  transition: all var(--transition-fast);
}

.fan-item.selected .fan-check {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #FFFFFF;
}

.fan-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ===== Transition ===== */
.fan-pop-enter-active {
  transition: opacity var(--transition-base), transform var(--transition-spring);
}
.fan-pop-leave-active {
  transition: opacity var(--transition-fast), transform var(--transition-fast);
}
.fan-pop-enter-from,
.fan-pop-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.95);
}
.fan-pop-enter-to,
.fan-pop-leave-from {
  opacity: 1;
  transform: translateY(0) scale(1);
}
</style>
