import type { PdfParserName, TextParsingConfig } from '@/api/types'

export type TextStrategy = 'default' | 'deepdoc'
export type ImageStrategy = 'vlm' | 'deepdoc_ocr'
export type VideoStrategy = 'simple' | 'scene' | 'dedup' | 'grouped' | 'rewrite' | 'dedup_grouped'

/** 视频解析策略选项（6 预设映射到抽帧/去重/描述三阶段组合）。 */
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
  {
    value: 'dedup_grouped',
    label: '去重+分组（暂未实现）',
    desc: '图像 embedding 去重 + 分组描述（预留，待图像 embedding 引入）',
    disabled: true,
  },
]

export function getVideoStrategyValue(value: unknown): VideoStrategy {
  const allowed: VideoStrategy[] = ['simple', 'scene', 'dedup', 'grouped', 'rewrite', 'dedup_grouped']
  return (allowed as string[]).includes(value as string) ? (value as VideoStrategy) : 'simple'
}

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

export const deepdocParserOptions: Array<{ label: string; value: PdfParserName; desc: string }> = [
  {
    label: 'full（全量流水线·推荐）',
    value: 'full',
    desc: '默认模式，对齐 RAGFlow 上游：每页 OCR 检测 + 逐框文字层融合 + ONNX 版面 + 表格识别。文字层干净时优先用文字层（跳过 OCR 识别，快），乱码或无文字层时回退 OCR。扫描件、图片 PDF、数字原生 PDF 通吃。速度最慢、占内存最高。',
  },
  {
    label: 'plain（纯文本）',
    value: 'plain',
    desc: '仅抽取文字层，无版面分析、无 OCR。最快，适合结构简单的纯文字 PDF。扫描件/图片 PDF 会抽出 0 字符，需改用 full。',
  },
  {
    label: 'docling（远程）',
    value: 'docling',
    desc: '远程 Docling 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
  {
    label: 'mineru（远程）',
    value: 'mineru',
    desc: '远程 Mineru 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
  {
    label: 'opendataloader（远程）',
    value: 'opendataloader',
    desc: '远程 OpenDataLoader 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
  {
    label: 'paddleocr（远程）',
    value: 'paddleocr',
    desc: '远程 PaddleOCR 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
  {
    label: 'somark（远程）',
    value: 'somark',
    desc: '远程 SoMark 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
  {
    label: 'tcadp（远程）',
    value: 'tcadp',
    desc: '远程 TCADP 解析服务。需在后端配置外部服务地址，否则解析失败。',
  },
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
  target.deepdocParser = textConfig?.pdf?.parser || 'full'
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
