import { request, instance } from '../index'
import type {
  DocumentListResponse,
  UploadDocumentResponse,
  BatchUploadResponse,
  DocumentDetail,
  ChunkListResponse,
  ProcessDocumentResponse,
  BatchProcessResponse,
  DocumentTaskListResponse,
  DocumentTaskItemListResponse,
  DocumentFramesResponse,
  ChunkPositionResponse,
} from '../types'

/**
 * 文档 API
 *
 * 知识库内文档全生命周期：上传、解析任务（触发/取消/重试）、
 * 分块查询、原文/解析产物（Markdown/图片/视频帧）下载与预览。
 */
export const documentApi = {
  /** 文档列表（分页；可按解析状态与文件名关键词过滤） */
  getDocuments(
    spaceId: number,
    kbId: number,
    params?: { status?: number; keyword?: string; skip?: number; limit?: number },
  ) {
    return request.get<DocumentListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      params,
    )
  },

  /** 上传文档（传单文件返回单文档结果，传数组走批量上传合并结果）；onProgress 回调上传进度百分比 */
  uploadDocument(
    spaceId: number,
    kbId: number,
    file: File | File[],
    onProgress?: (percent: number) => void,
  ) {
    return request.upload<UploadDocumentResponse | BatchUploadResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      file,
      onProgress,
    )
  },

  /** 文档详情（元信息与解析状态） */
  getDocument(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentDetail>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}`,
    )
  },

  /** 按 space + docId 反查归属知识库（文档详情页裸链接无 kbId query 时用） */
  getDocumentKbId(spaceId: number, docId: number) {
    return request.get<{ kb_id: number; document_id: number }>(
      `/spaces/${spaceId}/documents/${docId}/kb-id`,
    )
  },

  /** 分块列表（分页；含 chunk_type 媒体分块标记） */
  getDocumentChunks(
    spaceId: number,
    kbId: number,
    docId: number,
    params?: { skip?: number; limit?: number },
  ) {
    return request.get<ChunkListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/chunks`,
      params as Record<string, unknown>,
    )
  },

  /** 下载文档原始文件并触发浏览器保存 */
  async downloadDocument(spaceId: number, kbId: number, docId: number, filename: string) {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/download`,
    )
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  },

  /** 删除文档（连同其分块/向量/媒体产物） */
  deleteDocument(spaceId: number, kbId: number, docId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}`,
    )
  },

  /** 批量触发解析；不传 document_ids 时对全部文档生效，返回逐文档成败明细 */
  batchProcessDocuments(spaceId: number, kbId: number, data?: { document_ids?: number[] }) {
    return request.post<BatchProcessResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/process`,
      data,
    )
  },

  /** 取消进行中的解析任务 */
  cancelDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<{ document_id: number; status: string; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/cancel`,
    )
  },

  /** 重试解析（失败/取消的文档重新排队） */
  retryDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<ProcessDocumentResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/retry`,
    )
  },

  /** 获取文档封面图 Blob URL（图片类文档预览用，调用方负责 revokeObjectURL） */
  async getDocumentImage(spaceId: number, kbId: number, docId: number): Promise<string> {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/image`,
    )
    return window.URL.createObjectURL(blob)
  },

  /** 单文档的解析任务明细（每步解析子任务的状态） */
  getDocumentTasks(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentTaskItemListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/tasks`,
    )
  },

  /** 知识库维度解析任务总览（跨文档的任务列表，分页） */
  getDocumentTasksOverview(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number },
  ) {
    return request.get<DocumentTaskListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/document-tasks`,
      params as Record<string, unknown>,
    )
  },

  /** 下载文档解析后的 Markdown 全文（attachment，文件名由后端 Content-Disposition 提供） */
  async downloadDocumentParsedText(spaceId: number, kbId: number, docId: number, filename: string) {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/parsed-text/download`,
    )
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  },

  /** 获取文档解析后的 Markdown 全文 */
  async getDocumentParsedText(spaceId: number, kbId: number, docId: number): Promise<string> {
    // 使用 axios 统一拦截器（自动带 token、自动刷新），获取 text/markdown 响应
    const response = await instance.get(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/parsed-text`,
      { responseType: 'text', headers: { Accept: 'text/markdown' } },
    )
    return typeof response.data === 'string' ? response.data : String(response.data)
  },

  /** 获取文档视频帧预签名 URL 列表 */
  getDocumentFrames(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentFramesResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/frames`,
    )
  },

  /** 获取文档原始文件预览 Blob URL（带认证） */
  async getDocumentPreviewBlobUrl(spaceId: number, kbId: number, docId: number): Promise<string> {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/preview`,
    )
    return window.URL.createObjectURL(blob)
  },

  /** 查询 chunk 在 PDF 原文中的位置（页码 + bbox 矩形，引用溯源高亮） */
  getChunkPosition(spaceId: number, kbId: number, docId: number, chunkId: string) {
    return request.get<ChunkPositionResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/chunk-position`,
      { params: { chunk_id: chunkId } },
    )
  },
}
