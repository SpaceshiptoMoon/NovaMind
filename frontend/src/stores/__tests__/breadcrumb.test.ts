import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useBreadcrumbStore } from '@/stores/breadcrumb'

describe('breadcrumb store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('初始为空：顶栏不渲染面包屑', () => {
    const store = useBreadcrumbStore()
    expect(store.items).toEqual([])
    expect(store.back).toBeNull()
    expect(store.action).toBeNull()
  })

  it('set 整体覆盖发布（链段 + 返回目标 + 页头动作）', () => {
    const store = useBreadcrumbStore()
    store.set([{ label: '个人学习空间' }], null, {
      label: '空间设置',
      to: '/home/spaces/1/settings',
    })
    expect(store.items).toHaveLength(1)
    expect(store.back).toBeNull()
    expect(store.action?.label).toBe('空间设置')

    // 路由切换：新链路覆盖旧链路，未带返回目标/动作时归空
    store.set([{ label: '空间', to: '/x' }, { label: '文档管理' }], {
      label: '返回知识库',
      to: '/kb',
    })
    expect(store.items).toHaveLength(2)
    expect(store.back?.label).toBe('返回知识库')
    expect(store.action).toBeNull()
  })

  it('clear 清空（离开发布方页面后顶栏不残留旧链路）', () => {
    const store = useBreadcrumbStore()
    store.set([{ label: '文档管理' }], { label: '返回知识库', to: '/kb' }, {
      label: '空间设置',
      to: '/s',
    })
    store.clear()
    expect(store.items).toEqual([])
    expect(store.back).toBeNull()
    expect(store.action).toBeNull()
  })
})
