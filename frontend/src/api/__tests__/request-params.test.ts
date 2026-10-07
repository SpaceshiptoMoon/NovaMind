/* eslint-disable @typescript-eslint/no-explicit-any -- 测试 mock 拦截器回调类型简化用 any */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const axiosCreate = vi.fn()
const instanceGet = vi.fn()

const mockInstance = {
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
  get: instanceGet,
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}

vi.mock('axios', () => ({
  default: { create: axiosCreate, post: vi.fn() },
  __esModule: true,
}))

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

describe('request.get params 扁平传参契约', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    axiosCreate.mockReturnValue(mockInstance)
    instanceGet.mockResolvedValue({ data: {} })
  })

  async function loadApiModule() {
    vi.resetModules()
    return import('../index')
  }

  it('get 的第二参是扁平 query 对象，直落 axios config.params（不二次包装）', async () => {
    const { request } = await loadApiModule()

    await request.get('/x/chunk-position', { chunk_id: 'doc568_3' })

    expect(instanceGet).toHaveBeenCalledWith('/x/chunk-position', {
      params: { chunk_id: 'doc568_3' },
    })
  })

  it('get 无参调用时 axios config.params 为 undefined', async () => {
    const { request } = await loadApiModule()

    await request.get('/ping')

    expect(instanceGet).toHaveBeenCalledWith('/ping', { params: undefined })
  })

  it('误用形态（{params:{...}} 双层包装）会被序列化成 params[chunk_id]——锁定后端 422 根因形态', async () => {
    // 背景：getChunkPosition 曾写成 request.get(url, { params: { chunk_id } })，
    // 第二参被当作扁平 query 再包一层 → query 变 params[chunk_id]=... → 后端
    // Query(chunk_id) 必 422，且调用方 catch 静默降级零报错表象。
    // 本测试锁定 request.get 的「扁平契约」：调用方永远不该传 { params: {...} }。
    const { request } = await loadApiModule()

    await request.get('/x/chunk-position', { params: { chunk_id: 'doc568_3' } } as any)

    const config = instanceGet.mock.calls[0][1]
    // 双层包装的实际形状：config.params.params 才是真 query——这就是 422 根因
    expect(config.params).toEqual({ params: { chunk_id: 'doc568_3' } })
  })
})
