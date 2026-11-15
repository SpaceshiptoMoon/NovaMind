/**
 * 关键词高亮纯函数：把文本切成「普通段 / 命中段」供 v-for + <mark> 渲染。
 *
 * 刻意不返回 HTML 字符串（不走 v-html）——检索结果正文是用户内容，
 * 文本插值 + 分段渲染天然无 XSS 面。
 */

/** 预算常量：防超长查询构造病态正则（per-message 预算教训） */
const MAX_TERMS = 8
const MAX_TERM_LENGTH = 64

export interface HighlightSegment {
  text: string
  /** 是否命中关键词 */
  hit: boolean
}

// Intl.Segmenter 类型在当前 TS lib 目标（<es2022）中不存在——运行时特性
// 检测 + 局部窄化类型（不提升全局 tsconfig lib，旧环境自动退回空白分词）
interface SegmenterPartLike {
  segment: string
  isWordLike?: boolean
}
interface SegmenterLike {
  segment(input: string): Iterable<SegmenterPartLike>
}
const SegmenterCtor = (
  Intl as unknown as {
    Segmenter?: new (locale: string, options: { granularity: 'word' }) => SegmenterLike
  }
).Segmenter

/**
 * 查询文本 → 高亮词列表。
 *
 * 优先用 Intl.Segmenter 词级分词（平台 ICU 分词，CJK 无空格语言自动
 * 切词：「知识库检索」→「知识库」「检索」）；环境不支持时退回空白分词。
 * 过滤多词句中的单字词（单字高亮噪音大；检索本身用整句，高亮仅辅助定位）。
 */
export function queryToTerms(query: string): string[] {
  const raw = query
    .trim()
    .split(/\s+/)
    .filter(Boolean)

  if (SegmenterCtor) {
    const segmenter = new SegmenterCtor('zh', { granularity: 'word' })
    const terms: string[] = []
    for (const part of segmenter.segment(query)) {
      const text = part.segment.trim()
      if (part.isWordLike && text.length >= 2) terms.push(text)
    }
    if (terms.length) return terms
  }

  return raw
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * 把文本按关键词切成命中/普通分段（大小写不敏感，多词命中任一即高亮）。
 *
 * 空文本或无有效关键词时原样返回单段（调用方零分支渲染）。
 */
export function highlightSegments(text: string, terms: string[]): HighlightSegment[] {
  const cleaned = [
    ...new Set(
      terms
        .map((t) => t.trim())
        .filter((t) => t.length > 0)
        .map((t) => (t.length > MAX_TERM_LENGTH ? t.slice(0, MAX_TERM_LENGTH) : t)),
    ),
  ].slice(0, MAX_TERMS)

  if (!cleaned.length || !text) return [{ text, hit: false }]

  const pattern = new RegExp(`(${cleaned.map(escapeRegExp).join('|')})`, 'gi')
  const segments: HighlightSegment[] = []
  let last = 0
  for (const match of text.matchAll(pattern)) {
    const idx = match.index ?? 0
    if (idx > last) segments.push({ text: text.slice(last, idx), hit: false })
    segments.push({ text: match[0], hit: true })
    last = idx + match[0].length
  }
  if (last < text.length) segments.push({ text: text.slice(last), hit: false })
  return segments.length ? segments : [{ text, hit: false }]
}
