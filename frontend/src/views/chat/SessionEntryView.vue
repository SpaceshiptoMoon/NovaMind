<template>
  <!-- 薄入口：仅过渡态加载占位，判 kind 后立即转跳目标会话页 -->
  <div
    v-loading="true"
    class="session-entry-view"
    element-loading-text="正在打开会话…"
  />
</template>

<script setup lang="ts">
/**
 * 会话直达入口（薄 view）：/home/workspace/chat/:sessionId
 *
 * 拉 GET /agent/sessions/{sessionId}（单聊/群会话同一张表同一端点），按
 * extra_config.group 标记判 kind（对齐后端 agent_service.list_recent_sessions：
 * group={group_id} 为群时间线会话，单聊无此键）：
 * - 群会话 → WorkspaceGroupChat(groupId)，query 带目标会话供群页初始定位；
 * - 单聊 → 补 agentStore 上下文（currentAgent/会话列表）→ WorkspaceAgentChat → 拉历史。
 * 会话不存在/非本人/已删除（SessionNotFoundError）：错误提示由 request 拦截器统一
 * toast，这里只负责退回对话入口兜底。
 */
import { onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { agentApi } from '@/api/agent'
import { useAgentStore } from '@/stores/agent'

const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()

/** 兜底：会话打不开时退回对话入口（WorkspaceChat 欢迎页） */
async function bailOut() {
  await router.push('/home/workspace/chat')
}

onMounted(async () => {
  const sessionId = String(route.params.sessionId || '')
  if (!sessionId) {
    await bailOut()
    return
  }
  try {
    const detail = await agentApi.getSession(sessionId)
    // 群会话标记：extra_config.group={group_id}（时间线载体）；单聊会话无此键
    const groupFlag = detail.extra_config?.group
    const groupId =
      groupFlag && typeof groupFlag === 'object' && groupFlag.group_id != null
        ? Number(groupFlag.group_id)
        : null
    if (groupId !== null) {
      // 群会话：进群页，query 带目标会话（GroupChatView 在 initForGroup 完成后定位）
      await router.push({
        name: 'WorkspaceGroupChat',
        params: { groupId },
        query: { sessionId: detail.session_id },
      })
      return
    }
    // 单聊：设 currentAgent（agents 列表零成本取；直达刷新时列表未加载则拉详情兜底）
    agentStore.currentAgent = agentStore.agents.find((a) => a.id === detail.agent_id) ?? null
    if (!agentStore.currentAgent) await agentStore.fetchAgent(detail.agent_id)
    agentStore.fetchConversations(detail.agent_id)
    // 流式进行中先中止（SSE 回调写全局 messages，不中止会串台）
    if (agentStore.isStreaming) agentStore.cancelStream()
    await router.push({
      name: 'WorkspaceAgentChat',
      params: { agentId: detail.agent_id },
      // 透传 query（bind=1：本地项目创建流程自动弹目录绑定，由 AgentChatView 消费）
      query: route.query,
    })
    // fetchMessages 必须在 push 之后：AgentChatView 挂载的 initForAgent 会 clearChat
    // （清 messages/currentSessionId），push 前拉取的历史会被挂载清态冲掉（批2 同款约束）
    await agentStore.fetchMessages(detail.session_id)
  } catch {
    await bailOut()
  }
})
</script>

<style scoped>
.session-entry-view {
  position: absolute;
  inset: 0;
  z-index: 1;
  background: var(--color-bg-elevated);
}
</style>
