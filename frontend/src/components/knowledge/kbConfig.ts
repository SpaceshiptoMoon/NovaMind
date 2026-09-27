/** 知识库配置辅助：文本/图片/视频解析策略与 Wiki 生成配置的表单 ↔ 后端 config 双向转换 */
import type { TextParsingConfig, WikiGenerationConfig } from '@/api/types'

/** 文本解析策略：default（内置 reader）或 deepdoc */
export type TextStrategy = 'default' | 'deepdoc'
/** 图片解析策略：VLM 描述或 DeepDoc OCR */
export type ImageStrategy = 'vlm' | 'deepdoc_ocr'
/** 视频解析策略：5 种抽帧/去重/描述组合预设 */
export type VideoStrategy = 'simple' | 'scene' | 'dedup' | 'grouped' | 'rewrite'

/** 视频解析策略选项（5 预设映射到抽帧/去重/描述三阶段组合）。 */
export const videoStrategyItems: Array<{
  value: VideoStrategy
  label: string
  desc: string
  disabled?: boolean
}> = [
  { value: 'simple', label: '逐帧描述', desc: '固定间隔抽帧 + 逐帧单图描述（默认）' },
  { value: 'scene', label: '场景抽帧', desc: '按镜头切换点抽帧 + 逐帧描述' },
  { value: 'dedup', label: '相似去重', desc: '固定间隔 + 相似帧去重 + 逐帧描述' },
  { value: 'grouped', label: '分组描述', desc: '多帧一组喂 VLM 多图生成连贯描述' },
  { value: 'rewrite', label: '重写连贯', desc: '逐帧描述后 LLM 重写润色（保留时间锚点）' },
]

/** 校验视频策略枚举，非法值回退默认 simple */
export function getVideoStrategyValue(value: unknown): VideoStrategy {
  const allowed: VideoStrategy[] = ['simple', 'scene', 'dedup', 'grouped', 'rewrite']
  return (allowed as string[]).includes(value as string) ? (value as VideoStrategy) : 'simple'
}

/** 各文本类型解析策略在表单里的字段名（pdf 除外，pdf 单独带 OCR 开关） */
export type TextStrategyField =
  | 'docxStrategy'
  | 'excelStrategy'
  | 'pptStrategy'
  | 'epubStrategy'
  | 'markdownStrategy'
  | 'htmlStrategy'
  | 'txtStrategy'
  | 'jsonStrategy'

/** 文本类型策略选项；deepdocOnly 标记的类型（Excel/PPT/EPUB）后端 default 模式
 * 无 reader，仅支持 DeepDoc，前端不显示「默认」选项。 */
export const textStrategyItems: Array<{
  key: TextStrategyField
  label: string
  deepdocOnly?: boolean
}> = [
  { key: 'docxStrategy', label: 'DOCX' },
  { key: 'excelStrategy', label: 'Excel', deepdocOnly: true },
  { key: 'pptStrategy', label: 'PPT', deepdocOnly: true },
  { key: 'epubStrategy', label: 'EPUB', deepdocOnly: true },
  { key: 'markdownStrategy', label: 'Markdown' },
  { key: 'htmlStrategy', label: 'HTML' },
  { key: 'txtStrategy', label: 'TXT' },
  { key: 'jsonStrategy', label: 'JSON' },
]

/** 校验文本策略枚举，仅接受 deepdoc，其余回退 default */
export function getTextStrategyValue(value: unknown): TextStrategy {
  return value === 'deepdoc' ? 'deepdoc' : 'default'
}

/**
 * 问题生成的系统默认提示词模板（用于占位提示）。
 *
 * 后端实际默认模板见 `backend/src/features/knowledge_space/prompts/templates.py`
 * 的 `kb_default_question`（英文，使用 {content}/{count} 单花括号占位符，经
 * PromptManager.format_prompt 渲染）。这里给出其中文对照版本，并改用自定义
 * 模板约定的 {{content}}/{{count}} 双花括号占位符（见
 * `question_generation_service.py` _build_prompt 的自定义分支），用户可直接
 * 复制改写。若两端模板有调整需同步。
 */
export const DEFAULT_QUESTION_PROMPT_TEMPLATE = `留空则使用系统默认模板。自定义时支持占位符 {{content}}（分块内容）与 {{count}}（问题数）。

请严格根据以下文档内容，生成 {{count}} 个用户可能会问的问题。
要求：
1. 仅基于下方文档内容中实际存在的信息，不得引入文档未提及的实体（人名/地名/机构等）
2. 覆盖文档核心信息点
3. 是真实用户会提出的问题
4. 问题清晰简洁
5. 仅输出 JSON 数组，不含其他文本或说明

输出格式：
[{"question": "问题内容", "category": "factual"}]
类别可选：factual / conceptual / procedural

文档内容：
{{content}}`

