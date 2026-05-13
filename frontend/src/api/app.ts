/**
 * 简历挖掘 API
 */
import { request } from './index'

const BASE_URL = '/apps'

// 结构化简历类型
export interface PersonalInfo {
  name: string
  phone: string
  email: string
  location: string
  summary: string
}

export interface WorkExperience {
  company: string
  position: string
  department: string
  start_date: string
  end_date: string
  duration_months: number
  is_current: boolean
  responsibilities: string[]
  achievements: { description: string; metric: string; impact: string }[]
  tech_stack: string[]
}

export interface ProjectExperience {
  name: string
  source: string
  role: string
  background: string
  tech_stack: {
    languages: string[]
    frameworks: string[]
    middleware: string[]
    infrastructure: string[]
    tools: string[]
  }
  challenges: { challenge: string; solution: string; result: string }[]
  achievements: { description: string; metric: string; impact: string }[]
  highlights: string[]
}

export interface SkillGroup {
  category: string
  label: string
  items: { name: string; proficiency: string; years: number }[]
}

export interface Paper {
  title: string
  venue: string
  venue_level: string
  publication_date: string
  is_first_author: boolean
  keywords: string[]
}

export interface StructuredResume {
  personal_info: PersonalInfo
  work_experience: WorkExperience[]
  project_experience: ProjectExperience[]
  education: {
    school: string
    major: string
    degree: string
    start_date: string
    end_date: string
    highlights: string[]
  }[]
  skills: {
    skill_groups: SkillGroup[]
  }
  publications: {
    papers: Paper[]
    patents: { title: string; patent_type: string; status: string }[]
  }
}

export interface ResumeSession {
  id: string
  user_id: number
  resume_filename: string
  structured_resume: StructuredResume | null
  jd_text: string
  md_report_url: string | null
  status: number
  config: Record<string, unknown>
  created_at: string | null
  updated_at: string | null
}

export interface ResumeSessionListResponse {
  sessions: ResumeSession[]
  total: number
}

export interface ModelsResponse {
  models: Record<string, { max_tokens: number; temperature: number; top_p: number }>
}

export const appApi = {
  // 获取可用 LLM 模型列表
  getModels() {
    return request.get<ModelsResponse>('/ai-chat/models')
  },

  // 上传简历（使用 axios 实例，自动处理 token 刷新）
  async uploadResume(file: File, jdText?: string, config?: Record<string, unknown>, llmModel?: string) {
    const formData = new FormData()
    formData.append('file', file)
    if (jdText) formData.append('jd_text', jdText)
    if (config) formData.append('config', JSON.stringify(config))
    if (llmModel) formData.append('llm_model', llmModel)

    const { default: axiosInstance } = await import('./index')
    const { data } = await axiosInstance.post<ResumeSession>(
      `${BASE_URL}/resume/upload`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 },
    )
    return data
  },

  // 会话列表
  listSessions(limit = 20, offset = 0, status?: number) {
    return request.get<ResumeSessionListResponse>(`${BASE_URL}/resume/sessions`, { limit, offset, status })
  },

  // 会话详情
  getSession(sessionId: string) {
    return request.get<ResumeSession>(`${BASE_URL}/resume/sessions/${sessionId}`)
  },

  // 获取报告内容（从 MinIO 读取 MD 文本）
  async getReportContent(sessionId: string): Promise<string> {
    const { default: axiosInstance } = await import('./index')
    const { data } = await axiosInstance.get(`${BASE_URL}/resume/sessions/${sessionId}/report`, {
      responseType: 'text',
    })
    return data
  },

  // 删除会话
  deleteSession(sessionId: string) {
    return request.delete<{ message: string }>(`${BASE_URL}/resume/sessions/${sessionId}`)
  },

  // 下载报告
  async downloadReport(sessionId: string) {
    const { default: axiosInstance } = await import('./index')
    const response = await axiosInstance.get(`${BASE_URL}/resume/sessions/${sessionId}/download`, {
      responseType: 'blob',
    })
    // 从 Content-Disposition 提取文件名
    const disposition = response.headers['content-disposition']
    let filename = 'resume_report.md'
    if (disposition) {
      const utf8Match = disposition.match(/filename\*=UTF-8''(.+)/)
      if (utf8Match) {
        filename = decodeURIComponent(utf8Match[1])
      } else {
        const match = disposition.match(/filename="?([^"]+)"?/)
        if (match) filename = match[1]
      }
    }
    // 触发浏览器下载
    const url = URL.createObjectURL(response.data)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  },
}
