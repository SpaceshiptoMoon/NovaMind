/**
 * 面包屑 store
 *
 * 页面壳（SpaceListView）发布当前路由的面包屑链、返回目标与页头动作，
 * 全局顶栏（AppHeader）渲染——页面导航条从内容区上移到顶栏的桥接层。
 * 消费方：AppHeader（渲染）、SpaceListView（发布）。
 */
import { ref } from 'vue'
import type { Component } from 'vue'
import { defineStore } from 'pinia'
import type { CrumbItem } from '@/components/common/BreadcrumbNav.vue'

export interface BreadcrumbBack {
  label: string
  to: string
}

export interface BreadcrumbAction {
  label: string
  to: string
  /** 图标组件建议经 markRaw 包装后传入，避免组件对象被响应式代理 */
  icon?: Component
}

export const useBreadcrumbStore = defineStore('breadcrumb', () => {
  const items = ref<CrumbItem[]>([])
  const back = ref<BreadcrumbBack | null>(null)
  const action = ref<BreadcrumbAction | null>(null)

  /** 发布面包屑（页面路由变化时整体覆盖；action 为面包屑尾随的页头动作，可空） */
  function set(
    nextItems: CrumbItem[],
    nextBack: BreadcrumbBack | null = null,
    nextAction: BreadcrumbAction | null = null,
  ) {
    items.value = nextItems
    back.value = nextBack
    action.value = nextAction
  }

  /** 清空（离开发布方页面时由其卸载钩子调用，防止其他页面残留旧链路） */
  function clear() {
    items.value = []
    back.value = null
    action.value = null
  }

  return { items, back, action, set, clear }
})
