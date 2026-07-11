import type { Component } from 'vue'

export interface KbNavItem {
  label: string
  to: string
  route: string
  active: boolean
  icon: Component
}

export function buildKbNavItems(options: {
  spaceId: number | string
  kbId: number | string
  currentRouteName: string | symbol | null | undefined
  icons: {
    document: Component
    list: Component
    search: Component
    evaluation: Component
  }
}): KbNavItem[] {
  const { spaceId, kbId, currentRouteName, icons } = options

  return [
    {
      label: '文档管理',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      route: 'Documents',
      active: currentRouteName === 'Documents' || currentRouteName === 'DocumentDetail',
      icon: icons.document,
    },
    {
      label: '任务列表',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/tasks`,
      route: 'DocumentTasks',
      active: currentRouteName === 'DocumentTasks',
      icon: icons.list,
    },
    {
      label: '知识检索',
      to: `/home/spaces/${spaceId}/search?kbId=${kbId}`,
      route: 'Search',
      active: currentRouteName === 'Search',
      icon: icons.search,
    },
    {
      label: '效果评估',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`,
      route: 'KbEvaluation',
      active: currentRouteName === 'KbEvaluation',
      icon: icons.evaluation,
    },
  ]
}
