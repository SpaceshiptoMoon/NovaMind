<template>
  <div class="approval-card" role="alertdialog" aria-label="危险操作确认">
    <div class="approval-head">
      <span class="approval-icon" aria-hidden>⚠</span>
      <span class="approval-title">危险操作确认</span>
      <span class="approval-sep" aria-hidden />
      <span class="approval-meta">{{ approval.tool }}</span>
      <span v-if="secondsLeft != null" class="approval-countdown" :class="{ urgent: secondsLeft <= 15 }">
        {{ secondsLeft }}s
      </span>
    </div>
    <div class="approval-body">
      <p class="approval-pattern">{{ approval.pattern_key }}</p>
      <pre class="approval-preview">{{ approval.preview }}</pre>
      <p class="approval-hint">超时未决策将按拒绝处理（120 秒）</p>
    </div>
    <div class="approval-actions">
      <el-button size="small" :disabled="expired" @click="emit('deny', approval.approval_id)">
        拒绝
      </el-button>
      <el-button
        size="small"
        type="danger"
        :disabled="expired"
        @click="emit('approve', approval.approval_id)"
      >
        {{ expired ? '已超时' : '批准执行' }}
      </el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * E5 异步审批卡：危险代码执行前的用户决策入口（后端 ApprovalHook 推送
 * approval_request 事件，决策经 WS {action:'approval'} 回传）。
 * 后端 120s 超时按 deny fail-closed——卡片内做同周期倒计时，到期置灰，
 * 后端超时拒绝事件（tool_result error）照常回流。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import type { ApprovalRequestData } from '@/api/types'

const props = defineProps<{ approval: ApprovalRequestData }>()
const emit = defineEmits<{ approve: [approvalId: string]; deny: [approvalId: string] }>()

const APPROVAL_TIMEOUT_SECONDS = 120
const secondsLeft = ref<number | null>(null)
let timer: ReturnType<typeof setInterval> | null = null

const expired = computed(() => secondsLeft.value != null && secondsLeft.value <= 0)

function startCountdown() {
  stopCountdown()
  secondsLeft.value = APPROVAL_TIMEOUT_SECONDS
  timer = setInterval(() => {
    if (secondsLeft.value != null && secondsLeft.value > 0) {
      secondsLeft.value -= 1
    }
    if (secondsLeft.value != null && secondsLeft.value <= 0) {
      stopCountdown()
    }
  }, 1000)
}

function stopCountdown() {
  if (timer != null) {
    clearInterval(timer)
    timer = null
  }
}

// 每条新审批请求重置倒计时（旧请求已被后端 cleanup，组件仅渲染当前 pending 态）
watch(
  () => props.approval.approval_id,
  (id) => {
    if (id) startCountdown()
  },
  { immediate: true },
)

onBeforeUnmount(stopCountdown)
</script>

<style scoped>
.approval-card {
  margin: var(--space-2) 0;
  padding: var(--space-3);
  border: 1px solid var(--color-danger);
  border-radius: var(--radius-md);
  background: var(--color-danger-subtle);
}

.approval-head {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-sm);
}

.approval-icon {
  color: var(--color-danger);
  font-size: 14px;
}

.approval-title {
  font-weight: var(--weight-medium);
  color: var(--color-danger);
}

.approval-sep {
  width: 1px;
  height: 12px;
  background: var(--color-border-light);
}

.approval-meta {
  color: var(--color-text-secondary);
  font-family: var(--font-mono, monospace);
}

.approval-countdown {
  margin-left: auto;
  color: var(--color-warning);
  font-variant-numeric: tabular-nums;
}

.approval-countdown.urgent {
  color: var(--color-danger);
  font-weight: var(--weight-medium);
}

.approval-body {
  margin-top: var(--space-2);
}

.approval-pattern {
  margin: 0 0 var(--space-2);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
}

.approval-preview {
  margin: 0;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-sm);
  background: var(--color-bg-card-elevated);
  font-family: var(--font-mono, monospace);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 160px;
  overflow-y: auto;
}

.approval-hint {
  margin: var(--space-2) 0 0;
  font-size: var(--text-xs);
  color: var(--color-text-muted);
}

.approval-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
  margin-top: var(--space-3);
}
</style>
