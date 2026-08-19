import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestUse = vi.fn()
const responseUse = vi.fn()
const axiosCreate = vi.fn()
const axiosPost = vi.fn()
const instanceGet = vi.fn()
const instancePost = vi.fn()
const instancePut = vi.fn()
const instancePatch = vi.fn()
const instanceDelete = vi.fn()
const instanceCall = vi.fn()
const elMessageError = vi.fn()

let requestSuccessHandler: ((config: any) => any) | undefined
let responseErrorHandler: ((error: any) => Promise<unknown>) | undefined
let locationState: { pathname: string; href: string }

const mockInstance = Object.assign(instanceCall, {
  interceptors: {
    request: {
      use: (success: (config: any) => any) => {
        requestSuccessHandler = success
        requestUse(success)
      },
    },
    response: {
      use: (_success: unknown, error: (error: any) => Promise<unknown>) => {
        responseErrorHandler = error
        responseUse(error)
      },
    },
  },
  get: instanceGet,
  post: instancePost,
  put: instancePut,
  patch: instancePatch,
  delete: instanceDelete,
})

vi.mock('axios', () => {
  const axios = {
    create: axiosCreate,
    post: axiosPost,
  }
  return {
    default: axios,
    __esModule: true,
  }
})

vi.mock('element-plus', () => ({
  ElMessage: {
    error: elMessageError,
  },
}))

async function loadApiModule() {
  vi.resetModules()
  return import('../index')
}

function createReader(chunks: string[]) {
  const encoder = new TextEncoder()
  let index = 0
  return {
    read: vi.fn(async () => {
      if (index >= chunks.length) {
        return { done: true, value: undefined }
      }
      return {
        done: false,
        value: encoder.encode(chunks[index++]),
      }
    }),
  }
}

