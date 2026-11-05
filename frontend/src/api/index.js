import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const http = axios.create({ baseURL: '/api/v1', timeout: 120000 })

// 请求拦截：自动注入 Authorization
http.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) config.headers.Authorization = `Bearer ${auth.token}`
  return config
})

// 响应拦截：401 跳登录页
http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      const auth = useAuthStore()
      auth.logout()
      window.location.href = '/login'
    }
    return Promise.reject(err.response?.data || err)
  }
)

export const authApi = {
  login: (data) => http.post('/auth/login', data),
  refresh: (token) => http.post('/auth/refresh', null, { params: { refresh_token_str: token } }),
}

export const docsApi = {
  upload: (formData) => http.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  list: (params) => http.get('/documents', { params }),
  get: (id) => http.get(`/documents/${id}`),
  archive: (id) => http.delete(`/documents/${id}`),
  reindex: (id) => http.post(`/documents/${id}/reindex`),
}

export const searchApi = {
  search: (data) => http.post('/search', data),
  history: (params) => http.get('/search/history', { params }),
  feedback: (data) => http.post('/search/feedback', data),
}

export const adminApi = {
  stats: () => http.get('/admin/stats'),
  auditLogs: (params) => http.get('/admin/audit-logs', { params }),
  health: () => http.get('/admin/health'),
}

export default http
