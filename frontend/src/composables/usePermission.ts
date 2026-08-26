import { usePermissionStore } from '@/stores/permission'

export function usePermission() {
  const store = usePermissionStore()
  return {
    hasPermission: store.hasPermission,
    isAdmin: store.isAdmin,
  }
}
