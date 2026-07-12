import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

// 创建 Axios 实例
const instance: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
  transformRequest: [
    (data, headers) => {
      if (data instanceof FormData) {
        if (headers && typeof headers.setContentType === 'function') {
          headers.setContentType(false)
        } else if (headers && 'Content-Type' in headers) {
          delete headers['Content-Type']
        }
        return data
      }
      if (typeof data === 'object' && data !== null) {
        return JSON.stringify(data)
      }
      return data
    },
  ],
})

// Token 管理
const TOKEN_KEY = 'access_token'
const REFRESH_TOKEN_KEY = 'refresh_token'

export const tokenManager = {
  getToken: (): string | null => localStorage.getItem(TOKEN_KEY),
  setToken: (token: string): void => localStorage.setItem(TOKEN_KEY, token),
  getRefreshToken: (): string | null => localStorage.getItem(REFRESH_TOKEN_KEY),
  setRefreshToken: (token: string): void => localStorage.setItem(REFRESH_TOKEN_KEY, token),
  clearToken: (): void => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  },
}

// Token 刷新状态管理（防止并发刷新）
let isRefreshing = false
let pendingRequests: ((token: string) => void)[] = []

function onTokenRefreshed(token: string) {
  pendingRequests.forEach((cb) => cb(token))
  pendingRequests = []
}

async function refreshTokenRequest(): Promise<string> {
  const refreshToken = tokenManager.getRefreshToken()
  if (!refreshToken) {
    throw new Error('No refresh token')
  }

  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const { data } = await axios.post(`${baseURL}/user/users/refresh`, {
    refresh_token: refreshToken,
  })

  const { access_token, refresh_token } = data
  tokenManager.setToken(access_token)
  if (refresh_token) {
    tokenManager.setRefreshToken(refresh_token)
  }
  return access_token
}

