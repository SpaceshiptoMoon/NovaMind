import { request } from './index'
import type { SearchRequest, SearchResponse, SearchModeListResponse, SearchModelConfigResponse } from './types'

export const searchApi = {
  search(spaceId: number, kbId: number, data: SearchRequest) {
    return request.post<SearchResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search`,
      data,
      120000,
    )
  },

  searchByImage(spaceId: number, kbId: number, file: File, params?: { top_k?: number; score_threshold?: number }) {
    const formData = new FormData()
    formData.append('image', file)
    const query = new URLSearchParams()
    if (params?.top_k) query.set('top_k', String(params.top_k))
    if (params?.score_threshold) query.set('score_threshold', String(params.score_threshold))
    const qs = query.toString()
    const url = `/spaces/${spaceId}/knowledge-bases/${kbId}/search/image${qs ? `?${qs}` : ''}`
    return request.post<SearchResponse>(url, formData, 120000)
  },

  getSearchModes(spaceId: number, kbId: number) {
    return request.get<SearchModeListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search/modes`
    )
  },

  getModelConfig(spaceId: number, kbId: number) {
    return request.get<SearchModelConfigResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search/model-config`
    )
  },
}
