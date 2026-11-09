import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAgentStore } from '@/stores/agent'
import { agentApi } from '@/api/agent'

/**
 * 会话工作目录绑定的唯一实现（单聊）
 *
 * 弹窗（WorkspaceBindDialog）与右面板目录视图共用：绑定/解绑动作在此收口
 * （写会话 workspace + 自动并入 local_workspace 工具 + 会话列表回写），
 * 目录浏览态不在此——那是 WorkspaceBrowser 的内部状态，两个宿主各自独立。
 */
export function useWorkspaceBinding() {
  const agentStore = useAgentStore()

  const currentConversation = computed(
    () => agentStore.conversations.find((c) => c.session_id === agentStore.currentSessionId) || null,
  )
  const workspaceConfig = computed(() => currentConversation.value?.extra_config?.workspace ?? null)
  const isWorkspaceBound = computed(() => !!workspaceConfig.value)
  const workspaceRoot = computed(() => workspaceConfig.value?.root || '')

  /** 工作目录 chip 显示名：取末段（长路径截断），title 里看全路径 */
  const workspaceRootName = computed(() => {
    const p = workspaceRoot.value.replace(/\/+$/, '')
    const seg = p.split(/[\\/]/).pop() || p
    return seg.length > 18 ? `${seg.slice(0, 17)}…` : seg
  })

  const binding = ref(false)

  /** 绑定：传入目录即根，写会话 workspace + 自动给 agent 并入 local_workspace 勾选 */
  async function bindWorkspace(root: string): Promise<boolean> {
    const sessionId = agentStore.currentSessionId
    if (!sessionId || !agentStore.currentAgent || !root) return false
    binding.value = true
    try {
      await agentApi.updateSessionWorkspace(sessionId, { mode: 'local', root })
      // 工具默认必带：本地模式下 local_workspace 提供者须在 agent.enabled_tools 里
      // 才会随 resolve_tools 下发 schema；未勾选时静默并入
      const agent = agentStore.currentAgent
      const tools = agent.enabled_tools || []
      if (!tools.includes('local_workspace')) {
        await agentStore.updateAgent(agent.id, {
          enabled_tools: [...tools, 'local_workspace'],
        })
      }
      // 回写会话列表里的 workspace 键（不重新拉全量）
      const conv = currentConversation.value
      if (conv) {
        conv.extra_config = { ...conv.extra_config, workspace: { mode: 'local', root } }
      }
      ElMessage.success('已进入工作模式：read / glob / grep / bash 已启用')
      return true
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '绑定失败')
      return false
    } finally {
      binding.value = false
    }
  }

  /** 解绑：清会话 workspace；agent 勾选保留（其他会话可能仍在用） */
  async function unbindWorkspace(): Promise<boolean> {
    const sessionId = agentStore.currentSessionId
    if (!sessionId) return false
    binding.value = true
    try {
      await agentApi.updateSessionWorkspace(sessionId, null)
      const conv = currentConversation.value
      if (conv && conv.extra_config) {
        const next = { ...conv.extra_config }
        delete next.workspace
        conv.extra_config = next
      }
      ElMessage.success('已退出工作模式')
      return true
    } catch (e) {
      ElMessage.error(e instanceof Error ? e.message : '解绑失败')
      return false
    } finally {
      binding.value = false
    }
  }

  return {
    isWorkspaceBound,
    workspaceRoot,
    workspaceRootName,
    binding,
    bindWorkspace,
    unbindWorkspace,
  }
}
