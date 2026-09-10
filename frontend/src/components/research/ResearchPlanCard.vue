<script setup lang="ts">
import { ref, computed } from 'vue'
import { Check, RefreshRight } from '@element-plus/icons-vue'
import type { ResearchPlan } from '@/api/types'

const props = defineProps<{
  plan: ResearchPlan
  status: 'awaiting' | 'accepted' | 'revising' | 'skipped'
}>()

const emit = defineEmits<{
  submit: [decision: 'accepted' | 'edit_plan', feedback: string]
}>()

const feedback = ref('')

const canInteract = computed(() => props.status === 'awaiting')
const statusText = computed(() => {
  switch (props.status) {
    case 'awaiting':
      return '等待确认'
    case 'accepted':
      return '已确认'
    case 'revising':
      return '修订中'
    case 'skipped':
      return '自动执行'
  }
  return ''
})
const statusType = computed(() => {
  switch (props.status) {
    case 'awaiting':
      return 'warning'
    case 'accepted':
      return 'success'
    case 'revising':
      return 'info'
    case 'skipped':
      return 'info'
  }
  return 'info'
})

function handleAccept() {
  emit('submit', 'accepted', '')
}

function handleRevise() {
  emit('submit', 'edit_plan', feedback.value.trim())
  feedback.value = ''
}
</script>

<template>
  <div class="plan-card">
    <div class="plan-card-header">
      <span class="plan-card-title">{{ plan.title || '研究计划' }}</span>
      <el-tag :type="statusType" size="small">{{ statusText }}</el-tag>
    </div>

    <p v-if="plan.thought" class="plan-card-thought">{{ plan.thought }}</p>
    <el-alert
      v-if="plan.has_enough_context"
      title="已有背景信息足够，将直接生成报告"
      type="success"
      :closable="false"
      class="plan-card-alert"
    />

    <ol class="plan-card-steps">
      <li v-for="step in plan.steps" :key="step.step_id" class="plan-card-step">
        <span class="step-badge" :class="`step-badge--${step.step_type}`">
          {{ step.step_type === 'processing' ? '分析' : '检索' }}
        </span>
        <div class="step-body">
          <span class="step-title">{{ step.title }}</span>
          <span class="step-desc">{{ step.description }}</span>
        </div>
      </li>
    </ol>

    <div v-if="canInteract" class="plan-card-actions">
      <el-input
        v-model="feedback"
        type="textarea"
        :rows="2"
        placeholder="如需调整计划，请输入修改意见（可选留空直接确认）"
        class="plan-card-feedback"
      />
      <div class="plan-card-buttons">
        <el-button size="small" :icon="RefreshRight" @click="handleRevise" :disabled="!feedback.trim()">
          修订计划
        </el-button>
        <el-button type="primary" size="small" :icon="Check" @click="handleAccept">
          确认执行
        </el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.plan-card {
  border: 1px solid var(--color-border, #e5e7eb);
  border-radius: var(--radius-lg, 12px);
  padding: 14px 16px;
  background: var(--color-bg-elevated, #fff);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.plan-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.plan-card-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--color-text, #1f2937);
}

.plan-card-thought {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary, #6b7280);
}

.plan-card-alert {
  border-radius: var(--radius-md, 8px);
}

.plan-card-steps {
  margin: 0;
  padding: 0 0 0 4px;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-card-step {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.step-badge {
  flex-shrink: 0;
  font-size: 11px;
  line-height: 1;
  padding: 3px 6px;
  border-radius: var(--radius-full, 999px);
  margin-top: 1px;
}

.step-badge--research {
  background: var(--color-primary-bg, rgba(107, 114, 128, 0.12));
  color: var(--color-primary, #6b7280);
}

.step-badge--processing {
  background: var(--color-warning-bg, rgba(245, 158, 11, 0.12));
  color: var(--color-warning, #b45309);
}

.step-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.step-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text, #1f2937);
}

.step-desc {
  font-size: 12px;
  color: var(--color-text-secondary, #6b7280);
}

.plan-card-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px dashed var(--color-border, #e5e7eb);
  padding-top: 10px;
}

.plan-card-feedback {
  width: 100%;
}

.plan-card-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
