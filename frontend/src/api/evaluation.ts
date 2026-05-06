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

// ===================== 测试集管理 =====================

export const evaluationApi = {
  // 测试集列表
  getTestSets(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number },
  ): Promise<TestSetListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets`, params as Record<string, unknown>)
  },

  // 上传测试集
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
      .post<UploadTestSetResponse>(`${BASE(spaceId, kbId)}/test-sets`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  // 删除测试集
  deleteTestSet(
    spaceId: number,
    kbId: number,
    testSetId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`)
  },

  // 更新测试集名称
  updateTestSetName(
    spaceId: number,
    kbId: number,
    testSetId: number,
    data: TestSetUpdateRequest,
  ): Promise<TestSet> {
    return request.put(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`, data)
  },

  // 预览测试集用例
  getTestSetCases(
    spaceId: number,
    kbId: number,
    testSetId: number,
  ): Promise<TestSetCasesResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets/${testSetId}/cases`)
  },

  // ===================== 测评任务管理 =====================

  // 任务列表
  getTasks(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number; status?: string },
  ): Promise<EvaluationTaskListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks`, params as Record<string, unknown>)
  },

  // 任务详情
  getTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<EvaluationTask> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  // 创建测评任务
  createTask(
    spaceId: number,
    kbId: number,
    data: CreateEvaluationTaskRequest,
  ): Promise<CreateEvaluationTaskResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks`, data)
  },

  // 删除测评任务
  deleteTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  // 取消测评任务
  cancelTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<TaskCancelResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/cancel`)
  },

  // 获取任务执行进度
  getTaskProgress(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<TaskProgressResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/progress`)
  },

  // 获取测评报告
  getReport(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<EvaluationReport> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/report`)
  },

  // 提交人工评分
  submitHumanScores(
    spaceId: number,
    kbId: number,
    taskId: number,
    data: SubmitHumanScoresRequest,
  ): Promise<SubmitHumanScoresResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/scores`, data)
  },

  // 导出测评结果
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

    if (!response.ok) throw new Error('导出失败')

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
