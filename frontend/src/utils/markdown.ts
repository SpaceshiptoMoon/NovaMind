import { Marked } from 'marked'
import hljs from 'highlight.js'

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
      return `<div class="code-block" data-id="${id}">
  <div class="code-header">
    <span class="code-lang">${displayLang}</span>
    <button class="code-copy-btn" onclick="(function(btn){
      var code=btn.closest('.code-block').querySelector('code');
      navigator.clipboard.writeText(code.textContent||'');
      btn.classList.add('copied');
      btn.textContent='已复制';
      setTimeout(function(){btn.classList.remove('copied');btn.textContent='复制代码';},2000);
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
  const protectedText = text
    .replace(/```[\s\S]*?```/g, stash)
    .replace(/`[^`\n]+`/g, stash)

  // 2. 引用角标 → 占位符（排除 [n](url) 链接形式）
  const citedText = protectedText.replace(/\[(\d{1,3})\](?!\()/g, (_m, n) => `@@CITE_${n}@@`)

  // 3. 还原代码块
  const restored = citedText.replace(/@@CODEBLOCK_(\d+)_@@/g, (_m, i) => codeStore[Number(i)] ?? '')

  // 4. marked 解析
  const html = marked.parse(restored) as string

  // 5. 占位符 → 角标 sup（事件代理在 ChatView 统一接管 hover/click）
  return html.replace(/@@CITE_(\d{1,3})@@/g, (_m, n) =>
    `<sup class="cite-marker" data-cite="${n}">[${n}]</sup>`,
  )
}
