import { request } from './index'
import type {
  Space,
  SpaceListResponse,
  SpaceConfigResponse,
  SpaceConfigUpdateRequest,
  CreateSpaceRequest,
  UpdateSpaceRequest,
} from './types'

const BASE_URL = '/spaces'

export const spaceApi = {
  // 获取我的空间列表
  getSpaces(params?: { skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(BASE_URL, params)
  },

  // 获取公开空间列表
  getPublicSpaces(params?: { skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(`${BASE_URL}/public`, params)
  },

  // 搜索知识空间
  searchSpaces(params: { keyword: string; skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(`${BASE_URL}/search`, params as Record<string, unknown>)
  },

  // 创建空间
  createSpace(data: CreateSpaceRequest) {
    return request.post<Space>(BASE_URL, data)
  },

  // 获取空间详情
  getSpace(spaceId: number) {
    return request.get<Space>(`${BASE_URL}/${spaceId}`)
  },

  // 更新空间
  updateSpace(spaceId: number, data: UpdateSpaceRequest) {
    return request.put<Space>(`${BASE_URL}/${spaceId}`, data)
  },

  // 删除空间
  deleteSpace(spaceId: number) {
    return request.delete<{ success: boolean; message: string }>(`${BASE_URL}/${spaceId}`)
  },

  // 获取空间配置
  getConfig(spaceId: number) {
    return request.get<SpaceConfigResponse>(`${BASE_URL}/${spaceId}/config`)
  },

  // 更新空间配置（部分更新）
  updateConfig(spaceId: number, data: SpaceConfigUpdateRequest) {
    return request.patch<SpaceConfigResponse>(`${BASE_URL}/${spaceId}/config`, data)
  },
}
