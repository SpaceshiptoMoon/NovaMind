import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { request, tokenManager, TOKEN_SYNC_EVENT } from '@/api'
import { userApi } from '@/api/user'
import type { User, RegisterRequest } from '@/api/types'
import { usePermissionStore } from '@/stores/permission'

interface JwtPayload {
  user_id: number
  username: string
  email: string
  is_admin: boolean
  status: number
  exp: number
}

function decodeJwt(token: string): JwtPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length < 2 || !parts[1]) return null
    const payload = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(payload)
  } catch {
    return null
  }
}

function isTokenExpired(token: string): boolean {
  const payload = decodeJwt(token)
  if (!payload?.exp) return true
  return payload.exp * 1000 < Date.now()
}

function getUserIdFromToken(): number | null {
  const token = tokenManager.getToken()
  if (!token) return null
  const payload = decodeJwt(token)
  return payload?.user_id ?? null
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  // 响应式 token 镜像：setToken/clearToken 时同步更新，使 isLoggedIn 等派生
  // 状态在 token 变化时重新计算（此前 computed 直读 localStorage 无响应式依赖）
  const accessToken = ref<string | null>(tokenManager.getToken())

  const isLoggedIn = computed(() => {
    const token = accessToken.value
    return !!token && !isTokenExpired(token)
  })
  const isAdmin = computed(() => usePermissionStore().isAdmin)
  const username = computed(() => user.value?.username ?? '')

  function setToken(t: string, refresh?: string) {
    accessToken.value = t
    tokenManager.setToken(t)
    if (refresh) {
      tokenManager.setRefreshToken(refresh)
    }
  }

  function clearAuth() {
    user.value = null
    accessToken.value = null
    tokenManager.clearToken()
    localStorage.removeItem('user')
    usePermissionStore().clear()
  }

  async function login(uname: string, password: string) {
    loading.value = true
    try {
      const data = await userApi.login({ username: uname, password })
      setToken(data.access_token, data.refresh_token)
      await fetchProfile()
      const permStore = usePermissionStore()
      await permStore.fetchPermissions()
      return data
    } finally {
      loading.value = false
    }
  }

  async function register(payload: RegisterRequest) {
    loading.value = true
    try {
      const data = await userApi.register(payload)
      setToken(data.access_token, data.refresh_token)
      await fetchProfile()
      const permStore = usePermissionStore()
      await permStore.fetchPermissions()
      return data
    } finally {
      loading.value = false
    }
  }

  async function fetchProfile() {
    const userId = getUserIdFromToken()
    if (!userId) throw new Error('No valid token')

    try {
      const data = await request.get<User>(`/user/users/${userId}`)
      user.value = data
      localStorage.setItem('user', JSON.stringify(data))
      return data
    } catch (error) {
      clearAuth()
      throw error
    }
  }

  async function updateProfile(data: Partial<User>) {
    const userId = getUserIdFromToken()
    if (!userId) throw new Error('No valid token')

    const result = await request.put<User>(`/user/users/${userId}`, data)
    user.value = result
    localStorage.setItem('user', JSON.stringify(result))
    return result
  }

  async function logout() {
    try {
      await userApi.logout(tokenManager.getRefreshToken() ?? undefined)
    } catch {
      // 即使接口失败也清除本地状态
    } finally {
      clearAuth()
    }
  }

  function init() {
    const token = tokenManager.getToken()
    if (token && isTokenExpired(token)) {
      clearAuth()
      return
    }
    accessToken.value = token

    const userStr = localStorage.getItem('user')
    if (userStr) {
      try {
        user.value = JSON.parse(userStr)
      } catch {
        localStorage.removeItem('user')
      }
    }
  }

  // 拦截器静默刷新/清除 token 后，同步响应式镜像（每个 store 实例注册一次）
  if (typeof window !== 'undefined') {
    window.addEventListener(TOKEN_SYNC_EVENT, () => {
      accessToken.value = tokenManager.getToken()
    })
  }

  init()

  return {
    user,
    loading,
    isLoggedIn,
    isAdmin,
    username,
    setToken,
    clearAuth,
    login,
    register,
    fetchProfile,
    updateProfile,
    logout,
    init,
    getUserIdFromToken,
  }
})
