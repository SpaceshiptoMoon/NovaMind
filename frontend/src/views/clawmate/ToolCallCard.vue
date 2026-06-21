<template>
  <div class="tool-card" :class="`tool-card--${status}`">
    <div class="tool-header" @click="expanded = !expanded">
      <div class="tool-info">
        <el-icon v-if="status === 'running'" :size="14" class="tool-icon tool-icon--spinning">
          <Loading />
        </el-icon>
        <el-icon v-else :size="14" class="tool-icon">
          <SetUp />
        </el-icon>
        <span class="tool-name">{{ name }}</span>
        <span class="tool-status" :class="`tool-status--${status}`">{{ statusLabel }}</span>
      </div>
      <el-icon :size="12" class="expand-icon" :class="{ expanded }">
        <ArrowDown />
      </el-icon>
    </div>

    <div v-if="expanded" class="tool-body">
      <div v-if="args && Object.keys(args).length > 0" class="tool-section">
        <div class="tool-section-label">参数</div>
        <pre class="tool-json">{{ formatJson(args) }}</pre>
      </div>
      <div v-if="result" class="tool-section">
        <div class="tool-section-label">结果</div>
        <pre class="tool-json">{{ showFullResult ? result : truncatedResult }}</pre>
        <button
          v-if="result.length > TRUNCATE_LENGTH"
          class="tool-toggle"
          @click.stop="showFullResult = !showFullResult"
        >
          {{ showFullResult ? '收起' : '展开更多' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Loading, ArrowDown, SetUp } from '@element-plus/icons-vue'

const TRUNCATE_LENGTH = 500

const props = defineProps<{
  name: string
  callId: string
  status: 'running' | 'completed' | 'failed'
  result?: string
  args?: Record<string, unknown>
}>()

const expanded = ref(false)
const showFullResult = ref(false)

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    running: '执行中',
    completed: '完成',
    failed: '失败',
  }
  return map[props.status] || props.status
})

const truncatedResult = computed(() => {
  if (!props.result) return ''
  if (props.result.length <= TRUNCATE_LENGTH) return props.result
  return props.result.slice(0, TRUNCATE_LENGTH) + '...'
})

function formatJson(obj: Record<string, unknown>): string {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}
</script>

<style scoped>
.tool-card {
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
  overflow: hidden;
  max-width: 600px;
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-3) var(--space-4);
  cursor: pointer;
  transition: background var(--transition-fast);
}

.tool-header:hover {
  background: var(--color-bg-hover);
}

.tool-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.tool-icon {
  display: flex;
  align-items: center;
  color: var(--color-primary);
}

.tool-icon--spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.tool-name {
  font-family: var(--font-mono);
  font-size: var(--text-sm);
  font-weight: var(--weight-medium);
  color: var(--color-text);
}

.tool-status {
  font-size: var(--text-xs);
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  font-weight: var(--weight-medium);
}

.tool-status--running {
  background: var(--color-primary-subtle);
  color: var(--color-primary);
}

.tool-status--completed {
  background: rgba(46, 184, 92, 0.1);
  color: #2eb85c;
}

.tool-status--failed {
  background: var(--color-danger-subtle);
  color: var(--color-danger);
}

.expand-icon {
  color: var(--color-text-muted);
  transition: transform var(--transition-fast);
}

.expand-icon.expanded {
  transform: rotate(180deg);
}

.tool-body {
  border-top: 1px solid var(--color-border-light);
  padding: var(--space-3) var(--space-4);
}

.tool-section {
  margin-bottom: var(--space-3);
}

.tool-section:last-child {
  margin-bottom: 0;
}

.tool-section-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.tool-json {
  font-family: var(--font-mono);
  font-size: var(--text-xs);
  color: var(--color-text-secondary);
  background: var(--color-bg);
  padding: var(--space-3);
  border-radius: var(--radius-md);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
  margin: 0;
}

.tool-toggle {
  display: inline-block;
  margin-top: var(--space-2);
  border: none;
  background: transparent;
  font-family: var(--font-body);
  font-size: var(--text-xs);
  color: var(--color-primary);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
  transition: background var(--transition-fast);
}

.tool-toggle:hover {
  background: var(--color-primary-subtle);
}
</style>
