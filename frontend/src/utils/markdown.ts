import { Marked } from 'marked'
import hljs from 'highlight.js'
import katex from 'katex'
import { copyToClipboard } from '@/utils/clipboard'

// 代码块复制按钮是渲染产物里的内联 onclick，拿不到模块作用域，
// 把统一复制工具挂到 window 供其调用（幂等，重复挂载无副作用）
declare global {
  interface Window {
    __copyToClipboard?: typeof copyToClipboard
  }
}
window.__copyToClipboard = copyToClipboard

/**
 * Markdown 渲染工具
 *
 * renderMarkdown：GFM + highlight.js 代码高亮（带复制按钮）+ KaTeX 数学公式 +
 * 引用角标 [n] 交互化；代码块/公式经占位符暂存穿过 marked 解析后回填。
 * renderMarkdownWithToc：在其产物上为 h2/h3 注入锚点 id 并返回目录（Wiki 页专用）。
 */

let codeBlockId = 0

const marked = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    code({ text, lang }: { text: string; lang?: string }) {
      const language = lang && hljs.getLanguage(lang) ? lang : ''
      const highlighted = language
        ? hljs.highlight(text, { language }).value
        : hljs.highlightAuto(text).value
      const id = `code-block-${++codeBlockId}`
      const displayLang = language || 'code'
      // 复制走 window.__copyToClipboard（clipboard.ts 挂到 window）：内联 onclick
      // 拿不到模块作用域，直接内联 navigator.clipboard.writeText 无降级、失败静默
      return `<div class="code-block" data-id="${id}">
  <div class="code-header">
    <span class="code-lang">${displayLang}</span>
    <button class="code-copy-btn" onclick="(function(btn){
      var code=btn.closest('.code-block').querySelector('code');
      var done=function(){btn.classList.add('copied');btn.textContent='已复制';setTimeout(function(){btn.classList.remove('copied');btn.textContent='复制代码';},2000);};
      window.__copyToClipboard(code.textContent||'').then(function(ok){if(ok){done();}});
    })(this)">复制代码</button>
  </div>
  <pre><code class="hljs${language ? ` language-${language}` : ''}">${highlighted}</code></pre>
</div>`
    },
  },
})

// 代码块占位定界符（纯 ASCII、正文不可能出现），暂存 fenced/inline 代码块避免误伤
const CODE_TOKEN_START = '@@CODEBLOCK_'
const CODE_TOKEN_END = '_@@'

// 数学公式占位定界符（同上策略）：先于 marked 提取 $...$ / $$...$$，KaTeX 渲染后回填，
// 避免 marked 把 \times、_、^ 等 LaTeX 语法当 markdown 转义/强调吃掉
const MATH_TOKEN_START = '@@MATH_'
const MATH_TOKEN_END = '_@@'

/** KaTeX 渲染；解析失败回退原文（throwOnError: false 也会有红色报错块，这里宁可原文展示） */
function renderMath(latex: string, display: boolean): string {
  try {
    return katex.renderToString(latex, { displayMode: display, throwOnError: true })
  } catch {
    return null as unknown as string
  }
}

/**
 * 提取数学公式为占位符并预渲染（在 marked 解析前调用）。
 *
 * 支持 $$...$$（块级）与 $...$（行内）。判定收紧避免误伤金额/货币文本：
 * - 行内 $ 后不能紧跟空白，$ 前不能是空白（"$ 5 and $ 10" 不算公式）；
 * - 内容为空或纯空白不匹配。
 * 代码块已被上游暂存为 CODEBLOCK 占位符，此处天然不会命中。
 */
function extractMath(text: string): { text: string; store: string[] } {
  const store: string[] = []
  const put = (latex: string, display: boolean) => {
    const rendered = renderMath(latex, display)
    // 渲染失败保留原文交 marked 正常处理（$ 显示为普通字符）
    store.push(rendered ?? `$${display ? '$' : ''}${latex}$${display ? '$' : ''}`)
    return `${MATH_TOKEN_START}${store.length - 1}${MATH_TOKEN_END}`
  }

  const out = text
    // 块级 $$...$$（可跨行）
    .replace(/\$\$([\s\S]+?)\$\$/g, (_m, latex: string) =>
      latex.trim() ? put(latex, true) : _m,
    )
    // 行内 $...$（不跨行）。lead 只排除 $ 本身（空格、行首均可作前导——
    // "$ 5" 类货币靠 content 首字符非空白排除，而非靠 lead 排除空白）
    .replace(/(^|[^$])\$([^\s$][^$\n]*?)\$(?!\d)/g, (m, lead: string, latex: string) => {
      if (!latex.trim()) return m
      return lead + put(latex, false)
    })

  return { text: out, store }
}

