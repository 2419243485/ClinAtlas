<template>
  <div class="qa-page">
    <div class="qa-left">
      <div class="qa-input-area">
        <h2 class="section-title">知识问答</h2>
        <el-input
          v-model="query"
          type="textarea"
          :rows="4"
          placeholder="输入您的医学问题，例如：胰岛素注射部位轮换原则？"
          resize="none"
          @keydown.ctrl.enter="handleSearch"
        />
        <div class="input-actions">
          <div class="filter-row">
            <el-select v-model="departments" multiple collapse-tags placeholder="科室筛选（可选）" style="width:220px">
              <el-option v-for="d in DEPARTMENTS" :key="d" :label="d" :value="d" />
            </el-select>
            <el-select v-model="sourceTypes" multiple collapse-tags placeholder="文档类型（可选）" style="width:200px">
              <el-option label="临床指南" value="clinical_guideline" />
              <el-option label="药品手册" value="drug_manual" />
              <el-option label="诊断标准" value="diagnosis_standard" />
              <el-option label="护理规范" value="nursing_protocol" />
            </el-select>
          </div>
          <el-button type="primary" :loading="loading" @click="handleSearch">
            <el-icon><Search /></el-icon>
            提问 (Ctrl+Enter)
          </el-button>
        </div>
      </div>

      <!-- 检索历史 -->
      <div class="history-area" v-if="history.length">
        <div class="section-title-sm">最近提问</div>
        <div
          v-for="(h, i) in history"
          :key="i"
          class="history-item"
          @click="query = h.query"
        >
          <el-icon><Clock /></el-icon>
          <span>{{ h.query }}</span>
        </div>
      </div>
    </div>

    <div class="qa-right">
      <!-- 空态 -->
      <div v-if="!answer && !loading" class="empty-state">
        <el-icon class="empty-icon"><ChatDotRound /></el-icon>
        <p>在左侧输入医学问题，按下提问开始检索</p>
        <p class="empty-hint">系统将从院内知识库中检索最相关的内容并给出回答</p>
      </div>

      <!-- 生成中 / 回答内容 -->
      <div v-else class="answer-area">
        <div class="answer-header">
          <span class="answer-label">回答</span>
          <el-tag v-if="sources.length" size="small" type="info">
            {{ sources.length }} 条来源
          </el-tag>
          <el-button v-if="answer" text size="small" @click="copyAnswer">
            <el-icon><CopyDocument /></el-icon>复制
          </el-button>
        </div>
        <div class="answer-text" ref="answerEl">
          <span>{{ answer }}</span>
          <span v-if="loading" class="cursor-blink">▌</span>
        </div>

        <!-- 来源卡片 -->
        <div v-if="sources.length" class="sources-section">
          <div class="section-title-sm">参考来源</div>
          <SourceCard v-for="src in sources" :key="src.index" :source="src" />
        </div>

        <!-- 反馈 -->
        <div v-if="answer && !loading" class="feedback-row">
          <span class="feedback-label">回答是否有帮助？</span>
          <el-rate v-model="rating" @change="submitFeedback" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { searchApi } from '../api'
import SourceCard from '../components/SourceCard.vue'

const DEPARTMENTS = ['内科', '外科', '内分泌科', '心血管科', 'ICU', '急诊科', '药剂科', '护理部']

const query       = ref('')
const departments = ref([])
const sourceTypes = ref([])
const loading     = ref(false)
const answer      = ref('')
const sources     = ref([])
const rating      = ref(0)
const lastQueryId = ref('')
const history     = ref([])
const answerEl    = ref()

onMounted(async () => {
  try {
    const res = await searchApi.history({ page: 1, size: 8 })
    history.value = res.items || []
  } catch {}
})

async function handleSearch() {
  if (!query.value.trim()) return
  loading.value = true
  answer.value  = ''
  sources.value = []
  rating.value  = 0

  const currentQuery = query.value.trim()

  try {
    // 用 fetch 消费 SSE 流
    const token = localStorage.getItem('access_token')
    const resp  = await fetch('/api/v1/search/qa', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        query: currentQuery,
        department_filter: departments.value.length ? departments.value : null,
        source_types: sourceTypes.value.length ? sourceTypes.value : null,
        top_k: 5,
      }),
    })

    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)

    const reader = resp.body.getReader()
    const dec    = new TextDecoder()
    let buf      = ''
    let event    = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += dec.decode(value, { stream: true })

      // 逐行解析 SSE：按 event 类型分发，data 均为 JSON（token 中的换行已转义）
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''

      for (const line of lines) {
        if (line.startsWith('event:')) { event = line.slice(6).trim(); continue }
        if (!line.startsWith('data:')) continue

        const data = line.slice(5).trim()
        if (event === 'done') { loading.value = false; break }
        if (event === 'sources') { sources.value = JSON.parse(data); continue }
        if (event === 'answer') {
          answer.value += JSON.parse(data)
          await nextTick()
          if (answerEl.value) answerEl.value.scrollTop = answerEl.value.scrollHeight
        }
      }
    }
  } catch (e) {
    ElMessage.error('请求失败，请稍后重试')
    console.error(e)
  } finally {
    loading.value = false
    // 刷新历史
    try {
      const res = await searchApi.history({ page: 1, size: 8 })
      history.value = res.items || []
    } catch {}
  }
}

function copyAnswer() {
  navigator.clipboard.writeText(answer.value)
  ElMessage.success('已复制')
}

async function submitFeedback(val) {
  if (!lastQueryId.value) return
  try {
    await searchApi.feedback({ query_id: lastQueryId.value, rating: val })
    ElMessage.success('感谢反馈')
  } catch {}
}
</script>

<style scoped>
.qa-page {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 20px;
  align-items: start;
}
.qa-left { display: flex; flex-direction: column; gap: 16px; }
.section-title { font-size: 16px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px; }
.section-title-sm { font-size: 13px; font-weight: 500; color: var(--text-secondary); margin-bottom: 8px; }
.qa-input-area {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow);
}
.input-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 12px; }
.filter-row { display: flex; gap: 8px; flex-wrap: wrap; }
.history-area {
  background: var(--surface);
  border-radius: var(--radius);
  padding: 16px 20px;
  box-shadow: var(--shadow);
}
.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 8px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--text-regular);
  cursor: pointer;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  transition: background 120ms;
}
.history-item:hover { background: var(--bg); color: var(--primary); }
.qa-right {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  min-height: 480px;
}
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 24px;
  color: var(--text-secondary);
  gap: 10px;
  text-align: center;
}
.empty-icon { font-size: 48px; color: #c0c4cc; }
.empty-hint { font-size: 13px; color: #c0c4cc; }
.answer-area { padding: 24px; }
.answer-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.answer-label { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.answer-text {
  font-size: 15px;
  line-height: 1.8;
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 400px;
  overflow-y: auto;
  margin-bottom: 20px;
}
.cursor-blink {
  animation: blink 1s step-start infinite;
  color: var(--primary);
}
@keyframes blink { 50% { opacity: 0; } }
.sources-section { margin-top: 20px; display: flex; flex-direction: column; gap: 8px; }
.feedback-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
.feedback-label { font-size: 13px; color: var(--text-secondary); }

@media (max-width: 900px) {
  .qa-page { grid-template-columns: 1fr; }
}
</style>
