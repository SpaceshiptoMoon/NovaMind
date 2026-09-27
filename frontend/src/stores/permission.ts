/**
 * RBAC 权限 store
 *
 * 持有当前用户的权限码集合、角色码与应用级禁用列表（deny-list），是全局
 * isAdmin / hasPermission / hasApp 判断的单一事实源；登录/注册后拉取，登出清空。
 * 消费方：路由守卫、AppHeader/HomeView/UserManageView、v-permission 指令、usePermission。
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { userApi } from '@/api/user'

export const usePermissionStore = defineStore('permission', () => {
  const permissions = ref<string[]>([])
  const roleCode = ref<string>('')
  const disabledApps = ref<string[]>([])
  const loaded = ref(false)

  /** 是否管理员（角色码判定；admin 拥有全部权限与应用访问） */
  const isAdmin = computed(() => roleCode.value === 'admin')

  /** 是否持有指定权限码（传数组 = 任一命中即过；admin 短路全过） */
  function hasPermission(code: string | string[]): boolean {
    if (isAdmin.value) return true
    const codes = Array.isArray(code) ? code : [code]
    return codes.some((c) => permissions.value.includes(c))
  }

  /**
   * 应用可用性（deny-list：不在禁用列表 = 可用，默认全开放）。
   * admin 短路全过；强制执行在后端 AppGateMiddleware，此处仅控制导航展示。
   * 接受宽 string（路由 meta / 常量表推断不出字面量联合），非法代码恒落在禁用列表外。
   */
  function hasApp(code: string): boolean {
    if (isAdmin.value) return true
    return !disabledApps.value.includes(code)
  }

  /** 从后端拉取权限快照（权限码 + 角色码 + 应用禁用列表），覆盖式更新 */
  async function fetchPermissions() {
    const data = await userApi.getMyPermissions()
    permissions.value = data.permissions
    roleCode.value = data.role_code
    disabledApps.value = data.disabled_apps ?? []
    loaded.value = true
  }

  /** 清空全部权限状态（登出/用户被禁用时调用） */
  function clear() {
    permissions.value = []
    roleCode.value = ''
    disabledApps.value = []
    loaded.value = false
  }

  return {
    permissions,
    roleCode,
    disabledApps,
    loaded,
    isAdmin,
    hasPermission,
    hasApp,
    fetchPermissions,
    clear,
  }
})
