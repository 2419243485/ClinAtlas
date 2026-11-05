<template>
  <div class="admin-page">
    <h2 class="section-title">系统管理</h2>

    <!-- 统计卡片 -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-icon stat-icon--blue"><el-icon><Document /></el-icon></div>
        <div class="stat-body">
          <div class="stat-value">{{ stats.documents?.ready ?? '-' }}</div>
          <div class="stat-label">已索引文档</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--yellow"><el-icon><Loading /></el-icon></div>
        <div class="stat-body">
          <div class="stat-value">{{ stats.documents?.processing ?? 0 }}</div>
          <div class="stat-label">处理中</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--green"><el-icon><ChatDotRound /></el-icon></div>
        <div class="stat-body">
          <div class="stat-value">{{ stats.searches_24h ?? '-' }}</div>
          <div class="stat-label">近 24h 查询数</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon stat-icon--purple"><el-icon><User /></el-icon></div>
        <div class="stat-body">
          <div class="stat-value">{{ stats.users ?? '-' }}</div>
          <div class="stat-label">用户总数</div>
        </div>
      </div>
    </div>

    <!-- 审计日志 -->
    <div class="log-section">
      <div class="log-header">
        <span class="section-subtitle">审计日志</span>
        <div class="log-filters">
          <el-select v-model="logAction" clearable placeholder="操作类型" style="width:130px" @change="loadLogs">
            <el-option label="检索"   value="search" />
            <el-option label="问答"   value="qa" />
            <el-option label="上传"   value="upload" />
            <el-option label="归档"   value="delete" />
          </el-select>
          <el-button @click="loadLogs" :loading="logLoading">
            <el-icon><Refresh /></el-icon>刷新
          </el-button>
        </div>
      </div>

      <el-table :data="logs" v-loading="logLoading" stripe style="width:100%" size="small">
        <el-table-column prop="user_id" label="用户 ID" width="220" show-overflow-tooltip />
        <el-table-column prop="action" label="操作" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="ACTION_TYPE[row.action] || 'info'">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="query" label="查询内容" min-width="200" show-overflow-tooltip />
        <el-table-column prop="ip" label="IP" width="130" />
        <el-table-column prop="timestamp" label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="logPage"
          :page-size="50"
          :total="logTotal"
          layout="total, prev, pager, next"
          @current-change="loadLogs"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../api'

const ACTION_TYPE = { search: 'primary', qa: 'success', upload: 'warning', delete: 'danger' }

const stats     = ref({})
const logs      = ref([])
const logTotal  = ref(0)
const logPage   = ref(1)
const logAction = ref('')
const logLoading = ref(false)

function formatTime(ts) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', { hour12: false }).slice(0, 16)
}

async function loadStats() {
  try { stats.value = await adminApi.stats() } catch {}
}

async function loadLogs() {
  logLoading.value = true
  try {
    const res = await adminApi.auditLogs({
      page:   logPage.value,
      size:   50,
      action: logAction.value || undefined,
    })
    logs.value     = res.items
    logTotal.value = res.items.length >= 50 ? logPage.value * 50 + 1 : (logPage.value - 1) * 50 + res.items.length
  } catch {
    ElMessage.error('加载审计日志失败')
  } finally {
    logLoading.value = false
  }
}

onMounted(() => {
  loadStats()
  loadLogs()
})
</script>

<style scoped>
.admin-page { display: flex; flex-direction: column; gap: 20px; }
.section-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.section-subtitle { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.stat-card {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
}
.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  flex-shrink: 0;
}
.stat-icon--blue   { background: #dbeafe; color: #2563eb; }
.stat-icon--yellow { background: #fef9c3; color: #d97706; }
.stat-icon--green  { background: #dcfce7; color: #16a34a; }
.stat-icon--purple { background: #ede9fe; color: #7c3aed; }
.stat-value { font-size: 26px; font-weight: 700; color: var(--text-primary); line-height: 1.2; }
.stat-label { font-size: 13px; color: var(--text-secondary); margin-top: 2px; }
.log-section {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.log-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
}
.log-filters { display: flex; gap: 8px; }
.pagination { display: flex; justify-content: flex-end; padding: 14px 16px; }

@media (max-width: 900px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
