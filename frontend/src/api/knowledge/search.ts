import { request } from '../index'
import type {
  SearchRequest,
  SearchResponse,
  SearchModeListResponse,
  SearchModelConfigResponse,
} from '../types'

export const searchApi = {
  search(spaceId: number, kbId: number, data: SearchRequest) {
    return request.post<SearchResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/search`,
      data,
      120000,
    )
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