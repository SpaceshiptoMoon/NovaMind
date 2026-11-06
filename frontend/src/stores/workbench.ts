import { ref } from 'vue'
import { defineStore } from 'pinia'

// 右抽屉视图类型：overview=概览(产物占位) / sources=引用来源 / tool=工具结果详情 / message=消息全文(轨迹视图)
// trajectory=轨迹侧车（时间线列表） / workspace=工作目录浏览器（仅 agent 单聊会话可用）
export type DrawerView = 'overview' | 'sources' | 'tool' | 'message' | 'trajectory' | 'workspace'

// 面板宽度钳制区间与默认值；持久化键与主题键同风格（novamind- 前缀）
export const DRAWER_WIDTH_MIN = 320
export const DRAWER_WIDTH_MAX = 720
export const DRAWER_WIDTH_DEFAULT = 340
const DRAWER_WIDTH_STORAGE_KEY = 'novamind-drawer-width'

function readStoredDrawerWidth(): number {
  try {
    const raw = localStorage.getItem(DRAWER_WIDTH_STORAGE_KEY)
    if (!raw) return DRAWER_WIDTH_DEFAULT
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return DRAWER_WIDTH_DEFAULT
    return Math.min(DRAWER_WIDTH_MAX, Math.max(DRAWER_WIDTH_MIN, Math.round(parsed)))
  } catch {
    return DRAWER_WIDTH_DEFAULT
  }
}

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
  // 面板宽度（px）：拖拽把手实时写入；钳制在 MIN/MAX 区间，localStorage 持久化
  const drawerWidth = ref(readStoredDrawerWidth())
  // 选中的工具调用 call_id（与消息 tool_call_id / agentStore.toolCalls.callId 对应）
  const selectedToolCallId = ref<string | null>(null)
  // 选中的消息 ID（轨迹视图点击 assistant/user/system 行，inspector 展示 reasoning/content 全文）
  const selectedMessageId = ref<number | null>(null)

  /** 打开抽屉；传 view 则同时切换视图（不传保持当前视图） */
  function openDrawer(view?: DrawerView) {
    drawerOpen.value = true
    if (view) drawerView.value = view
  }

  /** 拖拽调宽：钳制区间后写入；合法值同时持久化，刷新后保持用户偏好宽度 */
  function setDrawerWidth(width: number) {
    if (!Number.isFinite(width)) return
    const clamped = Math.min(DRAWER_WIDTH_MAX, Math.max(DRAWER_WIDTH_MIN, Math.round(width)))
    drawerWidth.value = clamped
    try {
      localStorage.setItem(DRAWER_WIDTH_STORAGE_KEY, String(clamped))
    } catch {
      // 隐私模式等 localStorage 不可用场景：仅内存态，忽略持久化失败
    }
  }

  function closeDrawer() {
    drawerOpen.value = false
  }

  function toggleDrawer() {
    drawerOpen.value = !drawerOpen.value
  }

  /** 切换抽屉视图（overview/sources/tool/message），抽屉随之打开 */
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
    drawerWidth,
    selectedToolCallId,
    selectedMessageId,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    setDrawerWidth,
    setView,
    selectToolCall,
    selectMessage,
    resetSelection,
  }
})
