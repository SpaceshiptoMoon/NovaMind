import { usePermissionStore } from '@/stores/permission'

/** 权限判断组合式入口：暴露 hasPermission（权限码校验）与 isAdmin（管理员判定） */
export function usePermission() {
  const store = usePermissionStore()
  return {
    hasPermission: store.hasPermission,
    isAdmin: store.isAdmin,
  }
}
