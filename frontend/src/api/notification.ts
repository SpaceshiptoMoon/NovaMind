/**
 * 通知 API 模块
 */
import { request } from './index'
import type {
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
