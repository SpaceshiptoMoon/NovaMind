import { request } from '../index'
import type {
  SearchRequest,
  SearchResponse,
  SearchModeListResponse,
  SearchModelConfigResponse,
} from '../types'

/**
 * 检索 API
 *
 * 知识库检索入口：多模式检索执行与模式清单、检索所用模型配置查询。
 */
export const searchApi = {
  /** 执行一次检索（9 种模式之一，支持重排/LLM 回答/改写等可选增强）；LLM 增强耗时长，超时放宽到 120s */
  search(spaceId: number, kbId: number, data: SearchRequest) {
    return request.post<SearchResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search`,
      data,
      120000,
    )
  },

  /** 该知识库可用的检索模式清单（前端模式选择器数据源） */
  getSearchModes(spaceId: number, kbId: number) {
    return request.get<SearchModeListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search/modes`,
    )
  },

  /** 检索实际使用的 embedding/LLM/rerank 模型及平台可用清单（检索诊断页展示） */
  getModelConfig(spaceId: number, kbId: number) {
    return request.get<SearchModelConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search/model-config`,
    )
  },
}
