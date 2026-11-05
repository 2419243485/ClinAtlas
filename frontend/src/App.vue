<template>
  <div class="app-layout">
    <NavBar v-if="auth.isLoggedIn" />
    <router-view class="app-content" />
  </div>
</template>

<script setup>
import { useAuthStore } from './stores/auth'
import NavBar from './components/NavBar.vue'

const auth = useAuthStore()
</script>

<style>
:root {
  --bg: #f5f7fa;
  --surface: #ffffff;
  --border: #e4e7ed;
  --text-primary: #303133;
  --text-regular: #606266;
  --text-secondary: #909399;
  --primary: #2563eb;
  --primary-light: #dbeafe;
  --success: #16a34a;
  --warning: #d97706;
  --danger: #dc2626;
  --radius: 8px;
  --radius-sm: 4px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
  background: var(--bg);
  color: var(--text-primary);
  line-height: 1.6;
}

.app-layout { min-height: 100vh; display: flex; flex-direction: column; }
.app-content { flex: 1; padding: 24px; max-width: 1200px; margin: 0 auto; width: 100%; }

.el-button--primary { --el-button-bg-color: var(--primary); --el-button-border-color: var(--primary); }
</style>
