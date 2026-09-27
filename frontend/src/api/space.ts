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

/**
 * space API
 *
 * 知识空间：我的/公开空间列表、搜索、CRUD 与空间级配置
 */
export const spaceApi = {
  // 获取我的空间列表
  /** 当前用户可见的空间列表（分页） */
  getSpaces(params?: { skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(BASE_URL, params)
  },

  // 获取公开空间列表
  /** visibility=公开 的空间列表（供发现/浏览） */
  getPublicSpaces(params?: { skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(`${BASE_URL}/public`, params)
  },

  // 搜索知识空间
  /** 按关键字搜索空间（keyword 必填） */
  searchSpaces(params: { keyword: string; skip?: number; limit?: number }) {
    return request.get<SpaceListResponse>(`${BASE_URL}/search`, params as Record<string, unknown>)
  },

  // 创建空间
  /** 创建空间（名称必填，可见性与配置可选） */
  createSpace(data: CreateSpaceRequest) {
    return request.post<Space>(BASE_URL, data)
  },

  // 获取空间详情
  /** 空间详情 */
  getSpace(spaceId: number) {
    return request.get<Space>(`${BASE_URL}/${spaceId}`)
  },

  // 更新空间
  /** 更新空间基本信息（名称/可见性/配置） */
  updateSpace(spaceId: number, data: UpdateSpaceRequest) {
    return request.put<Space>(`${BASE_URL}/${spaceId}`, data)
  },

  // 删除空间
  /** 删除空间 */
  deleteSpace(spaceId: number) {
    return request.delete<{ success: boolean; message: string }>(`${BASE_URL}/${spaceId}`)
  },

  // 获取空间配置
  /** 空间配置及统计（文档/chunk 数、存储占用、成员数） */
  getConfig(spaceId: number) {
    return request.get<SpaceConfigResponse>(`${BASE_URL}/${spaceId}/config`)
  },

  // 更新空间配置（部分更新）
  /** 部分更新空间配置（描述/标签/embedding/LLM/ASR 等，只传变更项） */
  updateConfig(spaceId: number, data: SpaceConfigUpdateRequest) {
    return request.patch<SpaceConfigResponse>(`${BASE_URL}/${spaceId}/config`, data)
  },
}
