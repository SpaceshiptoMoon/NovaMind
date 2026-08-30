import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { userApi } from '@/api/user'

export const usePermissionStore = defineStore('permission', () => {
  const permissions = ref<string[]>([])
  const roleCode = ref<string>('')
  const disabledApps = ref<string[]>([])
  const loaded = ref(false)

  const isAdmin = computed(() => roleCode.value === 'admin')

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

  async function fetchPermissions() {
    const data = await userApi.getMyPermissions()
    permissions.value = data.permissions
    roleCode.value = data.role_code
    disabledApps.value = data.disabled_apps ?? []
    loaded.value = true
  }

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
