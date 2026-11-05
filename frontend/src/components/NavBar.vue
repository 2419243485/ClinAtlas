<template>
  <nav class="navbar">
    <div class="navbar-brand">
      <el-icon class="brand-icon"><FirstAidKit /></el-icon>
      <span class="brand-name">ClinAtlas</span>
    </div>
    <div class="navbar-menu">
      <router-link to="/qa" class="nav-item" active-class="nav-item--active">
        <el-icon><ChatDotRound /></el-icon>知识问答
      </router-link>
      <router-link to="/documents" class="nav-item" active-class="nav-item--active">
        <el-icon><Document /></el-icon>文档管理
      </router-link>
      <router-link v-if="auth.isAdmin" to="/admin" class="nav-item" active-class="nav-item--active">
        <el-icon><Setting /></el-icon>系统管理
      </router-link>
    </div>
    <div class="navbar-user">
      <span class="user-info">{{ auth.user?.username }}</span>
      <el-tag size="small" :type="auth.isAdmin ? 'danger' : 'info'">
        {{ auth.user?.role }}
      </el-tag>
      <el-button text @click="handleLogout">退出</el-button>
    </div>
  </nav>
</template>

<script setup>
import { useAuthStore } from '../stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<style scoped>
.navbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 24px;
  height: 56px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.navbar-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: 24px;
}
.brand-icon { font-size: 22px; color: var(--primary); }
.brand-name { font-size: 17px; font-weight: 600; color: var(--text-primary); letter-spacing: 0.3px; }
.navbar-menu { display: flex; gap: 4px; flex: 1; }
.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  color: var(--text-regular);
  text-decoration: none;
  font-size: 14px;
  transition: background 120ms, color 120ms;
}
.nav-item:hover { background: var(--bg); color: var(--primary); }
.nav-item--active { background: var(--primary-light); color: var(--primary); font-weight: 500; }
.navbar-user {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-left: auto;
}
.user-info { font-size: 13px; color: var(--text-secondary); }
</style>
