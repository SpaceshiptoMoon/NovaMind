import { request } from '../index'
import type {
  KnowledgeBase,
  KnowledgeBaseListResponse,
  KnowledgeBaseConfigResponse,
  KnowledgeBaseConfigUpdateRequest,
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest,
} from '../types'

export const knowledgeBaseApi = {
  getKnowledgeBases(
    spaceId: number,
    params?: { status?: number; skip?: number; limit?: number }
  ) {
    return request.get<KnowledgeBaseListResponse>(
      `/spaces/${spaceId}/knowledge-bases`,
      params
    )
  },

  getKnowledgeBase(spaceId: number, kbId: number) {
    return request.get<KnowledgeBase>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`
    )
  },

  createKnowledgeBase(spaceId: number, data: CreateKnowledgeBaseRequest) {
    return request.post<KnowledgeBase>(
      `/spaces/${spaceId}/knowledge-bases`,
      data
    )
  },

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

  deleteKnowledgeBase(spaceId: number, kbId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`
    )
  },

  getConfig(spaceId: number, kbId: number) {
    return request.get<KnowledgeBaseConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/config`
    )
  },

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
