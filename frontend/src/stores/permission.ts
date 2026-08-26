import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { userApi } from '@/api/user'

export const usePermissionStore = defineStore('permission', () => {
  const permissions = ref<string[]>([])
  const roleCode = ref<string>('')
  const loaded = ref(false)

  const isAdmin = computed(() => roleCode.value === 'admin')

  function hasPermission(code: string | string[]): boolean {
    if (isAdmin.value) return true
    const codes = Array.isArray(code) ? code : [code]
    return codes.some((c) => permissions.value.includes(c))
  }

  async function fetchPermissions() {
    const data = await userApi.getMyPermissions()
    permissions.value = data.permissions
    roleCode.value = data.role_code
    loaded.value = true
  }

  function clear() {
    permissions.value = []
    roleCode.value = ''
    loaded.value = false
  }

  return { permissions, roleCode, loaded, isAdmin, hasPermission, fetchPermissions, clear }
})
