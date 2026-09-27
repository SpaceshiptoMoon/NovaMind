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
  EvaluationComparisonResponse,
  SubmitHumanScoresRequest,
  SubmitHumanScoresResponse,
  TaskCancelResponse,
  TaskProgressResponse,
} from '@/api/types'

const BASE = (spaceId: number, kbId: number) =>
  `/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`

/**
 * 评测 API
 *
 * RAG 检索质量评估：测试集管理（上传/用例沉淀）、评测任务（创建/取消/进度）、
 * 报告查看/导出、两次报告对比、人工评分提交。
 */
export const evaluationApi = {
  /** 测试集列表（分页） */
  getTestSets(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number },
  ): Promise<TestSetListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets`, params as Record<string, unknown>)
  },

  /** 上传测试集文件（xlsx/json），后端解析出问答用例 */
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

  /** 删除测试集（不影响已创建的评测任务） */
  deleteTestSet(
    spaceId: number,
    kbId: number,
    testSetId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`)
  },

  /** 重命名测试集 */
  updateTestSetName(
    spaceId: number,
    kbId: number,
    testSetId: number,
    data: TestSetUpdateRequest,
  ): Promise<TestSet> {
    return request.put(`${BASE(spaceId, kbId)}/test-sets/${testSetId}`, data)
  },

  /** 测试集内的全部问答用例 */
  getTestSetCases(spaceId: number, kbId: number, testSetId: number): Promise<TestSetCasesResponse> {
    return request.get(`${BASE(spaceId, kbId)}/test-sets/${testSetId}/cases`)
  },

  /** 用用例列表直接建测试集（QA 消息沉淀，批次 3a） */
  createTestSetFromCases(
    spaceId: number,
    kbId: number,
    data: { name: string; cases: Array<{ question: string; expected_answer: string }> },
  ): Promise<UploadTestSetResponse> {
    return request.post(`${BASE(spaceId, kbId)}/test-sets/from-cases`, data)
  },

  /** 追加用例进已有测试集（批次 3a） */
  appendCasesToTestSet(
    spaceId: number,
    kbId: number,
    testSetId: number,
    data: { cases: Array<{ question: string; expected_answer: string }> },
  ): Promise<UploadTestSetResponse> {
    return request.post(`${BASE(spaceId, kbId)}/test-sets/${testSetId}/cases`, data)
  },

  /** 评测任务列表（分页；可按状态过滤） */
  getTasks(
    spaceId: number,
    kbId: number,
    params?: { skip?: number; limit?: number; status?: string },
  ): Promise<EvaluationTaskListResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks`, params as Record<string, unknown>)
  },

  /** 评测任务详情（配置与状态） */
  getTask(spaceId: number, kbId: number, taskId: number): Promise<EvaluationTask> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  /** 两次报告对比（批次 3b：同测试集且均 completed） */
  getReportComparison(
    spaceId: number,
    kbId: number,
    taskId: number,
    baselineTaskId: number,
  ): Promise<EvaluationComparisonResponse> {
    return request.get(
      `${BASE(spaceId, kbId)}/tasks/${taskId}/report/compare`,
      { baseline_task_id: baselineTaskId } as Record<string, unknown>,
    )
  },

  /** 创建评测任务：对指定测试集按配置跑检索+生成评估，返回任务句柄 */
  createTask(
    spaceId: number,
    kbId: number,
    data: CreateEvaluationTaskRequest,
  ): Promise<CreateEvaluationTaskResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks`, data)
  },

  /** 删除评测任务及其报告 */
  deleteTask(
    spaceId: number,
    kbId: number,
    taskId: number,
  ): Promise<{ success: boolean; message: string }> {
    return request.delete(`${BASE(spaceId, kbId)}/tasks/${taskId}`)
  },

  /** 取消运行中的评测任务 */
  cancelTask(spaceId: number, kbId: number, taskId: number): Promise<TaskCancelResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/cancel`)
  },

  /** 评测执行进度（当前/总数，轮询展示用） */
  getTaskProgress(spaceId: number, kbId: number, taskId: number): Promise<TaskProgressResponse> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/progress`)
  },

  /** 评测报告（检索/生成各项指标） */
  getReport(spaceId: number, kbId: number, taskId: number): Promise<EvaluationReport> {
    return request.get(`${BASE(spaceId, kbId)}/tasks/${taskId}/report`)
  },

  /** 提交人工评分（对任务内用例逐条打分，计入报告） */
  submitHumanScores(
    spaceId: number,
    kbId: number,
    taskId: number,
    data: SubmitHumanScoresRequest,
  ): Promise<SubmitHumanScoresResponse> {
    return request.post(`${BASE(spaceId, kbId)}/tasks/${taskId}/scores`, data)
  },

  /** 导出评测报告文件（json/csv），从 Content-Disposition 解析文件名并触发浏览器保存 */
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