/**
 * 将正文中的引用角标 [1] [2] ... 渲染为可交互的 <sup class="cite-marker">。
 *
 * 处理流程：
 * 1. 保护 fenced / inline 代码块，避免其中的 [n] 被误识别为引用角标；
 * 2. 把独立的 [n]（n 为 1-3 位数字，且非 [text](url) 链接形式）替换为占位符；
 * 3. 还原代码块后交由 marked 解析；
 * 4. 把占位符替换回 <sup class="cite-marker" data-cite="n">[n]</sup>。
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''

  // 1. 暂存代码块
  const codeStore: string[] = []
  const stash = (m: string) => `${CODE_TOKEN_START}${codeStore.push(m) - 1}${CODE_TOKEN_END}`
  const protectedText = text.replace(/```[\s\S]*?```/g, stash).replace(/`[^`\n]+`/g, stash)

  // 2. 数学公式 → KaTeX HTML 占位符（$$...$$ 块级 + $...$ 行内；失败回退原文）
  const { text: mathExtracted, store: mathStore } = extractMath(protectedText)

  // 3. 引用角标 → 占位符（排除 [n](url) 链接形式）
  const citedText = mathExtracted.replace(/\[(\d{1,3})\](?!\()/g, (_m, n) => `@@CITE_${n}@@`)

  // 4. 还原代码块
  const restored = citedText.replace(/@@CODEBLOCK_(\d+)_@@/g, (_m, i) => codeStore[Number(i)] ?? '')

  // 5. marked 解析
  const html = marked.parse(restored) as string

  // 6. 占位符 → 角标 sup（事件代理在 ChatView 统一接管 hover/click）
  const withCites = html.replace(
    /@@CITE_(\d{1,3})@@/g,
    (_m, n) => `<sup class="cite-marker" data-cite="${n}">[${n}]</sup>`,
  )

  // 7. 数学占位符 → KaTeX HTML（@ 字符不被 marked 转义，占位符安全穿过解析）
  return withCites.replace(/@@MATH_(\d+)_@@/g, (_m, i) => mathStore[Number(i)] ?? '')
}

// ---- TOC 支持（Wiki 浏览页专用；renderMarkdown 签名与行为不变，其他消费方零影响） ----

/** 目录条目：标题锚点 id、纯文本内容、标题层级（仅 h2/h3） */
export interface TocItem {
  id: string
  text: string
  level: 2 | 3
}

/**
 * 在 renderMarkdown 产物基础上为 h2/h3 注入 id 与 hover 锚点链接，并返回目录。
 *
 * marked v12+ 已移除 headerIds，渲染出的标题默认无 id。此处用正则后处理而非
 * DOMParser（为拿几个标题不值得整棵树 parse/serialize）：marked 输出的 h2/h3
 * 无属性、格式可预测；fenced code 内的 `<h2>` 已被转义为 `&lt;h2&gt;`，正则天然
 * 不误伤（有单测锁定）。slug 保留中文（`\p{L}`，HTML5 id 合法），同名标题追加序号。
 */
export function renderMarkdownWithToc(text: string): { html: string; toc: TocItem[] } {
  const html = renderMarkdown(text)
  const seen = new Map<string, number>()
  const toc: TocItem[] = []
  const out = html.replace(/<h([23])>([\s\S]*?)<\/h\1>/g, (_m, lvl: string, inner: string) => {
    const plain = inner.replace(/<[^>]+>/g, '').trim()
    let id =
      plain
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\s-]/gu, '')
        .replace(/\s+/g, '-') || 'section'
    const n = seen.get(id) ?? 0
    seen.set(id, n + 1)
    if (n) id = `${id}-${n}`
    toc.push({ id, text: plain, level: Number(lvl) as 2 | 3 })
    return `<h${lvl} id="${id}">${inner}<a class="heading-anchor" aria-hidden="true">#</a></h${lvl}>`
  })
  return { html: out, toc }
}
