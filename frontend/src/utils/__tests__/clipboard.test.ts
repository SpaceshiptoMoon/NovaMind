// copyToClipboard 单元测试：clipboard API 优先 + execCommand 降级 + 全败返回 false
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { copyToClipboard } from '../clipboard'

describe('copyToClipboard', () => {
  let writeText: ReturnType<typeof vi.fn>
  let execCommand: ReturnType<typeof vi.fn>

  beforeEach(() => {
    writeText = vi.fn()
    execCommand = vi.fn()
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    })
    // jsdom 未实现 execCommand，直接定义以观察降级路径的调用
    Object.defineProperty(document, 'execCommand', {
      value: execCommand,
      configurable: true,
      writable: true,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('clipboard API 成功时直接返回 true，不走降级', async () => {
    writeText.mockResolvedValue(undefined)
    await expect(copyToClipboard('hello')).resolves.toBe(true)
    expect(writeText).toHaveBeenCalledWith('hello')
    expect(execCommand).not.toHaveBeenCalled()
  })

  it('clipboard API 被拒（NotAllowedError）时降级 execCommand 成功', async () => {
    writeText.mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    execCommand.mockReturnValue(true)
    await expect(copyToClipboard('hello')).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('clipboard API 缺失时直接走降级路径', async () => {
    Object.defineProperty(navigator, 'clipboard', {
      value: undefined,
      configurable: true,
      writable: true,
    })
    execCommand.mockReturnValue(true)
    await expect(copyToClipboard('hello')).resolves.toBe(true)
    expect(execCommand).toHaveBeenCalledWith('copy')
  })

  it('两条路径都失败时返回 false 而非抛异常', async () => {
    writeText.mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    execCommand.mockReturnValue(false)
    await expect(copyToClipboard('hello')).resolves.toBe(false)
  })

  it('降级路径用后清理：不留 textarea 残留', async () => {
    writeText.mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    execCommand.mockReturnValue(true)
    await copyToClipboard('hello')
    expect(document.querySelectorAll('textarea')).toHaveLength(0)
  })
})
