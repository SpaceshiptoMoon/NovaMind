import { describe, expect, it } from 'vitest'
import { highlightSegments, queryToTerms } from '../highlight'

describe('queryToTerms', () => {
  it('空白分词并过滤空串', () => {
    expect(queryToTerms('  部署 流程 ')).toEqual(['部署', '流程'])
  })

  it('中文无空格整句一词', () => {
    expect(queryToTerms('如何部署生产环境')).toEqual(['如何部署生产环境'])
  })

  it('空查询返回空数组', () => {
    expect(queryToTerms('   ')).toEqual([])
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