describe('api/index', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    requestSuccessHandler = undefined
    responseErrorHandler = undefined
    locationState = { pathname: '/home', href: '/home' }

    axiosCreate.mockReturnValue(mockInstance)
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: locationState,
    })
    // 重置 MockWebSocket 实例池（class 在下方声明，test 时已赋值）
    MockWebSocket.instances = []
  })

  it('manages tokens in localStorage', async () => {
    const { tokenManager } = await loadApiModule()

    tokenManager.setToken('access')
    tokenManager.setRefreshToken('refresh')

    expect(tokenManager.getToken()).toBe('access')
    expect(tokenManager.getRefreshToken()).toBe('refresh')

    tokenManager.clearToken()

    expect(tokenManager.getToken()).toBeNull()
    expect(tokenManager.getRefreshToken()).toBeNull()
  })

  it('adds Authorization header to outgoing requests when token exists', async () => {
    localStorage.setItem('access_token', 'token-123')
    await loadApiModule()

    const config = requestSuccessHandler?.({ headers: {} })

    expect(config.headers.Authorization).toBe('Bearer token-123')
  })

  it('clears auth and redirects to login on 401 without refresh token', async () => {
    const { tokenManager } = await loadApiModule()
    tokenManager.setToken('access-only')

    const error = {
      config: { headers: {} },
      response: { status: 401 },
    }

    await expect(responseErrorHandler?.(error)).rejects.toBe(error)
    expect(tokenManager.getToken()).toBeNull()
    expect(tokenManager.getRefreshToken()).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('refreshes token and retries the original request on 401', async () => {
    const { tokenManager } = await loadApiModule()
    tokenManager.setToken('expired-access')
    tokenManager.setRefreshToken('refresh-123')

    axiosPost.mockResolvedValue({
      data: {
        access_token: 'new-access',
        refresh_token: 'new-refresh',
      },
    })
    instanceCall.mockResolvedValue({ data: { ok: true } })

    const originalRequest = {
      headers: {},
      _retry: false,
      url: '/secure',
    }
    const error = {
      config: originalRequest,
      response: { status: 401 },
    }

    const result = await responseErrorHandler?.(error)

    expect(axiosPost).toHaveBeenCalledWith('/api/v1/user/users/refresh', {
      refresh_token: 'refresh-123',
    })
    expect(tokenManager.getToken()).toBe('new-access')
    expect(tokenManager.getRefreshToken()).toBe('new-refresh')
    expect(originalRequest.headers.Authorization).toBe('Bearer new-access')
    expect(instanceCall).toHaveBeenCalledWith(originalRequest)
    expect(result).toEqual({ data: { ok: true } })
  })

  it('queues concurrent 401 requests behind a single refresh request', async () => {
    const { tokenManager } = await loadApiModule()
    tokenManager.setToken('expired-access')
    tokenManager.setRefreshToken('refresh-123')

    let resolveRefresh: ((value: unknown) => void) | undefined
    axiosPost.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRefresh = resolve
        }),
    )
    instanceCall.mockResolvedValue({ data: { ok: true } })

    const firstRequest = { headers: {}, _retry: false, url: '/secure/1' }
    const secondRequest = { headers: {}, _retry: false, url: '/secure/2' }

    const firstPromise = responseErrorHandler?.({
      config: firstRequest,
      response: { status: 401 },
    })
    const secondPromise = responseErrorHandler?.({
      config: secondRequest,
      response: { status: 401 },
    })

    expect(axiosPost).toHaveBeenCalledTimes(1)

    resolveRefresh?.({
      data: {
        access_token: 'shared-access',
        refresh_token: 'shared-refresh',
      },
    })

    const [firstResult, secondResult] = await Promise.all([firstPromise, secondPromise])

    expect(tokenManager.getToken()).toBe('shared-access')
    expect(tokenManager.getRefreshToken()).toBe('shared-refresh')
    expect(firstRequest.headers.Authorization).toBe('Bearer shared-access')
    expect(secondRequest.headers.Authorization).toBe('Bearer shared-access')
    expect(instanceCall).toHaveBeenCalledTimes(2)
    expect(firstResult).toEqual({ data: { ok: true } })
    expect(secondResult).toEqual({ data: { ok: true } })
  })

  it('clears auth and redirects when token refresh fails', async () => {
    const { tokenManager } = await loadApiModule()
    tokenManager.setToken('expired-access')
    tokenManager.setRefreshToken('refresh-123')
    axiosPost.mockRejectedValue(new Error('refresh failed'))

    const error = {
      config: { headers: {}, _retry: false },
      response: { status: 401 },
    }

    await expect(responseErrorHandler?.(error)).rejects.toBe(error)
    expect(tokenManager.getToken()).toBeNull()
    expect(tokenManager.getRefreshToken()).toBeNull()
    expect(window.location.href).toBe('/login')
  })

  it('shows backend error messages for non-401 failures', async () => {
    await loadApiModule()

    const error = {
      config: { headers: {} },
      response: {
        status: 403,
        data: {
          error: { message: 'forbidden' },
        },
      },
    }

    await expect(responseErrorHandler?.(error)).rejects.toBe(error)
    expect(elMessageError).toHaveBeenCalledWith('forbidden')
  })

  it('passes auth header to SSE requests and parses event/data payloads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: {
        getReader: () =>
          createReader([
            'event: progress\n',
            'data: {"step":1}\n\n',
            'data: {"type":"done","data":{"ok":true}}\n\n',
          ]),
      },
    })
    vi.stubGlobal('fetch', fetchMock)
    localStorage.setItem('access_token', 'sse-token')

    const { createSSEStream } = await loadApiModule()
    const onMessage = vi.fn()

    await createSSEStream('/chat/stream', { q: 'hi' }, { onMessage })

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: 'Bearer sse-token',
      },
      body: JSON.stringify({ q: 'hi' }),
      signal: undefined,
    })
    expect(onMessage).toHaveBeenNthCalledWith(1, {
      type: 'progress',
      data: { step: 1 },
    })
    expect(onMessage).toHaveBeenNthCalledWith(2, {
      type: 'done',
      data: { ok: true },
    })
  })

  it('throws parsed SSE error messages for non-ok responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: vi.fn().mockResolvedValue(JSON.stringify({ message: 'stream failed' })),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { createSSEStream } = await loadApiModule()

    await expect(
      createSSEStream('/chat/stream', {}, { onMessage: vi.fn() }),
    ).rejects.toThrow('stream failed')
  })

  // ===== createWebSocketStream =====
  // MockWebSocket：捕获构造参数，暴露 onopen/onmessage/onerror/onclose 供测试触发，
  // send/close 为 vi.fn 供断言。实例池供测试取回。
  class MockWebSocket {
    static instances: MockWebSocket[] = []
    url: string
    protocols: string[] | string
    onopen: (() => void) | null = null
    onmessage: ((evt: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    onclose: ((evt: { code: number; reason?: string }) => void) | null = null
    send = vi.fn()
    close = vi.fn()
    readyState = 0
    constructor(url: string, protocols?: string[] | string) {
      this.url = url
      this.protocols = protocols ?? []
      MockWebSocket.instances.push(this)
    }
  }

  it('createWebSocketStream streams content + done frames then resolves on close 1000', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'ws://test.host/api/v1')
    vi.stubGlobal('WebSocket', MockWebSocket)
    localStorage.setItem('access_token', 'test-token')

    const { createWebSocketStream } = await loadApiModule()
    const onMessage = vi.fn()
    const body = { message: 'hi' }

    const promise = createWebSocketStream(
      '/agent/agents/1/ws',
      body,
      { onMessage },
    )

    const ws = MockWebSocket.instances[0]!

    // 构造参数：fullUrl + subprotocols
    expect(ws.url).toBe('ws://test.host/api/v1/agent/agents/1/ws')
    expect(ws.protocols).toEqual(['bearer.test-token'])

    // onopen → ws.send({action:'chat', payload: body})
    ws.onopen!()
    expect(ws.send).toHaveBeenCalledWith(JSON.stringify({ action: 'chat', payload: body }))

    // 喂两帧
    ws.onmessage!({ data: JSON.stringify({ type: 'content', data: { content: 'hi' } }) })
    ws.onmessage!({ data: JSON.stringify({ type: 'done', data: { ok: true } }) })
    // onMessage 经 setTimeout(0) 异步 flush，等一个宏任务
    await new Promise((r) => setTimeout(r, 0))
    expect(onMessage).toHaveBeenNthCalledWith(1, { type: 'content', data: { content: 'hi' } })
    expect(onMessage).toHaveBeenNthCalledWith(2, { type: 'done', data: { ok: true } })

    // close 1000 → promise resolve
    ws.onclose!({ code: 1000 })
    await expect(promise).resolves.toBeUndefined()
  })

  it('createWebSocketStream rejects on auth-failure close code 4401', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'ws://test.host/api/v1')
    vi.stubGlobal('WebSocket', MockWebSocket)
    localStorage.setItem('access_token', 'test-token')

    const { createWebSocketStream } = await loadApiModule()
    const onMessage = vi.fn()

    const promise = createWebSocketStream(
      '/agent/agents/1/ws',
      { message: 'hi' },
      { onMessage },
    )

    const ws = MockWebSocket.instances[0]!
    // 直接 close 4401（握手期认证失败，未 onopen）
    ws.onclose!({ code: 4401, reason: 'unauthorized' })

    await expect(promise).rejects.toThrow('unauthorized')
    expect(onMessage).not.toHaveBeenCalled()
  })

  it('createWebSocketStream resolves and closes ws when AbortSignal already aborted', async () => {
    vi.stubEnv('VITE_API_BASE_URL', 'ws://test.host/api/v1')
    vi.stubGlobal('WebSocket', MockWebSocket)
    localStorage.setItem('access_token', 'test-token')

    const { createWebSocketStream } = await loadApiModule()
    const onMessage = vi.fn()
    const ac = new AbortController()
    ac.abort()

    const promise = createWebSocketStream(
      '/agent/agents/1/ws',
      { message: 'hi' },
      { onMessage, signal: ac.signal },
    )

    // 预先 aborted → 内部 ws.close(1000, 'cancel') + resolve，不触发 onopen/onmessage
    await expect(promise).resolves.toBeUndefined()
    const ws = MockWebSocket.instances[0]!
    expect(ws.close).toHaveBeenCalledWith(1000, 'cancel')
    expect(onMessage).not.toHaveBeenCalled()
  })
})
