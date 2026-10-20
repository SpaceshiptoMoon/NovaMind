<template>
  <div class="composer-area">
    <div class="composer-card">
      <div class="composer-scroll">
        <textarea
          ref="textareaRef"
          v-model="inputText"
          class="composer-textarea"
          :placeholder="running ? '成员讨论中…' : '向群聊发送消息…'"
          :rows="1"
          :disabled="running"
          @keydown="handleKeydown"
          @input="autoResize"
        />
      </div>
      <div class="composer-row">
        <span class="mode-pill" :class="mode">{{ modeLabel }}</span>
        <div class="composer-trailing">
          <button
            v-if="running"
            class="send-primary stop-primary"
            title="停止讨论"
            @click="$emit('stop')"
          >
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
              <rect x="3" y="3" width="10" height="10" rx="3" fill="currentColor" />
            </svg>
          </button>
          <button
            v-else
            class="send-primary"
            :class="{ active: inputText.trim() }"
            :disabled="!inputText.trim()"
            title="发送"
            @click="handleSend"
          >
            <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden>
              <path
                d="M8.3125 0.980183C8.66767 1.0531 8.97902 1.20418 9.2627 1.43233C9.48724 1.61297 9.73029 1.85793 9.97949 2.10714L14.707 6.83468L13.293 8.24874L9 3.95577V15.0417H7V3.95577L2.70703 8.24874L1.29297 6.83468L6.02051 2.10714C6.26971 1.85793 6.51277 1.61297 6.7373 1.43233C6.97662 1.23986 7.28445 1.04402 7.6875 0.980183C7.8973 0.947006 8.1031 0.95516 8.3125 0.980183Z"
                fill="currentColor"
              />
            </svg>
          </button>
        </div>
      </div>
    </div>
    <div class="composer-hint">
      <span class="hint-item"><kbd>Enter</kbd> 发送</span>
      <span class="hint-item"><kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 群聊输入区：单行自适应输入 + 模式徽标（只读）+ 发送/停止双态按钮
 *
 * run 进行中输入禁用（占位文案「成员讨论中…」），发送键换停止键——
 * 群 run 是编排器串行事务，运行中插话 P1 不做（投给谁语义复杂）。
 * 模式是建群时定的，徽标只读不可切换。
 */
import { ref, computed, nextTick } from 'vue'
import type { GroupMode } from '@/api/types'

const props = defineProps<{ running: boolean; mode: GroupMode }>()
const emit = defineEmits<{ send: [content: string]; stop: [] }>()

const inputText = ref('')
const textareaRef = ref<HTMLTextAreaElement>()

const modeLabel = computed(() =>
  props.mode === 'consult' ? '专家咨询' : '头脑风暴',
)

function handleSend() {
  const content = inputText.value.trim()
  if (!content || props.running) return
  inputText.value = ''
  nextTick(() => {
    if (textareaRef.value) textareaRef.value.style.height = 'auto'
  })
  emit('send', content)
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function autoResize() {
  nextTick(() => {
    const el = textareaRef.value
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  })
}
</script>

<style scoped>
.composer-area {
  flex-shrink: 0;
  padding: var(--space-2) var(--space-6) var(--space-4);
  background: transparent;
  position: relative;
}

.composer-card {
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  max-width: var(--container-width-md);
  margin: 0 auto;
  padding: 10px 12px 8px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-md);
  transition:
    border-color var(--transition-base),
    box-shadow var(--transition-base);
}

.composer-card:focus-within {
  border-color: var(--color-primary);
  box-shadow:
    0 0 0 3px var(--color-primary-muted),
    var(--shadow-sm);
}

.composer-scroll {
  max-height: 160px;
  overflow-y: auto;
}

.composer-textarea {
  display: block;
  width: 100%;
  border: none;
  outline: none;
  resize: none;
  font-family: var(--font-body);
  font-size: var(--text-base);
  line-height: var(--leading-normal);
  color: var(--color-text);
  background: transparent;
  padding: 4px 8px 0 12px;
}

.composer-textarea::placeholder {
  color: var(--color-text-faint);
}

.composer-textarea:disabled {
  opacity: 0.5;
}

.composer-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 2px 4px 0;
  flex-wrap: wrap;
}

.mode-pill {
  padding: 3px 10px;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-muted);
  font-size: var(--text-xs);
  white-space: nowrap;
  flex-shrink: 0;
  user-select: none;
}

.composer-trailing {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

/* 发送 / 停止主按钮（34px 圆形，与单聊同款） */
.send-primary {
  display: grid;
  place-items: center;
  flex: none;
  width: 34px;
  height: 34px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-hover);
  color: var(--color-text-faint);
  cursor: not-allowed;
  transition: all var(--transition-base);
}

.send-primary.active {
  background: var(--color-send-active);
  color: var(--color-chip-active-text);
  cursor: pointer;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.15);
}

.send-primary.active:hover {
  background: var(--color-send-active-hover);
  transform: scale(1.05);
}

.send-primary.stop-primary {
  background: var(--color-warning);
  cursor: pointer;
}

.send-primary.stop-primary:hover {
  background: var(--color-accent);
}

.composer-hint {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin: 6px auto 0;
  font-size: var(--text-xs);
  color: var(--color-text-faint);
}

.hint-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.hint-item kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  padding: 1px 5px;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.5;
  color: var(--color-text-secondary);
  background: var(--color-bg-card-elevated);
  border: 1px solid var(--color-border-light);
  border-bottom-width: 2px;
  border-radius: 4px;
}

@media (max-width: 720px) {
  .composer-area {
    padding: var(--space-2) var(--space-3) var(--space-3);
  }

  .composer-hint {
    display: none;
  }
}
</style>
