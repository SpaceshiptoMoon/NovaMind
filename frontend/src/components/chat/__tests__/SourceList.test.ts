import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import SourceList from '../SourceList.vue'
import type { ChatSource } from '@/api/types'

/** 批次 A：kb 组内 chunk_type=wiki_page 的来源渲染 Wiki 徽标；普通 chunk 不渲染 */
describe('SourceList wiki 徽标', () => {
  const mkSources = (): ChatSource[] => [
    {
      index: 1,
      kind: 'kb',
      chunk_type: 'wiki_page',
      document_name: 'RAG 概述',
      snippet: 'wiki 页内容',
      score: 0.95,
    },
    {
      index: 2,
      kind: 'kb',
      document_name: 'manual.pdf',
      snippet: '普通 chunk',
      score: 0.7,
    },
  ]

  const mountList = async () => {
    const wrapper = mount(SourceList, {
      props: { sources: mkSources() },
      global: { plugins: [ElementPlus] },
    })
    // 默认折叠，点 header 展开
    await wrapper.find('.source-list-header').trigger('click')
    return wrapper
  }

  it('wiki_page 来源显示 Wiki 徽标', async () => {
    const wrapper = await mountList()
    const wikiBadges = wrapper.findAll('.source-kind.wiki')
    expect(wikiBadges.length).toBe(1)
    // noUncheckedIndexedAccess：索引访问返回 T | undefined，需收窄
    const badge = wikiBadges[0]
    if (!badge) throw new Error('Wiki 徽标缺失')
    expect(badge.text()).toBe('Wiki')
  })

  it('普通 chunk 来源不显示 Wiki 徽标', async () => {
    const wrapper = await mountList()
    // 只有 index=1 的 wiki 来源带徽标；index=2（manual.pdf）不带
    const cards = wrapper.findAll('.source-card')
    expect(cards.length).toBe(2)
    const [first, second] = cards
    if (!first || !second) throw new Error('来源卡片数量不足')
    expect(second.find('.source-kind.wiki').exists()).toBe(false)
    // 两卡都保留「知识库」kind 徽标
    expect(first.find('.source-kind.kb').exists()).toBe(true)
    expect(second.find('.source-kind.kb').exists()).toBe(true)
  })
})
