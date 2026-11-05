<template>
  <div class="source-card" :class="{ 'source-card--expanded': expanded }">
    <div class="source-header" @click="expanded = !expanded">
      <div class="source-meta">
        <span class="source-index">[来源{{ source.index }}]</span>
        <span class="source-filename">{{ source.filename }}</span>
        <el-tag v-if="source.department" size="small" type="info">{{ source.department }}</el-tag>
        <el-tag v-if="source.page" size="small" type="info">第 {{ source.page }} 页</el-tag>
        <el-tag size="small" type="success">v{{ source.version }}</el-tag>
      </div>
      <div class="source-right">
        <span class="relevance">相关度 {{ (source.relevance * 100).toFixed(0) }}%</span>
        <el-icon class="toggle-icon" :class="{ rotated: expanded }"><ArrowDown /></el-icon>
      </div>
    </div>
    <div v-if="expanded" class="source-text">{{ source.text }}</div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({ source: { type: Object, required: true } })
const expanded = ref(false)
</script>

<style scoped>
.source-card {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color 120ms;
}
.source-card:hover { border-color: var(--primary); }
.source-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  cursor: pointer;
  background: var(--surface);
  user-select: none;
}
.source-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.source-index { font-size: 12px; font-weight: 600; color: var(--primary); }
.source-filename { font-size: 13px; color: var(--text-primary); font-weight: 500; }
.source-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.relevance { font-size: 12px; color: var(--text-secondary); }
.toggle-icon { transition: transform 200ms; color: var(--text-secondary); }
.toggle-icon.rotated { transform: rotate(180deg); }
.source-text {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-regular);
  background: var(--bg);
  border-top: 1px solid var(--border);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
