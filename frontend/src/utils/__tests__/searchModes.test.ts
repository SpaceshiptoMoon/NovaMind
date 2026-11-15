import { describe, expect, it } from 'vitest'
import { SEARCH_PRESETS, getPreset, matchPreset } from '../searchModes'

describe('SEARCH_PRESETS', () => {
  it('三档齐备且 mode 与后端 9 模式对齐', () => {
    expect(SEARCH_PRESETS.map((p) => p.key)).toEqual(['semantic', 'hybrid', 'qa'])
    expect(SEARCH_PRESETS.map((p) => p.mode)).toEqual([
      'content_vector',
      'content_hybrid',
      'content_hybrid',
    ])
  })

  it('仅 AI 问答档开启 LLM', () => {
    expect(SEARCH_PRESETS.filter((p) => p.llmEnabled).map((p) => p.key)).toEqual(['qa'])
  })
})

describe('getPreset', () => {
  it('按 key 取预设', () => {
    expect(getPreset('semantic').mode).toBe('content_vector')
  })

  it('未知 key 回落混合档', () => {
    expect(getPreset('nope' as never).key).toBe('hybrid')
  })
})

describe('matchPreset', () => {
  it('向量无 LLM = 语义档', () => {
    expect(matchPreset('content_vector', false).key).toBe('semantic')
  })

  it('混合 + LLM = AI 问答档', () => {
    expect(matchPreset('content_hybrid', true).key).toBe('qa')
  })

  it('混合无 LLM = 混合档', () => {
    expect(matchPreset('content_hybrid', false).key).toBe('hybrid')
  })

  it('专家模式组合（question_* 等）回落混合档回显', () => {
    expect(matchPreset('question_hybrid', false).key).toBe('hybrid')
    expect(matchPreset('all_bm25', true).key).toBe('hybrid')
  })
})
