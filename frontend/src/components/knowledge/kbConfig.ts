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
