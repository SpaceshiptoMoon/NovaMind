import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { ElNotification } from 'element-plus'
import { notificationApi, connectNotificationWs, disconnectNotificationWs } from '@/api/notification'
import type { Notification } from '@/api/types'

/** header 下拉与徽标的单一事实源：WS 实时推送 + 30s 轮询兜底收敛 */
export const useNotificationStore = defineStore('notification', () => {
  // 最近通知（header 下拉数据源，最多保留 20 条）
  const items = ref<Notification[]>([])
  const unreadCount = ref(0)
  // WS 连接状态
  const connected = ref(false)

  let pollTimer: ReturnType<typeof setInterval> | null = null
  let inited = false

  const hasUnread = computed(() => unreadCount.value > 0)

  async function fetchUnreadCount(): Promise<void> {
    try {
      const res = await notificationApi.getUnreadCount()
      unreadCount.value = res.unread_count
    } catch {
      // 静默：轮询兜底，失败等下一轮
    }
  }

  async function loadRecent(limit = 5): Promise<void> {
    try {
      const res = await notificationApi.getNotifications({ limit })
      items.value = res.items || []
      unreadCount.value = res.unread_count
    } catch {
      // 静默
    }
  }

  /** WS 收到新通知：去重 prepend + 徽标累加 + 轻提示 */
  function handleWsEvent(n: Notification): void {
    if (items.value.some((item) => item.id === n.id)) return
    items.value = [n, ...items.value].slice(0, 20)
    unreadCount.value++
    ElNotification({
      title: n.title,
      message: n.content,
      type: 'info',
      duration: 4500,
    })
  }

  /**
   * 初始化（幂等）：拉取基线数据 + 建 WS 订阅 + 启动轮询兜底。
   * 登录后由 AppHeader watch isLoggedIn 调用。
   */
  function init(): void {
    if (inited) return
    inited = true

    fetchUnreadCount()
    loadRecent()

    connectNotificationWs({
      onEvent: handleWsEvent,
      onStateChange: (up) => {
        connected.value = up
        // 重连成功后补拉，收敛断线窗口内丢失的事件
        if (up) loadRecent()
      },
    })

    pollTimer = setInterval(fetchUnreadCount, 30_000)
  }

  async function markRead(id: number): Promise<void> {
    const target = items.value.find((item) => item.id === id)
    if (target && !target.is_read) {
      target.is_read = true
      unreadCount.value = Math.max(unreadCount.value - 1, 0)
    }
    try {
      await notificationApi.markRead(id)
    } catch {
      // 失败等下一次轮询收敛未读数
    }
  }

  async function markAllRead(): Promise<void> {
    items.value = items.value.map((item) => ({ ...item, is_read: true }))
    unreadCount.value = 0
    try {
      await notificationApi.markAllRead()
    } catch {
      // 同上
    }
  }

  /** 登出清理：断开 WS + 停轮询 + 清状态 */
  function stop(): void {
    inited = false
    disconnectNotificationWs()
    if (pollTimer !== null) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    items.value = []
    unreadCount.value = 0
    connected.value = false
  }

  return {
    items,
    unreadCount,
    connected,
    hasUnread,
    init,
    loadRecent,
    fetchUnreadCount,
    markRead,
    markAllRead,
    stop,
  }
})
