import { describe, expect, it } from 'vitest'

import { renderMarkdown } from '../markdown'

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