// 请求拦截器
instance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = tokenManager.getToken()
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器 — 后端直接返回数据，不包裹在 { code, data } 中
instance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const { response } = error

    // 401 且有 refresh_token → 尝试静默刷新
    if (response?.status === 401 && !originalRequest._retry) {
      const refreshToken = tokenManager.getRefreshToken()
      if (!refreshToken) {
        tokenManager.clearToken()
        redirectToLogin()
        return Promise.reject(error)
      }

      if (isRefreshing) {
        // 其他请求排队等待刷新完成
        return new Promise((resolve) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(instance(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await refreshTokenRequest()
        onTokenRefreshed(newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return instance(originalRequest)
      } catch {
        tokenManager.clearToken()
        redirectToLogin()
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    // 统一错误提示（排除 401，上面已处理）
    if (response && response.status !== 401) {
      const errorData = response.data
      const message = errorData?.error?.message || errorData?.message || getDefaultMessage(response.status)
      ElMessage.error(message)
    }

    return Promise.reject(error)
  },
)

function redirectToLogin() {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

function getDefaultMessage(status: number): string {
  const map: Record<number, string> = {
    400: '请求参数错误',
    403: '没有权限执行此操作',
    404: '请求的资源不存在',
    409: '资源冲突',
    422: '参数验证失败',
    500: '服务器内部错误',
  }
  return map[status] || '请求失败'
}

// 导出请求方法 — 响应直接返回 data，不需要 .data.data
export const request = {
  get<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    return instance.get<T>(url, { params }).then((r) => r.data)
  },

  post<T>(url: string, data?: unknown, timeout?: number): Promise<T> {
    return instance.post<T>(url, data, timeout ? { timeout } : undefined).then((r) => r.data)
  },

  put<T>(url: string, data?: unknown): Promise<T> {
    return instance.put<T>(url, data).then((r) => r.data)
  },

  patch<T>(url: string, data?: unknown): Promise<T> {
    return instance.patch<T>(url, data).then((r) => r.data)
  },

  delete<T>(url: string, params?: Record<string, unknown>): Promise<T> {
    return instance.delete<T>(url, { params }).then((r) => r.data)
  },

  // 文件上传（支持单文件和多文件）
  upload<T>(url: string, file: File | File[], onProgress?: (percent: number) => void): Promise<T> {
    const formData = new FormData()
    if (Array.isArray(file)) {
      file.forEach((f) => formData.append('files', f))
    } else {
      formData.append('files', file)
    }
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()

    return new Promise<T>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${baseURL}${url}`, true)

      if (token) {
        xhr.setRequestHeader('Authorization', `Bearer ${token}`)
      }

      xhr.responseType = 'text'
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      }

      xhr.onload = () => {
        const responseText = xhr.responseText || ''
        const contentType = xhr.getResponseHeader('content-type') || ''
        const isJson = contentType.includes('application/json')
        const payload = isJson && responseText ? JSON.parse(responseText) : responseText

        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(payload as T)
          return
        }

        const message =
          payload?.error?.message ||
          payload?.message ||
          payload?.detail ||
          getDefaultMessage(xhr.status)
        ElMessage.error(message)
        reject(new Error(message))
      }

      xhr.onerror = () => {
        const message = '上传请求失败'
        ElMessage.error(message)
        reject(new Error(message))
      }

      xhr.send(formData)
    })
  },

  // 文件下载（返回 blob）
  download(url: string): Promise<Blob> {
    return instance.get(url, { responseType: 'blob' }).then((r) => r.data)
  },
}

// SSE 流式请求工具
export async function createSSEStream(
  url: string,
  body: unknown,
  callbacks: {
    onMessage: (event: { type: string; data: unknown }) => void
    onError?: (error: string) => void
    signal?: AbortSignal
  },
): Promise<void> {
  const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const token = tokenManager.getToken()

  const response = await fetch(`${baseURL}${url}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal: callbacks.signal,
  })

  if (!response.ok) {
    const errorText = await response.text().catch(() => '')
    let message = `请求失败 (${response.status})`
    try {
      const parsed = JSON.parse(errorText)
      message = parsed?.error?.message || parsed?.message || message
    } catch {
      // ignore parse error
    }
    throw new Error(message)
  }

  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEventType = ''
  let currentData = ''

  let yieldScheduled = false
  function yieldToMain() {
    if (yieldScheduled) return
    yieldScheduled = true
    queueMicrotask(() => { yieldScheduled = false })
  }

  function flushEvent(): boolean {
    if (!currentData) {
      currentEventType = ''
      return false
    }
    let dispatched = false
    try {
      const parsed = JSON.parse(currentData)
      if (parsed.type !== undefined) {
        callbacks.onMessage({ type: parsed.type, data: parsed.data ?? parsed })
        dispatched = true
      } else if (parsed.event_type !== undefined) {
        callbacks.onMessage({ type: parsed.event_type, data: parsed.data })
        dispatched = true
      } else if (currentEventType) {
        callbacks.onMessage({ type: currentEventType, data: parsed })
        dispatched = true
      }
    } catch {
      // skip malformed data
    }
    currentEventType = ''
    currentData = ''
    return dispatched
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      flushEvent()
      break
    }

    buffer += decoder.decode(value, { stream: true })
    // 兼容 \r\n 换行
    buffer = buffer.replace(/\r\n/g, '\n')

    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      const trimmed = line.trim()

      if (!trimmed) {
        if (flushEvent()) {
          // 让出执行权，允许 Vue 刷新响应式更新并渲染 DOM
          await new Promise(r => setTimeout(r, 0))
        }
        continue
      }

      if (trimmed.startsWith(':')) continue

      if (trimmed.startsWith('event:')) {
        if (flushEvent()) {
          await new Promise(r => setTimeout(r, 0))
        }
        currentEventType = trimmed.slice(6).trim()
      } else if (trimmed.startsWith('data:')) {
        currentData += trimmed.slice(5).trimStart()
      }
    }
  }
}

export default instance
