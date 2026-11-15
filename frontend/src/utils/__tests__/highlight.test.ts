import { describe, expect, it } from 'vitest'
import { highlightSegments, queryToTerms } from '../highlight'

const hasSegmenter = 'Segmenter' in (Intl as object)

describe('queryToTerms', () => {
  it('空白分词并过滤空串', () => {
    expect(queryToTerms('  部署 流程 ')).toEqual(['部署', '流程'])
  })

  it('单字整查询保留（用户显式输入的单字即查询本体，不算噪音）', () => {
    expect(queryToTerms('光')).toEqual(['光'])
  })

  it('英文查询按词切分', () => {
    expect(queryToTerms('deploy guide')).toEqual(['deploy', 'guide'])
  })

  it('空查询返回空数组', () => {
    expect(queryToTerms('   ')).toEqual([])
  })
})

describe.skipIf(!hasSegmenter)('queryToTerms（Intl.Segmenter 可用）', () => {
  it('无空格中文经 ICU 分词切成多词（词典版本无关的行为断言）', () => {
    const terms = queryToTerms('知识库检索')
    expect(terms.length).toBeGreaterThanOrEqual(2)
    expect(terms).toContain('检索')
    expect(terms.every((t) => t.length >= 2)).toBe(true)
  })
})

describe.skipIf(hasSegmenter)('queryToTerms（无 Intl.Segmenter 退回空白分词）', () => {
  it('中文整句一词', () => {
    expect(queryToTerms('知识库检索')).toEqual(['知识库检索'])
  })
})

describe.skipIf(!hasSegmenter)('highlightSegments 端到端（无空格中文查询）', () => {
  it('整句中文查询经分词后子词命中高亮', () => {
    const segs = highlightSegments('本知识库支持混合检索与全文检索', queryToTerms('知识库检索'))
    const hits = segs.filter((s) => s.hit).map((s) => s.text)
    expect(hits).toContain('检索')
  })
})

describe('highlightSegments', () => {
  it('单关键词命中切成三段', () => {
    expect(highlightSegments('部署手册与部署流程', ['部署'])).toEqual([
      { text: '部署', hit: true },
      { text: '手册与', hit: false },
      { text: '部署', hit: true },
      { text: '流程', hit: false },
    ])
  })

  it('大小写不敏感命中保留原文', () => {
    const segs = highlightSegments('FastAPI 与 fastapi', ['fastapi'])
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['FastAPI', 'fastapi'])
  })

  it('多词命中任一即高亮', () => {
    const segs = highlightSegments('检索与改写', ['检索', '改写'])
    expect(segs.filter((s) => s.hit).length).toBe(2)
  })

  it('正则元字符按字面量处理（用户输入安全）', () => {
    const segs = highlightSegments('a.b 与 axb', ['a.b'])
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['a.b'])
  })

  it('无关键词或空文本原样单段', () => {
    expect(highlightSegments('原文', [])).toEqual([{ text: '原文', hit: false }])
    expect(highlightSegments('', ['词'])).toEqual([{ text: '', hit: false }])
  })

  it('关键词超预算截断（8 词上限，防病态正则）', () => {
    const terms = Array.from({ length: 20 }, (_, i) => `词${i}`)
    const segs = highlightSegments('词0 词9 词19', terms)
    // 预算保留 词0..词7：词0 精确命中；词9 超预算按普通文本渲染；
    // 词19 的前缀 词1 在预算内仍部分命中（短词是超预算长词前缀时的边界行为）
    expect(segs.filter((s) => s.hit).map((s) => s.text)).toEqual(['词0', '词1'])
  })

  it('相邻命中不产生空段', () => {
    const segs = highlightSegments('ab', ['a', 'b'])
    expect(segs.every((s) => s.text.length > 0)).toBe(true)
    expect(segs.map((s) => s.hit)).toEqual([true, true])
  })
})
