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
  WikiAutoFixResponse,
  WikiIssue,
  WikiIssueCreateRequest,
  WikiOverview,
} from '../types'

/**
 * Wiki API
 *
 * 知识库自动生成的 Wiki 域：页面 CRUD、索引/搜索/统计、摄取状态、
 * 来源溯源、版本历史与回滚、重建，以及图谱/lint/问题管理（P3）、空间级概览。
 */
export const wikiApi = {
  /** Wiki 页面列表（分页；可按类型/状态/分类过滤，q 关键词搜索） */
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
    },
  ) {
    return request.get<WikiPageListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages`,
      params,
    )
  },

  /** 按 slug 取 Wiki 页面正文 */
  getPage(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiPage>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`)
  },

  /** 手工新建 Wiki 页面 */
  createPage(spaceId: number, kbId: number, data: WikiPageCreateRequest) {
    return request.post<WikiPage>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages`, data)
  },

  /** 编辑 Wiki 页面（内容/标题/分类等） */
  updatePage(spaceId: number, kbId: number, slug: string, data: WikiPageUpdateRequest) {
    return request.put<WikiPage>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`,
      data,
    )
  },

  /** 删除 Wiki 页面（其入链转为失效链接，由 lint 报告） */
  deletePage(spaceId: number, kbId: number, slug: string) {
    return request.delete<void>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}`)
  },

  /** Wiki 目录树（按 page_type 分组） */
  getIndex(spaceId: number, kbId: number, perPage?: number) {
    return request.get<WikiIndexResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/index`,
      perPage ? { per_page: perPage } : undefined,
    )
  },

  /** Wiki 全文/标题搜索（走 ES 索引） */
  search(spaceId: number, kbId: number, q: string, limit?: number) {
    return request.get<WikiSearchResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/search`,
      { q, limit },
    )
  },

  /** Wiki 健康统计（页数/链接数/孤儿页/是否激活） */
  getStats(spaceId: number, kbId: number) {
    return request.get<WikiStatsResponse>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/stats`)
  },

  /** 摄取流水线状态（各步骤进度/耗时/错误；无任务时返回 null） */
  getIngestStatus(spaceId: number, kbId: number) {
    return request.get<WikiIngestStatusResponse | null>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/ingest/status`,
    )
  },

  /** 页面溯源：生成该页的源文档与 chunk 引用 */
  getPageSources(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiPageSourcesResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/pages/${slug}/sources`,
    )
  },

  /** 页面版本历史列表（含当前版本号） */
  listRevisions(spaceId: number, kbId: number, slug: string) {
    return request.get<WikiRevisionListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revisions/${slug}`,
    )
  },

  /** 指定版本的页面快照内容 */
  getRevision(spaceId: number, kbId: number, slug: string, version: number) {
    return request.get<WikiRevisionDetail>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revisions/${slug}/${version}`,
    )
  },

  /** 回滚页面到指定版本（产生新版本，不改写历史） */
  revert(spaceId: number, kbId: number, slug: string, version: number) {
    return request.post<WikiRevertResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/revert`,
      { slug, version },
    )
  },

  /** 触发 Wiki 重建（从文档重新生成全部页面；不传 document_ids 时全量重建） */
  rebuild(spaceId: number, kbId: number, documentIds?: number[]) {
    return request.post<{ enqueued: number; candidates: number }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/rebuild`,
      documentIds ? { document_ids: documentIds } : {},
    )
  },

  // ==================== P3：图谱 / lint / 问题 ====================

  /** 页面关系图谱（ECharts graph 数据；支持 center/depth 邻域模式） */
  getGraph(
    spaceId: number,
    kbId: number,
    params?: { mode?: string; center?: string; depth?: number; limit?: number },
  ) {
    return request.get<WikiGraphResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/graph`,
      params,
    )
  },

  /** 触发 Wiki 质量体检（死链/孤儿页/冲突别名等，返回健康分） */
  lint(spaceId: number, kbId: number) {
    return request.get<WikiLintResponse>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/lint`)
  },

  /** 一键自动修复可修复的 lint 问题，返回修复明细 */
  autoFix(spaceId: number, kbId: number) {
    return request.post<WikiAutoFixResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/lint/autofix`,
      {},
    )
  },

  /** 问题工单列表（可按状态过滤） */
  listIssues(spaceId: number, kbId: number, status?: string) {
    return request.get<WikiIssue[]>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues`,
      status ? { status } : undefined,
    )
  },

  /** 手工登记 Wiki 问题工单 */
  createIssue(spaceId: number, kbId: number, data: WikiIssueCreateRequest) {
    return request.post<WikiIssue>(`/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues`, data)
  },

  /** 推进问题工单状态（open → in_progress → resolved 等） */
  updateIssueStatus(spaceId: number, kbId: number, issueId: string, status: string) {
    return request.put<WikiIssue>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/wiki/issues/${issueId}/status`,
      { status },
    )
  },

  // ==================== 空间级概览（工作台首页） ====================

  /** 空间级 Wiki 总览（跨知识库聚合页数/健康分/待处理问题，工作台首页） */
  getSpaceWikiOverview(spaceId: number) {
    return request.get<WikiOverview>(`/spaces/${spaceId}/stats/wiki-overview`)
  },
}
