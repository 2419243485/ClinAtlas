import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const token        = ref(localStorage.getItem('access_token') || '')
  const refreshToken = ref(localStorage.getItem('refresh_token') || '')
  const user         = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  const isLoggedIn   = computed(() => !!token.value)
  const isAdmin      = computed(() => user.value?.role === 'admin')

  async function login(username, password) {
    const res = await authApi.login({ username, password })
    token.value        = res.access_token
    refreshToken.value = res.refresh_token
    localStorage.setItem('access_token',  res.access_token)
    localStorage.setItem('refresh_token', res.refresh_token)

    // 从 JWT payload 解析用户信息（base64 decode 中间段）
    const payload = JSON.parse(atob(res.access_token.split('.')[1]))
    user.value = {
      user_id:    payload.sub,
      username:   payload.username,
      role:       payload.role,
      tenant_id:  payload.tenant_id,
      department: payload.department,
    }
    localStorage.setItem('user', JSON.stringify(user.value))
  }

  function logout() {
    token.value = ''
    refreshToken.value = ''
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
  }

  return { token, refreshToken, user, isLoggedIn, isAdmin, login, logout }
})
