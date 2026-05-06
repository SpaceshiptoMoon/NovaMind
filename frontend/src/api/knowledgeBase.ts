import { request } from './index'
import type {
  KnowledgeBase,
  KnowledgeBaseListResponse,
  KnowledgeBaseConfigResponse,
  KnowledgeBaseConfigUpdateRequest,
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest,
} from './types'

export const knowledgeBaseApi = {
  // 获取知识库列表
  getKnowledgeBases(
    spaceId: number,
    params?: { status?: number; skip?: number; limit?: number }
  ) {
    return request.get<KnowledgeBaseListResponse>(
      `/spaces/${spaceId}/knowledge-bases`,
      params
    )
  },

  // 获取知识库详情
  getKnowledgeBase(spaceId: number, kbId: number) {
    return request.get<KnowledgeBase>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`
    )
  },

  // 创建知识库
  createKnowledgeBase(spaceId: number, data: CreateKnowledgeBaseRequest) {
    return request.post<KnowledgeBase>(
      `/spaces/${spaceId}/knowledge-bases`,
      data
    )
  },

  // 更新知识库
  updateKnowledgeBase(
    spaceId: number,
    kbId: number,
    data: UpdateKnowledgeBaseRequest
  ) {
    return request.put<KnowledgeBase>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`,
      data
    )
  },

  // 删除知识库
  deleteKnowledgeBase(spaceId: number, kbId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`
    )
  },

  // 获取知识库配置
  getConfig(spaceId: number, kbId: number) {
    return request.get<KnowledgeBaseConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/config`
    )
  },

  // 部分更新知识库配置
  updateConfig(
    spaceId: number,
    kbId: number,
    data: KnowledgeBaseConfigUpdateRequest
  ) {
    return request.patch<KnowledgeBaseConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/config`,
      data
    )
  },
}