/** 后端 config.text_parsing → 表单字段（逐类型回填策略与 PDF OCR 开关） */
export function applyTextParsingConfig(
  target: {
    pdfStrategy: TextStrategy
    pdfOcrEnabled: boolean
    docxStrategy: TextStrategy
    excelStrategy: TextStrategy
    pptStrategy: TextStrategy
    epubStrategy: TextStrategy
    markdownStrategy: TextStrategy
    htmlStrategy: TextStrategy
    txtStrategy: TextStrategy
    jsonStrategy: TextStrategy
  },
  textConfig?: TextParsingConfig,
) {
  target.pdfStrategy = getTextStrategyValue(textConfig?.pdf?.strategy)
  target.pdfOcrEnabled = textConfig?.pdf?.ocr_enabled ?? false
  target.docxStrategy = getTextStrategyValue(textConfig?.docx?.strategy)
  target.excelStrategy = getTextStrategyValue(textConfig?.excel?.strategy)
  target.pptStrategy = getTextStrategyValue(textConfig?.ppt?.strategy)
  target.epubStrategy = getTextStrategyValue(textConfig?.epub?.strategy)
  target.markdownStrategy = getTextStrategyValue(textConfig?.markdown?.strategy)
  target.htmlStrategy = getTextStrategyValue(textConfig?.html?.strategy)
  target.txtStrategy = getTextStrategyValue(textConfig?.txt?.strategy)
  target.jsonStrategy = getTextStrategyValue(textConfig?.json?.strategy)
}

/** 表单字段 → 后端 TextParsingConfig（deepdoc 策略时 PDF 固定 parser=full） */
export function buildTextParsingConfigFromForm(source: {
  pdfStrategy: TextStrategy
  pdfOcrEnabled: boolean
  docxStrategy: TextStrategy
  excelStrategy: TextStrategy
  pptStrategy: TextStrategy
  epubStrategy: TextStrategy
  markdownStrategy: TextStrategy
  htmlStrategy: TextStrategy
  txtStrategy: TextStrategy
  jsonStrategy: TextStrategy
}): TextParsingConfig {
  return {
    pdf: {
      strategy: source.pdfStrategy,
      // 前端只暴露 default/deepdoc 两个选择；deepdoc 固定走 full（推荐模式）
      parser: source.pdfStrategy === 'deepdoc' ? 'full' : undefined,
      ocr_enabled: source.pdfOcrEnabled,
    },
    docx: { strategy: source.docxStrategy },
    excel: { strategy: source.excelStrategy },
    ppt: { strategy: source.pptStrategy },
    epub: { strategy: source.epubStrategy },
    markdown: { strategy: source.markdownStrategy },
    html: { strategy: source.htmlStrategy },
    txt: { strategy: source.txtStrategy },
    json: { strategy: source.jsonStrategy },
  }
}

// ==================== Wiki 生成配置（表单 ↔ 后端 config 双向转换） ====================

/** Wiki 生成粒度：聚焦/标准/穷举三档 */
export type WikiGranularity = 'focused' | 'standard' | 'exhaustive'

/** Wiki 粒度选项（下拉 label + 描述） */
export const wikiGranularityItems: Array<{ value: WikiGranularity; label: string; desc: string }> =
  [
    { value: 'focused', label: '聚焦', desc: '仅提取文档主要主题（3-7 项）' },
    { value: 'standard', label: '标准', desc: '主要主题 + 实质性讨论的实体与概念（默认）' },
    { value: 'exhaustive', label: '穷举', desc: '穷举所有命名实体与概念，适合做术语库' },
  ]

/** 后端 config.wiki → 表单字段 */
export function applyWikiConfig(
  target: {
    wikiEnabled: boolean
    wikiLlmModel: string
    wikiGranularity: WikiGranularity
    wikiMaxPages: number
    wikiContentInstructions: string
    wikiExtractionInstructions: string
  },
  wikiConfig?: WikiGenerationConfig,
) {
  target.wikiEnabled = wikiConfig?.enabled ?? false
  target.wikiLlmModel = wikiConfig?.llm?.model ?? ''
  const granularity = wikiConfig?.granularity ?? 'standard'
  target.wikiGranularity =
    granularity === 'focused' || granularity === 'exhaustive' ? granularity : 'standard'
  target.wikiMaxPages = wikiConfig?.max_pages_per_ingest ?? 50
  target.wikiContentInstructions = wikiConfig?.content_instructions ?? ''
  target.wikiExtractionInstructions = wikiConfig?.extraction_instructions ?? ''
}

/** 表单字段 → 后端 config.wiki；关闭时仅保留开关状态 */
export function buildWikiConfigFromForm(source: {
  wikiEnabled: boolean
  wikiLlmModel: string
  wikiGranularity: WikiGranularity
  wikiMaxPages: number
  wikiContentInstructions: string
  wikiExtractionInstructions: string
}): WikiGenerationConfig {
  if (!source.wikiEnabled) {
    return { enabled: false }
  }
  return {
    enabled: true,
    llm: source.wikiLlmModel ? { model: source.wikiLlmModel } : undefined,
    granularity: source.wikiGranularity,
    max_pages_per_ingest: source.wikiMaxPages,
    content_instructions: source.wikiContentInstructions || null,
    extraction_instructions: source.wikiExtractionInstructions || null,
  }
}
