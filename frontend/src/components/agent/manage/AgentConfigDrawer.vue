<template>
  <el-drawer
    :model-value="modelValue"
    :title="`${agent?.name || '智能体'} · 配置`"
    direction="rtl"
    size="420px"
    :append-to-body="true"
    @update:model-value="(v: boolean) => emit('update:modelValue', v)"
  >
    <div class="config-drawer-body">
      <div class="config-card config-card--full">
        <div class="config-label">系统提示词</div>
        <div class="config-value system-prompt">{{ agent?.system_prompt || '-' }}</div>
      </div>
      <div class="config-grid">
        <div class="config-card">
          <div class="config-label">模型</div>
          <div class="config-value">{{ agent?.llm_model || '默认' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">计划模式</div>
          <div class="config-value">
            {{ agent?.extra_config?.plan_mode === true ? '开启' : '关闭' }}
          </div>
        </div>
        <div class="config-card">
          <div class="config-label">Temperature</div>
          <div class="config-value">{{ agent?.temperature ?? '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">Top P</div>
          <div class="config-value">{{ agent?.top_p ?? '-' }}</div>
        </div>
        <div class="config-card">
          <div class="config-label">最大生成</div>
          <div class="config-value">
            {{ agent?.max_tokens != null ? `${agent.max_tokens} tokens` : '-' }}
          </div>
        </div>
        <div class="config-card">
          <div class="config-label">上下文窗口</div>
          <div class="config-value">
            {{ agent?.context_window != null ? `${agent.context_window} tokens` : '-' }}
          </div>
        </div>
      </div>
      <div class="config-card config-card--full">
        <div class="config-label">工具</div>
        <div class="config-value">
          <template v-if="agent?.enabled_tools?.length">
            <span v-for="s in agent.enabled_tools" :key="s" class="tag">{{ s }}</span>
          </template>
          <template v-else>未启用</template>
        </div>
      </div>
      <div class="config-card config-card--full">
        <div class="config-label">MCP 服务器</div>
        <div class="config-value">
          <template v-if="agent?.enabled_mcp_servers?.length">
            <span v-for="m in agent.enabled_mcp_servers" :key="m" class="tag"
              >Server #{{ m }}</span
            >
          </template>
          <template v-else>未启用</template>
        </div>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
/** Agent 只读配置抽屉（原 WorkspaceLayout 内联段拆出）：append-to-body 需全局样式。 */
import type { Agent } from '@/api/types'

defineProps<{ modelValue: boolean; agent: Agent | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()
</script>

<style>
/* 配置抽屉内容（append-to-body 需全局；自原 AgentView 平移） */
.config-drawer-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.config-drawer-body .config-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
}

.config-drawer-body .config-label {
  font-size: var(--text-xs);
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.config-drawer-body .config-value {
  font-size: var(--text-sm);
  color: var(--color-text);
  line-height: var(--leading-relaxed);
  word-break: break-word;
}

/* 生成参数双列网格：抽屉 420px 内键值对成对并排，模型/计划模式/采样参数同层 */
.config-drawer-body .config-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-3);
}

.config-drawer-body .config-grid .config-card {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border-light);
  border-radius: var(--radius-lg);
  background: var(--color-bg-card);
}

@media (max-width: 480px) {
  .config-drawer-body .config-grid {
    grid-template-columns: 1fr;
  }
}

.config-drawer-body .system-prompt {
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
}

.config-drawer-body .tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: var(--radius-full);
  background: var(--color-primary-muted);
  color: var(--color-primary);
  font-size: var(--text-xs);
  margin-right: var(--space-1);
  margin-bottom: var(--space-1);
}
</style>
