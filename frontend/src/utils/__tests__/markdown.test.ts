import { describe, expect, it } from 'vitest'

import { renderMarkdown, renderMarkdownWithToc } from '../markdown'

describe('renderMarkdown', () => {
  it('renders citation markers outside code blocks', () => {
    const html = renderMarkdown('Answer with source [1].')

    expect(html).toContain('<sup class="cite-marker" data-cite="1">[1]</sup>')
  })

  it('does not convert citations inside inline code', () => {
    const html = renderMarkdown('Use `ref[2]` literally.')

    expect(html).toContain('ref[2]')
    expect(html).not.toContain('data-cite="2"')
  })

  it('renders fenced code blocks with copy UI', () => {
    const html = renderMarkdown('```ts\nconst x = 1\n```')

    expect(html).toContain('code-copy-btn')
    expect(html).toContain('code-block-')
  })
})

describe('renderMarkdown math (KaTeX)', () => {
  it('renders inline math with $...$', () => {
    const html = renderMarkdown('矩阵 $M \\in \\mathbb{R}^{n \\times n}$ 是正定的')

    expect(html).toContain('katex')
    expect(html).not.toContain('$M')
  })

  it('renders display math with $$...$$', () => {
    const html = renderMarkdown('公式：\n\n$$\\sum_{i=1}^{n} a_i$$\n\n结束')

    expect(html).toContain('katex-display')
  })

  it('does not treat currency-like dollars as math', () => {
    const html = renderMarkdown('价格是 $ 5 和 $ 10，共 $15。')

    // 无紧贴内容配对 → 不进 KaTeX，$ 原样保留
    expect(html).not.toContain('katex')
    expect(html).toContain('$')
  })

  it('keeps dollars inside code blocks untouched', () => {
    const html = renderMarkdown('```bash\necho $PATH and $HOME\n```')

    expect(html).not.toContain('katex')
    expect(html).toContain('$PATH')
  })

  it('falls back to raw text when KaTeX fails to parse', () => {
    const html = renderMarkdown('$\\unknowncmd{x}$')

    // 解析失败回退：原文保留，不产生红色报错块
    expect(html).toContain('$\\unknowncmd{x}$')
    expect(html).not.toContain('katex-error')
  })

  it('strips math HTML in toc text but keeps it in the heading', () => {
    const { html, toc } = renderMarkdownWithToc('## 复杂度 $O(n^2)$ 分析\n\n正文')

    // 正文标题保留 KaTeX 排版；目录纯文本（正则剥 HTML 标签）
    expect(html).toContain('katex')
    expect(toc[0]!.text).toContain('O(n')
    expect(toc[0]!.text).not.toContain('<span')
  })
})

describe('renderMarkdownWithToc', () => {
  it('injects ids into h2/h3 and returns toc entries', () => {
    const { html, toc } = renderMarkdownWithToc('## 架构\n\n正文\n\n### 部署方式\n\n正文')

    expect(toc).toEqual([
      { id: '架构', text: '架构', level: 2 },
      { id: '部署方式', text: '部署方式', level: 3 },
    ])
    expect(html).toContain('<h2 id="架构">')
    expect(html).toContain('<h3 id="部署方式">')
  })

  it('disambiguates duplicate headings with a numeric suffix', () => {
    const { toc } = renderMarkdownWithToc('## 概述\n\n## 概述\n\n## 概述')

    expect(toc.map((t) => t.id)).toEqual(['概述', '概述-1', '概述-2'])
  })

  it('keeps latin/digit characters and strips punctuation in slugs', () => {
    const { toc } = renderMarkdownWithToc('## Setup (v2.0)!\n\n正文')

    expect(toc[0]!.id).toBe('setup-v20')
  })

  it('does not inject anchors into escaped headings inside fenced code', () => {
    const { html, toc } = renderMarkdownWithToc('```\n<h2>fake heading</h2>\n```\n\n## 真标题')

    // fenced code 内容经 hljs 转义 + span 包裹（&lt;<span>h2</span>&gt;），
    // 不会出现裸 <h2>，TOC 正则不会误伤
    expect(html).toContain('hljs-name">h2</span>')
    expect(html).not.toContain('id="fake')
    expect(toc).toHaveLength(1)
    expect(toc[0]!.id).toBe('真标题')
  })

  it('falls back to a placeholder slug for symbol-only headings', () => {
    const { toc } = renderMarkdownWithToc('## ???')

    expect(toc[0]!.id).toBe('section')
  })

  it('does not mutate plain renderMarkdown output', () => {
    const html = renderMarkdown('## 未受影响')

    expect(html).toContain('<h2>未受影响</h2>')
    expect(html).not.toContain('heading-anchor')
  })
})
