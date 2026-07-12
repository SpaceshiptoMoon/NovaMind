import { request, default as instance } from '@/api'
import type {
  TestSetListResponse,
  UploadTestSetResponse,
  TestSet,
  TestSetUpdateRequest,
  TestSetCasesResponse,
  EvaluationTaskListResponse,
  EvaluationTask,
  CreateEvaluationTaskRequest,
  CreateEvaluationTaskResponse,
  EvaluationReport,
  SubmitHumanScoresRequest,
  SubmitHumanScoresResponse,
  TaskCancelResponse,
  TaskProgressResponse,
} from '@/api/types'

const BASE = (spaceId: number, kbId: number) =>
  `/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`

export const evaluationApi = {
  getTestSets(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number },
  ): Promise<TestSetListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets`, params as Record<string, unknown>)
  },

  uploadTestSet(
    spaceId: number,
    kbId: number,
    file: File,
    name: string,
  ): Promise<UploadTestSetResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('name', name)
    return instance
      .post<UploadTestSetResponse>(`${BASE(spaceId, kbId)}/test-sets`, formData)
      .then((r) => r.data)
  },

  deleteTestSet(
    spaceId: number,
    kbId: number,
    testSetId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`)
  },

  updateTestSetName(
    spaceId: number,
    kbId: number,
    testSetId: number,
    data: TestSetUpdateRequest,
  ): Promise<TestSet> {
    return request.put(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`, data)
  },

  getTestSetCases(
    spaceId: number,
    kbId: number,
    testSetId: number,
  ): Promise<TestSetCasesResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets/${testSetId}/cases`)
  },

  getTasks(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number; status?: string },
  ): Promise<EvaluationTaskListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks`, params as Record<string, unknown>)
  },

  getTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<EvaluationTask> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  createTask(
    spaceId: number,
    kbId: number,
    data: CreateEvaluationTaskRequest,
  ): Promise<CreateEvaluationTaskResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks`, data)
  },

  deleteTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  cancelTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<TaskCancelResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/cancel`)
  },

  getTaskProgress(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<TaskProgressResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/progress`)
  },

  getReport(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<EvaluationReport> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/report`)
  },

  submitHumanScores(
    spaceId: number,
    kbId: number,
    taskId: number,
    data: SubmitHumanScoresRequest,
  ): Promise<SubmitHumanScoresResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/scores`, data)
  },

  async exportReport(
    spaceId: number,
    kbId: number,
    taskId: number,
    format: 'json' | 'csv' = 'json',
  ): Promise<void> {
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = localStorage.getItem('access_token')
    const url = `${baseURL}${BASE(spaceId, kbId)}/tasks/${taskId}/export?format=${format}`

    const response = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })

    if (!response.ok) throw new Error('瀵煎嚭澶辫触')

    const blob = await response.blob()
    const disposition = response.headers.get('content-disposition')
    let filename = `evaluation_report.${format}`
    if (disposition) {
      const match = disposition.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/)
      if (match && match[1]) filename = match[1].replace(/['"]/g, '')
    }

    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  },
}
