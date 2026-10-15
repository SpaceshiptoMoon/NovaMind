<template>
  <div class="chat-entry">
    <!-- 解析默认助手中的骨架占位：预演目标对话页（欢迎态）版式，
         加载完成经 fade 过渡切入真页，消除「白屏转圈→突然出现」的割裂感 -->
    <div v-if="!error" class="chat-entry__skeleton" aria-busy="true">
      <div class="chat-entry__greeting">
        <div class="skeleton chat-entry__sk-title"></div>
        <div class="skeleton chat-entry__sk-desc"></div>
      </div>
      <div class="chat-entry__sk-card">
        <div class="skeleton chat-entry__sk-line"></div>
        <div class="chat-entry__sk-row">
          <div class="skeleton chat-entry__sk-chip" v-for="n in 4" :key="n"></div>
          <div class="chat-entry__sk-spacer"></div>
          <div class="skeleton chat-entry__sk-send"></div>
        </div>
      </div>
      <div class="chat-entry__sk-suggestions">
        <div class="skeleton chat-entry__sk-pill" v-for="n in 3" :key="n"></div>
      </div>
    </div>

    <div v-if="error" class="chat-entry__error">
      <p>{{ error }}</p>
      <el-button type="primary" size="small" @click="goAgentWorkspace">前往智能体页</el-button>
    </div>

    <div v-if="slow" class="chat-entry__slow-hint">正在进入对话…</div>
  </div>
</template>

<script setup lang="ts">
/**
 * 对话入口跳转页（/home/workspace/chat）
 *
 * 工作台统一对话面的入口：解析（必要时自动开通）当前用户默认助手后
 * 重定向到 agent 聊天页。本页不承载任何聊天逻辑；加载态以对话页骨架
 * 呈现，仅当解析明显偏慢（>600ms）才补一行文字提示。
 */
import { onMounted, ref, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { agentApi } from '@/api/agent'

const router = useRouter()
const error = ref('')
// 接口 >600ms 未返回才显示文字提示（骨架本身已表达加载中，避免快网闪字）
const slow = ref(false)
let slowTimer: ReturnType<typeof setTimeout> | null = null

function goAgentWorkspace() {
  router.replace('/home/workspace/agents')
}

onMounted(async () => {
  slowTimer = setTimeout(() => {
    slow.value = true
  }, 600)
  try {
    const agent = await agentApi.getDefaultAgent()
    await router.replace(`/home/workspace/agents/${agent.id}/chat`)
  } catch {
    error.value = '进入对话失败，请确认已配置智能体应用权限'
    ElMessage.error('进入对话失败')
  } finally {
    if (slowTimer) clearTimeout(slowTimer)
  }
})

onBeforeUnmount(() => {
  if (slowTimer) clearTimeout(slowTimer)
})
</script>

<style scoped>
.chat-entry {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  /* 与 AgentChatView 画布同 token（bg-card 非-bg）：骨架→真页切换不跳底色 */
  background: var(--color-bg-card);
  overflow: hidden;
}

/* ===== 骨架：预演 AgentChatView 欢迎态版式 ===== */
.chat-entry__skeleton {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 100%;
  max-width: var(--container-width-md);
  padding: 0 var(--space-6);
}

.chat-entry__greeting {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  margin-bottom: 36px;
}

.chat-entry__sk-title {
  width: 180px;
  height: 26px;
  border-radius: var(--radius-md);
}

.chat-entry__sk-desc {
  width: 260px;
  height: 14px;
  border-radius: var(--radius-sm);
}

.chat-entry__sk-card {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 14px 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-2xl);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-md);
}

.chat-entry__sk-line {
  width: 40%;
  height: 14px;
  border-radius: var(--radius-sm);
}

.chat-entry__sk-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-entry__sk-chip {
  width: 72px;
  height: 28px;
  border-radius: var(--radius-md);
  flex-shrink: 0;
}

.chat-entry__sk-spacer {
  flex: 1;
}

.chat-entry__sk-send {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.chat-entry__sk-suggestions {
  display: flex;
  gap: 12px;
  margin-top: 20px;
}

.chat-entry__sk-pill {
  width: 140px;
  height: 32px;
  border-radius: var(--radius-full);
}

/* ===== 慢网文字提示与错误态 ===== */
.chat-entry__slow-hint {
  position: absolute;
  bottom: 32px;
  font-size: 12px;
  color: var(--color-text-faint);
}

.chat-entry__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: var(--color-text-secondary, #71717a);
  font-size: 13px;
}
</style>
