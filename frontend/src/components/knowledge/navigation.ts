/** 知识库页签导航项：展示文案、跳转地址与激活态 */
export interface KbNavItem {
  label: string
  to: string
  route: string
  active: boolean
}

/** 按空间/知识库构造知识库详情页顶部导航（文档/任务/Wiki/检索/评估五页签） */
export function buildKbNavItems(options: {
  spaceId: number | string
  kbId: number | string
  currentRouteName: string | symbol | null | undefined
}): KbNavItem[] {
  const { spaceId, kbId, currentRouteName } = options

  return [
    {
      label: '文档管理',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/documents`,
      route: 'Documents',
      active: currentRouteName === 'Documents' || currentRouteName === 'DocumentDetail',
    },
    {
      label: '任务列表',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/tasks`,
      route: 'DocumentTasks',
      active: currentRouteName === 'DocumentTasks',
    },
    {
      label: 'Wiki',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/wiki`,
      route: 'KbWiki',
      active: currentRouteName === 'KbWiki',
    },
    {
      label: '知识检索',
      to: `/home/spaces/${spaceId}/search?kbId=${kbId}`,
      route: 'Search',
      active: currentRouteName === 'Search',
    },
    {
      label: '效果评估',
      to: `/home/spaces/${spaceId}/knowledge-bases/${kbId}/evaluation`,
      route: 'KbEvaluation',
      active: currentRouteName === 'KbEvaluation',
    },
  ]
}
