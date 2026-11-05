<template>
  <div class="docs-page">
    <div class="page-header">
      <h2 class="section-title">文档管理</h2>
      <el-button type="primary" @click="showUpload = true">
        <el-icon><Upload /></el-icon>上传文档
      </el-button>
    </div>

    <!-- 筛选条件 -->
    <div class="filter-bar">
      <el-select v-model="filterDept" clearable placeholder="科室" style="width:140px" @change="loadDocs">
        <el-option v-for="d in DEPARTMENTS" :key="d" :label="d" :value="d" />
      </el-select>
      <el-select v-model="filterStatus" clearable placeholder="状态" style="width:120px" @change="loadDocs">
        <el-option label="处理中" value="processing" />
        <el-option label="已就绪" value="ready" />
        <el-option label="失败"   value="failed" />
      </el-select>
    </div>

    <!-- 文档表格 -->
    <div class="table-wrap">
      <el-table :data="docs" v-loading="tableLoading" stripe style="width:100%">
        <el-table-column prop="filename" label="文件名" min-width="220" show-overflow-tooltip />
        <el-table-column prop="department" label="科室" width="110" />
        <el-table-column prop="source_type" label="类型" width="130">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ SOURCE_LABEL[row.source_type] || row.source_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="80" />
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="STATUS_TYPE[row.status]">{{ STATUS_LABEL[row.status] }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="uploaded_at" label="上传时间" width="170">
          <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text size="small" @click="reindex(row)" :disabled="row.status === 'processing'">
              重新索引
            </el-button>
            <el-popconfirm title="确认归档该文档？" @confirm="archiveDoc(row)">
              <template #reference>
                <el-button text size="small" type="danger">归档</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next"
          @change="loadDocs"
        />
      </div>
    </div>

    <!-- 上传对话框 -->
    <el-dialog v-model="showUpload" title="上传文档" width="480px" :close-on-click-modal="false">
      <el-form :model="uploadForm" label-width="80px">
        <el-form-item label="文件">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            accept=".pdf,.docx,.doc"
            :on-change="(f) => uploadForm.file = f.raw"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="upload-tip">拖拽或点击上传，支持 PDF / DOCX</div>
          </el-upload>
        </el-form-item>
        <el-form-item label="科室">
          <el-select v-model="uploadForm.department" placeholder="选择科室" style="width:100%">
            <el-option v-for="d in DEPARTMENTS" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="文档类型">
          <el-select v-model="uploadForm.source_type" style="width:100%">
            <el-option label="临床指南"   value="clinical_guideline" />
            <el-option label="药品手册"   value="drug_manual" />
            <el-option label="诊断标准"   value="diagnosis_standard" />
            <el-option label="护理规范"   value="nursing_protocol" />
            <el-option label="其他"       value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="uploadForm.version" placeholder="1.0" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUpload = false">取消</el-button>
        <el-button type="primary" :loading="uploading" @click="handleUpload">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { docsApi } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()

const DEPARTMENTS = ['内科', '外科', '内分泌科', '心血管科', 'ICU', '急诊科', '药剂科', '护理部']
const SOURCE_LABEL = {
  clinical_guideline: '临床指南',
  drug_manual:        '药品手册',
  diagnosis_standard: '诊断标准',
  nursing_protocol:   '护理规范',
  other:              '其他',
}
const STATUS_LABEL = { pending: '等待中', processing: '处理中', ready: '已就绪', failed: '失败', archived: '已归档' }
const STATUS_TYPE  = { pending: 'info', processing: 'warning', ready: 'success', failed: 'danger', archived: '' }

const docs         = ref([])
const total        = ref(0)
const page         = ref(1)
const pageSize     = ref(20)
const tableLoading = ref(false)
const filterDept   = ref('')
const filterStatus = ref('')
const showUpload   = ref(false)
const uploading    = ref(false)

const uploadForm = ref({ file: null, department: '', source_type: 'other', version: '1.0' })

function formatTime(ts) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN', { hour12: false }).slice(0, 16)
}

async function loadDocs() {
  tableLoading.value = true
  try {
    const res = await docsApi.list({
      page: page.value,
      size: pageSize.value,
      department:    filterDept.value   || undefined,
      status_filter: filterStatus.value || undefined,
    })
    docs.value  = res.items
    total.value = res.total
  } catch {
    ElMessage.error('加载文档列表失败')
  } finally {
    tableLoading.value = false
  }
}

async function handleUpload() {
  if (!uploadForm.value.file) return ElMessage.warning('请选择文件')
  uploading.value = true
  const fd = new FormData()
  fd.append('file', uploadForm.value.file)
  fd.append('department',  uploadForm.value.department)
  fd.append('source_type', uploadForm.value.source_type)
  fd.append('version',     uploadForm.value.version)
  try {
    await docsApi.upload(fd)
    ElMessage.success('上传成功，后台处理中')
    showUpload.value = false
    uploadForm.value = { file: null, department: '', source_type: 'other', version: '1.0' }
    await loadDocs()
  } catch (e) {
    ElMessage.error(e?.detail || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function archiveDoc(row) {
  try {
    await docsApi.archive(row.doc_id)
    ElMessage.success('已归档')
    await loadDocs()
  } catch (e) {
    ElMessage.error(e?.detail || '归档失败')
  }
}

async function reindex(row) {
  try {
    await docsApi.reindex(row.doc_id)
    ElMessage.success('重新索引任务已提交')
    await loadDocs()
  } catch (e) {
    ElMessage.error(e?.detail || '提交失败')
  }
}

onMounted(loadDocs)
</script>

<style scoped>
.docs-page { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; }
.section-title { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.filter-bar { display: flex; gap: 10px; flex-wrap: wrap; }
.table-wrap {
  background: var(--surface);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.pagination { display: flex; justify-content: flex-end; padding: 16px; }
.upload-icon { font-size: 40px; color: #c0c4cc; display: block; margin: 16px auto 8px; }
.upload-tip { font-size: 13px; color: var(--text-secondary); text-align: center; padding-bottom: 16px; }
</style>
