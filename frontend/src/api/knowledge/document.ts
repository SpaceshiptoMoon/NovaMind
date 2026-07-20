import { request, tokenManager } from '../index'
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
} from '../types'

export const documentApi = {
  getDocuments(spaceId: number, kbId: number, params?: { status?: number; skip?: number; limit?: number }) {
    return request.get<DocumentListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      params
    )
  },

  uploadDocument(spaceId: number, kbId: number, file: File | File[], onProgress?: (percent: number) => void) {
    return request.upload<UploadDocumentResponse | BatchUploadResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      file,
      onProgress
    )
  },

  getDocument(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentDetail>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}`
    )
  },

  getDocumentChunks(spaceId: number, kbId: number, docId: number, params?: { skip?: number; limit?: number }) {
    return request.get<ChunkListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/chunks`,
      params as Record<string, unknown>
    )
  },

  async downloadDocument(spaceId: number, kbId: number, docId: number, filename: string) {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/download`
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

  deleteDocument(spaceId: number, kbId: number, docId: number) {
    return request.delete<{ success: boolean; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}`
    )
  },

  batchProcessDocuments(spaceId: number, kbId: number, data?: { document_ids?: number[] }) {
    return request.post<BatchProcessResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/process`,
      data
    )
  },

  cancelDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<{ document_id: number; status: string; message: string }>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/cancel`
    )
  },

  retryDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<ProcessDocumentResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/retry`
    )
  },

  async getDocumentImage(spaceId: number, kbId: number, docId: number): Promise<string> {
    const blob = await request.download(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/image`
    )
    return window.URL.createObjectURL(blob)
  },

  getDocumentTasks(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentTaskItemListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/tasks`
    )
  },

  getDocumentTasksOverview(spaceId: number, kbId: number, params?: { skip?: number; limit?: number }) {
    return request.get<DocumentTaskListResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/document-tasks`,
      params as Record<string, unknown>
    )
  },

  /** 获取文档解析后的 Markdown 全文 */
  async getDocumentParsedText(spaceId: number, kbId: number, docId: number): Promise<string> {
    // 使用原生 fetch 获取文本内容（非 JSON），需手动带上 token
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`

    const response = await fetch(
      `${baseURL}/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/parsed-text`,
      { credentials: 'include', headers }
    )
    if (!response.ok) {
      throw new Error(`获取解析全文失败: ${response.status}`)
    }
    return response.text()
  },

  /** 获取文档视频帧预签名 URL 列表 */
  getDocumentFrames(spaceId: number, kbId: number, docId: number) {
    return request.get<DocumentFramesResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/frames`
    )
  },

  /** 生成文档原始文件预览 URL（用于 <img>/<audio>/iframe 的 src） */
  getDocumentPreviewUrl(spaceId: number, kbId: number, docId: number): string {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    return `${baseURL}/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/preview`
  },
}
