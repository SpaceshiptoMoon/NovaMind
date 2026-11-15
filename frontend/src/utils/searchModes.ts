/**
 * 检索三档预设：消费侧（全局检索页 / 检索页默认态）的模式映射。
 *
 * 权威 mode id 清单与后端 `backend/src/engines/rag/modes.py` 对齐；
 * 「AI 问答」不是独立 mode，是混合检索 + llm.enabled 的组合。
 */
export type SearchPresetKey = 'semantic' | 'hybrid' | 'qa'

export interface SearchPreset {
  key: SearchPresetKey
  label: string
  /** 映射到的后端检索模式 id */
  mode: string
  /** 是否同时开启 LLM 回答 */
  llmEnabled: boolean
}

export const SEARCH_PRESETS: SearchPreset[] = [
  { key: 'semantic', label: '语义检索', mode: 'content_vector', llmEnabled: false },
  { key: 'hybrid', label: '混合检索', mode: 'content_hybrid', llmEnabled: false },
  { key: 'qa', label: 'AI 问答', mode: 'content_hybrid', llmEnabled: true },
]

const PRESET_BY_KEY = new Map(SEARCH_PRESETS.map((p) => [p.key, p]))

/** 按 key 取预设；未知 key 回落混合档（与后端默认模式一致） */
export function getPreset(key: SearchPresetKey): SearchPreset {
  return PRESET_BY_KEY.get(key) ?? PRESET_BY_KEY.get('hybrid')!
}

/**
 * 反查当前 (mode, llmEnabled) 命中哪一档预设（回显/专家模式切换用）。
 *
 * 专家参数组合（question_ 系、all_ 系模式、或 bm25 + LLM 等）不在三档内，
 * 回落混合档——仅影响分段控件回显，不回写用户已选模式。
 */
export function matchPreset(mode: string, llmEnabled: boolean): SearchPreset {
  if (mode === 'content_vector' && !llmEnabled) return getPreset('semantic')
  if (mode === 'content_hybrid' && llmEnabled) return getPreset('qa')
  return getPreset('hybrid')
}
