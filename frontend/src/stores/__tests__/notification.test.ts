import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const { notificationApi, connectNotificationWs, disconnectNotificationWs } = vi.hoisted(() => ({
  notificationApi: {
    getNotifications: vi.fn(),
    getUnreadCount: vi.fn(),
    markRead: vi.fn(),
    markAllRead: vi.fn(),
  },
  connectNotificationWs: vi.fn(),
  disconnectNotificationWs: vi.fn(),
}))

vi.mock('@/api/notification', () => ({
  notificationApi,
  connectNotificationWs,
  disconnectNotificationWs,
}))

vi.mock('element-plus', () => ({
  ElNotification: vi.fn(),
}))

import { useNotificationStore } from '@/stores/notification'

function _notification(id: number, is_read = false) {
  return {
    id,
    user_id: 1,
    type: 'system',
    title: `通知${id}`,
    content: 'c',
    link: null,
    extra_data: null,
    is_read,
    read_at: null,
    created_at: '2026-09-13T00:00:00',
  }
}

function _wsHandlers() {
  const call = connectNotificationWs.mock.calls[0]?.[0]
  if (!call) throw new Error('connectNotificationWs 未被调用')
  return call as {
    onEvent: (n: ReturnType<typeof _notification>) => void
    onStateChange?: (up: boolean) => void
  }
}

describe('notification store — WS 推送 + 轮询兜底', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('init：拉取基线数据 + 注册 WS 订阅 + 启动轮询', () => {
    notificationApi.getUnreadCount.mockResolvedValue({ unread_count: 3 })
    notificationApi.getNotifications.mockResolvedValue({
      items: [_notification(1)],
      total: 1,
      unread_count: 3,
    })
    const store = useNotificationStore()
    store.init()
    expect(notificationApi.getUnreadCount).toHaveBeenCalled()
    expect(notificationApi.getNotifications).toHaveBeenCalledWith({ limit: 5 })
    expect(connectNotificationWs).toHaveBeenCalledTimes(1)
    store.stop()
  })

  it('init 幂等：重复调用不重复订阅', () => {
    const store = useNotificationStore()
    store.init()
    store.init()
    expect(connectNotificationWs).toHaveBeenCalledTimes(1)
    store.stop()
  })

  it('handleWsEvent：新通知 prepend + 未读累加；同 id 去重', () => {
    const store = useNotificationStore()
    store.init()
    const onEvent = _wsHandlers().onEvent

    onEvent(_notification(10))
    onEvent(_notification(11))
    onEvent(_notification(10)) // 重复 id 应被忽略
    expect(store.items.map((n: { id: number }) => n.id)).toEqual([11, 10])
    expect(store.unreadCount).toBe(2)
    store.stop()
  })

  it('handleWsEvent：超过 20 条截断', () => {
    const store = useNotificationStore()
    store.init()
    const onEvent = _wsHandlers().onEvent
    for (let i = 1; i <= 25; i++) onEvent(_notification(i))
    expect(store.items.length).toBe(20)
    store.stop()
  })

  it('onStateChange(true)：重连后补拉数据收敛断线窗口', () => {
    notificationApi.getNotifications.mockResolvedValue({ items: [], total: 0, unread_count: 0 })
    const store = useNotificationStore()
    store.init()
    const { onStateChange } = _wsHandlers()
    const callsBefore = notificationApi.getNotifications.mock.calls.length
    onStateChange?.(true)
    expect(notificationApi.getNotifications.mock.calls.length).toBe(callsBefore + 1)
    store.stop()
  })

  it('markRead：本地置已读 + 未读数递减，API 调用', async () => {
    notificationApi.getNotifications.mockResolvedValue({
      items: [_notification(1)],
      total: 1,
      unread_count: 1,
    })
    notificationApi.markRead.mockResolvedValue({ message: 'ok' })
    const store = useNotificationStore()
    await store.loadRecent()
    await store.markRead(1)
    expect(notificationApi.markRead).toHaveBeenCalledWith(1)
    expect(store.unreadCount).toBe(0)
  })

  it('markAllRead：全部置已读', async () => {
    notificationApi.getNotifications.mockResolvedValue({ items: [], total: 0, unread_count: 0 })
    notificationApi.markAllRead.mockResolvedValue({ message: 'ok' })
    const store = useNotificationStore()
    store.init()
    const onEvent = _wsHandlers().onEvent
    onEvent(_notification(1))
    onEvent(_notification(2))
    await store.markAllRead()
    expect(store.unreadCount).toBe(0)
    expect(store.items.every((n: { is_read: boolean }) => n.is_read)).toBe(true)
    store.stop()
  })

  it('stop：断开 WS + 清空状态', () => {
    const store = useNotificationStore()
    store.init()
    const onEvent = _wsHandlers().onEvent
    onEvent(_notification(1))
    store.stop()
    expect(disconnectNotificationWs).toHaveBeenCalled()
    expect(store.items).toEqual([])
    expect(store.unreadCount).toBe(0)
    // stop 后重新 init 允许再订阅
    store.init()
    expect(connectNotificationWs).toHaveBeenCalledTimes(2)
    store.stop()
  })
})
