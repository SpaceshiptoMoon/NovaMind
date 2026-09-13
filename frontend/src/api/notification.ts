/**
 * 通知 API 模块
 */
import { request, createWsUrl, tokenManager, TOKEN_SYNC_EVENT } from './index'
import type {
  Notification,
  NotificationListResponse,
  UnreadCountResponse,
  NotificationPreference,
} from './types'

const BASE_URL = '/notifications'

export const notificationApi = {
  /** 获取通知列表 */
  getNotifications(params?: { limit?: number; offset?: number; unread_only?: boolean }) {
    return request.get<NotificationListResponse>(BASE_URL, params)
  },

  /** 获取未读通知数 */
  getUnreadCount() {
    return request.get<UnreadCountResponse>(`${BASE_URL}/unread-count`)
  },

  /** 标记单条通知为已读 */
  markRead(id: number) {
    return request.put<{ message: string }>(`${BASE_URL}/${id}/read`)
  },

  /** 标记所有通知为已读 */
  markAllRead() {
    return request.put<{ message: string }>(`${BASE_URL}/read-all`)
  },

  /** 获取通知偏好 */
  getPreferences() {
    return request.get<NotificationPreference>(`${BASE_URL}/preferences`)
  },

  /** 更新通知偏好 */
  updatePreferences(data: Partial<NotificationPreference>) {
    return request.put<NotificationPreference>(`${BASE_URL}/preferences`, data)
  },
}

// ==================== 通知常驻 WS 订阅 ====================
// 不复用 createWebSocketStream（一次性 Promise 语义不匹配常驻订阅）。
// 断线策略：指数退避重连（1s→30s 封顶）；close 4401/4403（token 无效/账号
// 禁用）不重连；25s 心跳 ping，连续 2 次无 pong 主动断开触发重连；
// 网络恢复（online 事件）立即重连；token 清除断开、重新登录重连。

const WS_URL = `${BASE_URL}/ws`
const HEARTBEAT_INTERVAL_MS = 25_000
const MAX_MISSED_PONGS = 2
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 30_000

// WS close code：服务端 ws_authenticate 认证失败（4401 未认证 / 4403 状态不允许）
const WS_CLOSE_UNAUTHENTICATED = 4401
const WS_CLOSE_FORBIDDEN = 4403

let ws: WebSocket | null = null
let retryCount = 0
let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let heartbeatTimer: ReturnType<typeof setInterval> | null = null
let missedPongs = 0
let intentionallyClosed = false
let onlineListener: (() => void) | null = null
let tokenSyncListener: (() => void) | null = null

interface NotificationWsHandlers {
  /** 收到 notification.new 事件（完整通知对象） */
  onEvent: (n: Notification) => void
  /** 连接状态变化（true=已连接），可选 */
  onStateChange?: (connected: boolean) => void
}

let handlers: NotificationWsHandlers | null = null

function stopHeartbeat(): void {
  if (heartbeatTimer !== null) {
    clearInterval(heartbeatTimer)
    heartbeatTimer = null
  }
}

function startHeartbeat(): void {
  stopHeartbeat()
  missedPongs = 0
  heartbeatTimer = setInterval(() => {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    missedPongs++
    if (missedPongs > MAX_MISSED_PONGS) {
      // 连续无 pong：连接假死（nginx 静默断连等），主动断开走重连路径
      ws.close()
      return
    }
    ws.send(JSON.stringify({ action: 'ping' }))
  }, HEARTBEAT_INTERVAL_MS)
}

function scheduleReconnect(): void {
  if (intentionallyClosed || !handlers) return
  if (reconnectTimer !== null) return
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** retryCount, RECONNECT_MAX_MS)
  retryCount++
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connect()
  }, delay)
}

function handleMessage(ev: MessageEvent): void {
  try {
    const event = JSON.parse(ev.data as string) as { type: string; data: unknown }
    if (event.type === 'pong') {
      missedPongs = 0
      return
    }
    if (event.type === 'notification.new' && handlers) {
      handlers.onEvent(event.data as Notification)
    }
  } catch {
    // 非 JSON 帧（不应出现）静默忽略
  }
}

function cleanupSocket(): void {
  stopHeartbeat()
  if (ws) {
    ws.onopen = null
    ws.onmessage = null
    ws.onclose = null
    ws.onerror = null
    ws = null
  }
}

function connect(): void {
  if (!handlers) return
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return

  const token = tokenManager.getToken()
  if (!token) return // 未登录不连

  cleanupSocket()
  const socket = new WebSocket(createWsUrl(WS_URL), [`bearer.${token}`])
  ws = socket

  socket.onopen = () => {
    retryCount = 0
    missedPongs = 0
    handlers?.onStateChange?.(true)
    startHeartbeat()
  }
  socket.onmessage = handleMessage
  socket.onclose = (ev) => {
    handlers?.onStateChange?.(false)
    const code = ev.code
    // token 无效/账号禁用：不重连（等轮询兜底或重新登录）
    if (code === WS_CLOSE_UNAUTHENTICATED || code === WS_CLOSE_FORBIDDEN) {
      intentionallyClosed = true
      cleanupSocket()
      return
    }
    cleanupSocket()
    scheduleReconnect()
  }
  socket.onerror = () => {
    // onclose 会跟着触发，重连逻辑统一在 onclose
  }
}

/** 建立通知 WS 常驻订阅（幂等；未登录时静默不连） */
export function connectNotificationWs(wsHandlers: NotificationWsHandlers): void {
  handlers = wsHandlers
  intentionallyClosed = false

  if (!onlineListener) {
    onlineListener = () => {
      retryCount = 0
      connect()
    }
    window.addEventListener('online', onlineListener)
  }
  if (!tokenSyncListener) {
    tokenSyncListener = () => {
      // token 清除（登出）→ 断开；token 出现（登录/刷新）→ 确保 connected
      if (!tokenManager.getToken()) {
        intentionallyClosed = true
        cleanupSocket()
        socketCloseQuietly()
      } else {
        intentionallyClosed = false
        connect()
      }
    }
    window.addEventListener(TOKEN_SYNC_EVENT, tokenSyncListener)
  }

  connect()
}

function socketCloseQuietly(): void {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.close()
    } catch {
      // 忽略
    }
  }
}

/** 断开通知 WS 订阅并清理全部监听（登出/组件卸载时调用） */
export function disconnectNotificationWs(): void {
  handlers = null
  intentionallyClosed = true
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (onlineListener) {
    window.removeEventListener('online', onlineListener)
    onlineListener = null
  }
  if (tokenSyncListener) {
    window.removeEventListener(TOKEN_SYNC_EVENT, tokenSyncListener)
    tokenSyncListener = null
  }
  socketCloseQuietly()
  cleanupSocket()
}
