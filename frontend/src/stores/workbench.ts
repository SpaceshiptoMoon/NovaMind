import { ref } from 'vue'
import { defineStore } from 'pinia'

// 右抽屉视图类型：overview=概览(产物占位) / sources=引用来源 / tool=工具结果详情 / message=消息全文(轨迹视图)
export type DrawerView = 'overview' | 'sources' | 'tool' | 'message'

/**
 * 工作台右抽屉状态
 *
 * 仅持有 UI 态（开关/当前视图/选中的工具调用 ID / 选中的消息 ID）；
 * 抽屉展示的数据（sources / toolCalls）由 WorkspaceLayout 按当前频道
 * 从 chatStore / agentStore 聚合后以 props 喂入，避免在视图层重复接线。
 */
export const useWorkbenchStore = defineStore('workbench', () => {
  const drawerOpen = ref(false)
  const drawerView = ref<DrawerView>('overview')
  // 选中的工具调用 call_id（与消息 tool_call_id / agentStore.toolCalls.callId 对应）
  const selectedToolCallId = ref<string | null>(null)
  // 选中的消息 ID（轨迹视图点击 assistant/user/system 行，inspector 展示 reasoning/content 全文）
  const selectedMessageId = ref<number | null>(null)

  function openDrawer(view?: DrawerView) {
    drawerOpen.value = true
    if (view) drawerView.value = view
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function toggleDrawer() {
    drawerOpen.value = !drawerOpen.value
  }

  function setView(view: DrawerView) {
    drawerView.value = view
    drawerOpen.value = true
  }

  // 选中某个工具调用并在抽屉打开其结果详情
  function selectToolCall(callId: string) {
    selectedToolCallId.value = callId
    drawerView.value = 'tool'
    drawerOpen.value = true
  }

  // 选中某条消息并在抽屉打开其全文（轨迹视图 assistant/user/system 行）
  function selectMessage(messageId: number) {
    selectedMessageId.value = messageId
    drawerView.value = 'message'
    drawerOpen.value = true
  }

  // 切换会话/频道时重置选中态，避免残留上一会话的工具结果
  function resetSelection() {
    selectedToolCallId.value = null
    selectedMessageId.value = null
    drawerView.value = 'overview'
  }

  return {
    drawerOpen,
    drawerView,
    selectedToolCallId,
    selectedMessageId,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    setView,
    selectToolCall,
    selectMessage,
    resetSelection,
  }
})