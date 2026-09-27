import { request } from '../index'
import type {
  KnowledgeBase,
  KnowledgeBaseListResponse,
  KnowledgeBaseConfigResponse,
  KnowledgeBaseConfigUpdateRequest,
  CreateKnowledgeBaseRequest,
  UpdateKnowledgeBaseRequest,
} from '../types'

/**
 * 知识库 API
 *
 * 知识库实体的增删改查，以及解析/切分/检索等 KB 级配置的读写。
 */
export const knowledgeBaseApi = {
  /** 知识库列表（分页；可按状态过滤） */
  getKnowledgeBases(spaceId: number, params?: { status?: number; skip?: number; limit?: number }) {
    return request.get<KnowledgeBaseListResponse>(`/spaces/${spaceId}/knowledge-bases`, params)
  },

  /** 知识库详情（含统计与配置快照） */
  getKnowledgeBase(spaceId: number, kbId: number) {
    return request.get<KnowledgeBase>(`/spaces/${spaceId}/knowledge-bases/${kbId}`)
  },

  /** 创建知识库 */
  createKnowledgeBase(spaceId: number, data: CreateKnowledgeBaseRequest) {
    return request.post<KnowledgeBase>(`/spaces/${spaceId}/knowledge-bases`, data)
  },

  /** 更新知识库基础信息（名称/描述等） */
  updateKnowledgeBase(spaceId: number, kbId: number, data: UpdateKnowledgeBaseRequest) {
    return request.put<KnowledgeBase>(`/spaces/${spaceId}/knowledge-bases/${kbId}`, data)
  },

  /** 删除知识库（连同其文档/分块/索引产物） */
  deleteKnowledgeBase(spaceId: number, kbId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}`,
    )
  },

  /** 读取 KB 级配置（切分/解析/检索参数）与统计 */
  getConfig(spaceId: number, kbId: number) {
    return request.get<KnowledgeBaseConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/config`,
    )
  },

  /** 局部更新 KB 配置（PATCH 语义，只改传入的配置段） */
  updateConfig(spaceId: number, kbId: number, data: KnowledgeBaseConfigUpdateRequest) {
    return request.patch<KnowledgeBaseConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/config`,
      data,
    )
  },
}
