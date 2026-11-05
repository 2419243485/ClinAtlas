<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="login-logo">
        <el-icon class="logo-icon"><FirstAidKit /></el-icon>
        <h1 class="logo-title">ClinAtlas</h1>
        <p class="logo-sub">医学知识库</p>
      </div>
      <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            size="large"
            :prefix-icon="User"
            autofocus
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            size="large"
            :prefix-icon="Lock"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width:100%;margin-top:8px"
          :loading="loading"
          @click="handleLogin"
        >
          登录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router  = useRouter()
const auth    = useAuthStore()
const formRef = ref()
const loading = ref(false)

const form = ref({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码',   trigger: 'blur' }],
}

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form.value.username, form.value.password)
    router.push('/qa')
  } catch (e) {
    ElMessage.error(e?.detail || '登录失败，请检查用户名或密码')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #e0eaff 0%, #f0f9ff 100%);
}
.login-card {
  background: var(--surface);
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0,0,0,0.10);
  padding: 40px 36px;
  width: 360px;
}
.login-logo {
  text-align: center;
  margin-bottom: 32px;
}
.logo-icon {
  font-size: 40px;
  color: var(--primary);
  display: block;
  margin: 0 auto 8px;
}
.logo-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}
.logo-sub {
  font-size: 13px;
  color: var(--text-secondary);
}
</style>
