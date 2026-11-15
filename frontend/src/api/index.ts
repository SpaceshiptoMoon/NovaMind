/**
 * HTTP 客户端与流式请求基础设施
 *
 * 集中提供：axios 实例（自动附 Authorization、401 静默刷新重放）、
 * `request` 类型化请求方法、SSE/WS 流式工具。所有 api 模块经此发请求，
 * 禁止裸用 axios。
 */
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

// token 被拦截器刷新/清除时派发，供 store 同步响应式镜像
export const TOKEN_SYNC_EVENT = 'novamind:token-sync'

/** 派发令牌同步事件（localStorage 无响应性，store 监听此事件镜像状态） */
function emitTokenSync() {
  window.dispatchEvent(new CustomEvent(TOKEN_SYNC_EVENT))
}

/** 访问/刷新令牌的 localStorage 存取（无响应性，响应式镜像见 stores/user） */
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
let pendingRejectors: ((error: unknown) => void)[] = []

function onTokenRefreshed(token: string) {
  pendingRequests.forEach((cb) => cb(token))
  pendingRequests = []
  pendingRejectors = []
}

function onTokenRefreshFailed() {
  pendingRejectors.forEach((reject) => reject(new Error('登录状态已失效，请重新登录')))
  pendingRequests = []
  pendingRejectors = []
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
  emitTokenSync()
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

// 认证失败响应不该触发静默刷新的端点（密码错误 ≠ token 过期）
const AUTH_ENDPOINTS = ['/users/login', '/users/register', '/users/refresh']

// 响应拦截器 — 后端直接返回数据，不包裹在 { code, data } 中
instance.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    const { response } = error
    const isAuthEndpoint = AUTH_ENDPOINTS.some((ep) => (originalRequest?.url || '').includes(ep))

    // 401 且非认证端点且有 refresh_token → 尝试静默刷新
    if (response?.status === 401 && !originalRequest._retry && !isAuthEndpoint) {
      const refreshToken = tokenManager.getRefreshToken()
      if (!refreshToken) {
        tokenManager.clearToken()
        emitTokenSync()
        redirectToLogin()
        return Promise.reject(error)
      }

      if (isRefreshing) {
        // 其他请求排队等待刷新完成
        return new Promise((resolve, reject) => {
          pendingRequests.push((token: string) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(instance(originalRequest))
          })
          // 刷新失败时释放排队请求，避免 Promise 永久挂起
          pendingRejectors.push(reject)
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const newToken = await refreshTokenRequest()
        onTokenRefreshed(newToken)
        originalRequest.headers.Authorization = `Bearer ${newToken}`
        return instance(originalRequest)
      } catch (refreshError) {
        tokenManager.clearToken()
        emitTokenSync()
        // 释放排队请求（若不释放，这些 Promise 永远 pending）
        onTokenRefreshFailed()
        redirectToLogin()
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    // 强制改密：跳转改密页（后端 PASSWORD_CHANGE_REQUIRED，403）
    const errorCode = response?.data?.error?.code
    if (errorCode === 'PASSWORD_CHANGE_REQUIRED') {
      if (window.location.pathname !== '/home/change-password') {
        window.location.href = '/home/change-password?forced=1'
      }
      return Promise.reject(error)
    }

    // 统一错误提示（排除 401，上面已处理）
    if (response && response.status !== 401) {
      const errorData = response.data
      const detailsMessage = Array.isArray(errorData?.error?.details)
        ? errorData.error.details
            .map((d: { message?: string }) => d?.message)
            .filter(Boolean)
            .join('；')
        : ''
      const message =
        detailsMessage ||
        errorData?.error?.message ||
        errorData?.message ||
        getDefaultMessage(response.status)
      ElMessage.error(message)
    } else if (!response) {
      // 网络层失败（断网/超时/DNS/连接拒绝）：无 response 对象，此前静默吞掉，
      // 用户在 UI 上看到的是"点了保存没反应"（评审 P1：保存失败零反馈）
      ElMessage.error('网络异常，请检查连接后重试')
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

/**
 * 流式计算文件 sha256（hex）：File.slice 逐块读，内存峰值与文件大小解耦。
 *
 * Web Crypto 无增量摘要 API——单块 4MB 收集后一次 digest；大文件把全部块的
 * ArrayBuffer 拼进一个 Uint8Array 再喂（File.slice 是引用，物化发生在
 * arrayBuffer() 调用时，浏览器内部按块搬运）。分片上传的完整性凭证，
 * complete 时与后端重组文件的 sha256 比对。
 */
async function sha256File(file: File | Blob): Promise<string> {
  const BLOCK = 4 * 1024 * 1024
  const parts: Blob[] = []
  for (let offset = 0; offset < file.size; offset += BLOCK) {
    parts.push(file.slice(offset, offset + BLOCK))
  }
  let input: ArrayBuffer
  if (parts.length === 1 && parts[0]) {
    input = await parts[0].arrayBuffer()
  } else {
    const total = new Uint8Array(file.size)
    let pos = 0
    for (const p of parts) {
      total.set(new Uint8Array(await p.arrayBuffer()), pos)
      pos += p.size
    }
    input = total.buffer
  }
  const digest = await crypto.subtle.digest('SHA-256', input)
  return Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

// 导出请求方法 — 响应直接返回 data，不需要 .data.data
/**
 * 类型化请求方法集：泛型直接落到响应体，错误统一 toast + reject
 *
 * 401 时自动用 refresh token 静默续期并重放原请求（并发请求共享一次刷新）；
 * `upload` 走 XHR 以支持上传进度回调。
 */
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
      // 大视频（2GB 级）上传远超 axios 默认 30s；无超时会让网络中断的请求
      // 永久挂起在 UI「上传中」。按 2GB/1MBps 的保守带宽给 2h 硬顶。
      xhr.timeout = 2 * 60 * 60 * 1000
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

      xhr.ontimeout = () => {
        const message = '上传超时，请检查网络后重试'
        ElMessage.error(message)
        reject(new Error(message))
      }

      xhr.send(formData)
    })
  },

  /**
   * 分片上传（大文件）：init → 逐片 PUT（固定 offset，乱序/重试安全）→ complete。
   *
   * 单片 XHR timeout 120s + 失败重试 2 次（指数退避 1s/2s）；进度按已确认字节
   * 聚合计算（重试片不虚增进度）。整文件 sha256 由本函数流式计算（File.slice
   * 逐块读，内存峰值与文件大小解耦），与 complete 申报值比对不符后端拒入。
   *
   * @param urls 四端点路径构造器（调用方注入，本函数不耦合具体路由前缀）
   * @param file 待上传文件
   * @param options chunkSize 分片大小（默认 16MB）；onProgress 聚合进度回调
   */
  async uploadChunked<T>(
    urls: {
      init: string
      chunk: (uploadId: string, index: number) => string
      complete: (uploadId: string) => string
      abort: (uploadId: string) => string
    },
    file: File,
    options?: { chunkSize?: number; onProgress?: (percent: number) => void },
  ): Promise<T> {
    const chunkSize = options?.chunkSize ?? 16 * 1024 * 1024
    const onProgress = options?.onProgress
    const baseURL = import.meta.env.VITE_API_BASE_URL || '/api/v1'
    const token = tokenManager.getToken()

    const fileSha256 = await sha256File(file)
    const totalChunks = Math.max(1, Math.ceil(file.size / chunkSize))

    const initRes = await instance.post<{
      upload_id: string
      chunk_size_hint: number
    }>(urls.init, {
      filename: file.name,
      total_size: file.size,
      total_chunks: totalChunks,
      file_sha256: fileSha256,
    })
    const uploadId = initRes.data.upload_id
    const serverHint = initRes.data.chunk_size_hint
    // 服务端步长与本端不一致时以服务端固定 offset 布局为准（同一布局才能拼回）
    const effectiveChunkSize = serverHint > 0 ? serverHint : chunkSize
    const effectiveTotalChunks = Math.max(1, Math.ceil(file.size / effectiveChunkSize))

    let confirmedBytes = 0
    const reportProgress = () => {
      if (onProgress) {
        onProgress(Math.round((confirmedBytes / file.size) * 100))
      }
    }

    const putOneChunk = async (index: number): Promise<void> => {
      const start = index * effectiveChunkSize
      const blob = file.slice(start, Math.min(start + effectiveChunkSize, file.size))
      const bytes = blob.size

      let lastError: Error | null = null
      for (let attempt = 0; attempt <= 2; attempt++) {
        if (attempt > 0) {
          await new Promise((r) => setTimeout(r, 1000 * attempt))
        }
        try {
          await new Promise<void>((resolve, reject) => {
            const xhr = new XMLHttpRequest()
            xhr.open('PUT', `${baseURL}${urls.chunk(uploadId, index)}`, true)
            if (token) {
              xhr.setRequestHeader('Authorization', `Bearer ${token}`)
            }
            xhr.responseType = 'text'
            xhr.timeout = 120 * 1000
            xhr.onload = () => {
              if (xhr.status >= 200 && xhr.status < 300) {
                confirmedBytes += bytes
                reportProgress()
                resolve()
                return
              }
              const contentType = xhr.getResponseHeader('content-type') || ''
              let message = getDefaultMessage(xhr.status)
              try {
                const payload = contentType.includes('application/json') && xhr.responseText
                  ? JSON.parse(xhr.responseText)
                  : null
                message = payload?.error?.message || payload?.message || payload?.detail || message
              } catch {
                /* 保留默认消息 */
              }
              reject(new Error(message))
            }
            xhr.onerror = () => reject(new Error('分片上传请求失败'))
            xhr.ontimeout = () => reject(new Error('分片上传超时'))
            xhr.send(blob)
          })
          return
        } catch (err) {
          lastError = err instanceof Error ? err : new Error(String(err))
        }
      }
      throw lastError ?? new Error('分片上传失败')
    }

    try {
      for (let i = 0; i < effectiveTotalChunks; i++) {
        await putOneChunk(i)
      }
      const completeRes = await instance.post<T>(urls.complete(uploadId), {
        file_sha256: fileSha256,
      })
      onProgress?.(100)
      return completeRes.data
    } catch (err) {
      // 失败即取消会话（best-effort；后端 TTL/cron 也会兜底清理）
      instance.post(urls.abort(uploadId), {}).catch(() => undefined)
      const message = err instanceof Error ? err.message : '分片上传失败'
      ElMessage.error(message)
      throw err
    }
  },

  // 文件下载（返回 blob）
  download(url: string): Promise<Blob> {
    return instance.get(url, { responseType: 'blob' }).then((r) => r.data)
  },
}

// WS URL 拼接：http(s):// → ws(s)://；相对路径（如 /api/v1）用当前页协议+host
// 拼绝对 WS URL：http(s)→ws(s)，相对路径用当前页协议+host。通知常驻订阅共用。
export function createWsUrl(url: string): string {
  const apiBase = import.meta.env.VITE_API_BASE_URL || '/api/v1'
  const wsBase = apiBase.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:')
  if (/^wss?:\/\//.test(wsBase)) {
    return wsBase + url
  }
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${wsBase}${url}`
}

export { instance }
export default instance
