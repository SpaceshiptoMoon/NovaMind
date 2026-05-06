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

export function renderMarkdown(text: string): string {
  if (!text) return ''
  return marked.parse(text) as string
}
