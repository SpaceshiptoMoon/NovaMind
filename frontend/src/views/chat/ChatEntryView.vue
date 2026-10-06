<template>
  <div class="chat-entry">
    <div v-if="error" class="chat-entry__error">
      <p>{{ error }}</p>
      <el-button type="primary" size="small" @click="goAgentWorkspace">前往智能体页</el-button>
    </div>
    <div v-else class="chat-entry__loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在进入对话…</span>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 对话入口跳转页（/home/workspace/chat）
 *
 * 工作台统一对话面的入口：解析（必要时自动开通）当前用户默认助手后
 * 重定向到 agent 聊天页。本页不承载任何聊天逻辑。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'
import { agentApi } from '@/api/agent'

const router = useRouter()
const error = ref('')

function goAgentWorkspace() {
  router.replace('/home/workspace/agents')
}

onMounted(async () => {
  try {
    const agent = await agentApi.getDefaultAgent()
    await router.replace(`/home/workspace/agents/${agent.id}/chat`)
  } catch {
    error.value = '进入对话失败，请确认已配置智能体应用权限'
    ElMessage.error('进入对话失败')
  }
})
</script>

<style scoped>
.chat-entry {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 240px;
}

.chat-entry__loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-secondary, #71717a);
  font-size: 13px;
}

.chat-entry__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--text-secondary, #71717a);
  font-size: 13px;
}
</style>
