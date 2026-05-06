import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { request, tokenManager } from '@/api'
import type { User, LoginResponse } from '@/api/types'

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

  const isLoggedIn = computed(() => {
    const token = tokenManager.getToken()
    return !!token && !isTokenExpired(token)
  })
  const isAdmin = computed(() => user.value?.is_admin ?? false)
  const username = computed(() => user.value?.username ?? '')

  function setToken(accessToken: string, refresh?: string) {
    tokenManager.setToken(accessToken)
    if (refresh) {
      tokenManager.setRefreshToken(refresh)
    }
  }

  function clearAuth() {
    user.value = null
    tokenManager.clearToken()
    localStorage.removeItem('user')
  }

  async function login(uname: string, password: string) {
    loading.value = true
    try {
      const data = await request.post<LoginResponse>('/user/users/login', {
        username: uname,
        password,
      })
      setToken(data.access_token, data.refresh_token)
      await fetchProfile()
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
      await request.post('/user/users/logout')
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

    const userStr = localStorage.getItem('user')
    if (userStr) {
      try {
        user.value = JSON.parse(userStr)
      } catch {
        localStorage.removeItem('user')
      }
    }
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
    fetchProfile,
    updateProfile,
    logout,
    init,
    getUserIdFromToken,
  }
})
