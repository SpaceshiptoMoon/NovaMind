import { request } from '../index'
import type {
  WikiPage,
  WikiPageListResponse,
  WikiIndexResponse,
  WikiStatsResponse,
  WikiIngestStatusResponse,
  WikiPageSourcesResponse,
  WikiSearchResponse,
  WikiRevisionListResponse,
  WikiRevisionDetail,
  WikiPageUpdateRequest,
  WikiPageCreateRequest,
  WikiRevertResponse,
  WikiGraphResponse,
  WikiLintResponse,
  WikiIssue,
  WikiIssueCreateRequest,
} from '../types'

/** Wiki API — 前缀 /spaces/{spaceId}/knowledge-bases/{kbId}/wiki */
export const wikiApi = {
  listPages(
    spaceId: number,
    kbId: number,
    params?: {
      page?: number
      page_size?: number
      page_type?: string
      status?: string
      category?: string
      q?: string
    }
  ) {
    return request.get<WikiPageListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages`,
      params
    )
  },

  getPage(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiPage>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`
    )
  },

  createPage(spaceId: number, kbId: number, data: WikiPageCreateRequest) {
    return request.post<WikiPage>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages`,
      data
    )
  },

  updatePage(
    spaceId: number,
    kbId: number,
    slug: string,
    data: WikiPageUpdateRequest
  ) {
    return request.put<WikiPage>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`,
      data
    )
  },

  deletePage(spaceId: number, kbId: number, slug: string) {
    return request.delete<void>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`
    )
  },

  getIndex(spaceId: number, kbId: number, perPage?: number) {
    return request.get<WikiIndexResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/index`,
      perPage ? { per_page: perPage } : undefined
    )
  },

  search(spaceId: number, kbId: number, q: string, limit?: number) {
    return request.get<WikiSearchResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/search`,
      { q, limit }
    )
  },

  getStats(spaceId: number, kbId: number) {
    return request.get<WikiStatsResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/stats`
    )
  },

  getIngestStatus(spaceId: number, kbId: number) {
    return request.get<WikiIngestStatusResponse | null>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/ingest/status`
    )
  },

  getPageSources(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiPageSourcesResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}/sources`
    )
  },

  listRevisions(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiRevisionListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revisions/${slug}`
    )
  },

  getRevision(spaceId: number, kbId: number, slug: string, version: number) {
    return request.get<WikiRevisionDetail>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revisions/${slug}/${version}`
    )
  },

  revert(spaceId: number, kbId: number, slug: string, version: number) {
    return request.post<WikiRevertResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revert`,
      { slug, version }
    )
  },

  rebuild(spaceId: number, kbId: number, documentIds?: number[]) {
    return request.post<{ enqueued: number; candidates: number }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/rebuild`,
      documentIds ? { document_ids: documentIds } : {}
    )
  },

  // ==================== P3：图谱 / lint / 问题 ====================

  getGraph(
    spaceId: number,
    kbId: number,
    params?: { mode?: string; center?: string; depth?: number; limit?: number }
  ) {
    return request.get<WikiGraphResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/graph`,
      params
    )
  },

  lint(spaceId: number, kbId: number) {
    return request.get<WikiLintResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/lint`
    )
  },

  listIssues(spaceId: number, kbId: number, status?: string) {
    return request.get<WikiIssue[]>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues`,
      status ? { status } : undefined
    )
  },

  createIssue(spaceId: number, kbId: number, data: WikiIssueCreateRequest) {
    return request.post<WikiIssue>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues`,
      data
    )
  },

  updateIssueStatus(spaceId: number, kbId: number, issueId: string, status: string) {
    return request.put<WikiIssue>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues/${issueId}/status`,
      { status }
    )
  },
}
