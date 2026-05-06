/**
 * 全局类型定义
 */

// 重新导出 API 类型
export * from '../api/types'

// 路由元信息
declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresAdmin?: boolean
    layout?: 'auth' | 'main'
    title?: string
  }
}

// 表单规则类型
export interface FormRule {
  required?: boolean
  message?: string
  trigger?: 'blur' | 'change'
  min?: number
  max?: number
  pattern?: RegExp
  validator?: (rule: unknown, value: unknown, callback: (error?: Error) => void) => void
}

// 表格列配置
export interface TableColumn {
  prop: string
  label: string
  width?: string | number
  minWidth?: string | number
  sortable?: boolean
  fixed?: 'left' | 'right' | true
  formatter?: (row: Record<string, unknown>, column: TableColumn, cellValue: unknown) => string
}

// 选择器选项
export interface SelectOption {
  label: string
  value: string | number
  disabled?: boolean
}

// 面包屑项
export interface BreadcrumbItem {
  title: string
  path?: string
}

// 通用 ID 类型
export type ID = number | string

// 通用时间戳类型
export type Timestamp = string | Date
