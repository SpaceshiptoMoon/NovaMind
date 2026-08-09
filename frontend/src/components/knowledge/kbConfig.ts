import type { PdfParserName, TextParsingConfig } from '@/api/types'

export type TextStrategy = 'default' | 'deepdoc'
export type ImageStrategy = 'vlm' | 'deepdoc_ocr'
export type AudioChunkStrategy = 'sentence' | 'fixed'

export type TextStrategyField =
  | 'docxStrategy'
  | 'excelStrategy'
  | 'pptStrategy'
  | 'epubStrategy'
  | 'markdownStrategy'
  | 'htmlStrategy'
  | 'txtStrategy'
  | 'jsonStrategy'

export const textStrategyItems: Array<{ key: TextStrategyField; label: string }> = [
  { key: 'docxStrategy', label: 'DOCX' },
  { key: 'excelStrategy', label: 'Excel' },
  { key: 'pptStrategy', label: 'PPT' },
  { key: 'epubStrategy', label: 'EPUB' },
  { key: 'markdownStrategy', label: 'Markdown' },
  { key: 'htmlStrategy', label: 'HTML' },
  { key: 'txtStrategy', label: 'TXT' },
  { key: 'jsonStrategy', label: 'JSON' },
]

export const deepdocParserOptions: Array<{ label: string; value: PdfParserName }> = [
  { label: 'layout', value: 'layout' },
  { label: 'plain', value: 'plain' },
  { label: 'vision', value: 'vision' },
  { label: 'docling', value: 'docling' },
  { label: 'mineru', value: 'mineru' },
  { label: 'opendataloader', value: 'opendataloader' },
  { label: 'paddleocr', value: 'paddleocr' },
  { label: 'somark', value: 'somark' },
  { label: 'tcadp', value: 'tcadp' },
]

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

export function applyTextParsingConfig(
  target: {
    pdfStrategy: TextStrategy
    deepdocParser: PdfParserName
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
  target.deepdocParser = textConfig?.pdf?.parser || 'layout'
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

export function buildTextParsingConfigFromForm(source: {
  pdfStrategy: TextStrategy
  deepdocParser: PdfParserName
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
      parser: source.pdfStrategy === 'deepdoc' ? source.deepdocParser : undefined,
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
