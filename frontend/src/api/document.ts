import { request } from './index'
import type {
  DocumentListResponse,
  UploadDocumentResponse,
  BatchUploadResponse,
  DocumentDetail,
  Chunk,
  ProcessDocumentResponse,
  BatchProcessResponse,
} from './types'

export const documentApi = {
  getDocuments(spaceId: number, kbId: number, params?: { status?: string; skip?: number; limit?: number }) {
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
    return request.get<Chunk[]>(
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

  processDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<ProcessDocumentResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/process`
    )
  },

  batchProcessDocuments(spaceId: number, kbId: number, data?: { document_ids?: number[] }) {
    return request.post<BatchProcessResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/process`,
      data
    )
  },

  reprocessDocument(spaceId: number, kbId: number, docId: number) {
    return request.post<ProcessDocumentResponse>(
      `/spaces/${spaceId}/knowledge-bases/${kbId}/documents/${docId}/reprocess`,
      {}
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
}
