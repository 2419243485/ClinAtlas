import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/qa' },
  { path: '/qa',       name: 'qa',        component: () => import('../views/QA.vue') },
  { path: '/documents', name: 'documents', component: () => import('../views/Documents.vue') },
  { path: '/admin',    name: 'admin',    component: () => import('../views/Admin.vue'), meta: { requireAdmin: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.isLoggedIn) return '/login'
  if (to.meta.requireAdmin && !auth.isAdmin) return '/qa'
})

export default router
