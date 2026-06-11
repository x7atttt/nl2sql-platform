<template>
  <div class="page-container">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/datasets')">返回</el-button>
        <h2>{{ dataset?.name || '数据集详情' }}</h2>
      </div>
      <el-tag v-if="dataset" :type="statusType(dataset.status)">{{ statusLabel(dataset.status) }}</el-tag>
    </div>

    <div v-if="dataset" class="info-row">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="文件名">{{ dataset.file_name }}</el-descriptions-item>
        <el-descriptions-item label="行数">{{ dataset.row_count }}</el-descriptions-item>
        <el-descriptions-item label="列数">{{ dataset.column_count }}</el-descriptions-item>
        <el-descriptions-item label="文件大小">{{ formatSize(dataset.file_size) }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <el-tabs v-model="activeTab" v-loading="loading">
      <el-tab-pane label="数据分析" name="analysis">
        <div v-if="analysis" class="analysis-section">
          <h4>列统计信息</h4>
          <el-table :data="analysis.column_stats.columns" stripe border size="small">
            <el-table-column prop="name" label="列名" min-width="120" />
            <el-table-column prop="type" label="类型" width="80">
              <template #default="{ row }">
                <el-tag size="small">{{ row.type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="空值" width="70">
              <template #default="{ row }">{{ row.null_count }}</template>
            </el-table-column>
            <el-table-column label="唯一值" width="70">
              <template #default="{ row }">{{ row.distinct_count }}</template>
            </el-table-column>
            <el-table-column label="最小值" width="90">
              <template #default="{ row }">{{ row.min ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="最大值" width="90">
              <template #default="{ row }">{{ row.max ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="平均值" width="90">
              <template #default="{ row }">{{ row.avg ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="中位数" width="90">
              <template #default="{ row }">{{ row.median ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="高频值" min-width="200">
              <template #default="{ row }">
                <span v-if="row.top_values">
                  {{ row.top_values.slice(0, 5).map((v: any) => `${v.value}(${v.count})`).join(', ') }}
                </span>
                <span v-else>-</span>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <el-empty v-else-if="!loading" description="暂无分析数据" />
      </el-tab-pane>

      <el-tab-pane label="自然语言查询" name="query">
        <div class="query-workspace">
          <div class="query-input-row">
            <el-input
              v-model="question"
              placeholder="用自然语言查询数据..."
              size="large"
              @keyup.enter="handleQuery"
              :disabled="queryLoading"
            >
              <template #append>
                <el-button :icon="Search" :loading="queryLoading" @click="handleQuery" />
              </template>
            </el-input>
          </div>

          <div v-if="queryResult" class="result-section">
            <div v-if="queryResult.success" class="result-success">
              <div class="result-header">
                <span>查询到 {{ queryResult.row_count }} 条数据，耗时 {{ queryResult.execution_time_ms }}ms</span>
              </div>

              <el-table
                :data="queryResult.data"
                stripe border size="small"
                max-height="400" class="result-table"
              >
                <el-table-column
                  v-for="col in resultColumns"
                  :key="col"
                  :prop="col"
                  :label="col"
                  min-width="120"
                  show-overflow-tooltip
                />
              </el-table>

              <el-collapse class="sql-collapse">
                <el-collapse-item title="查看生成的 SQL">
                  <code class="sql-code">{{ queryResult.sql }}</code>
                </el-collapse-item>
              </el-collapse>

              <div v-if="canExport" class="export-row">
                <el-button :icon="Download" @click="handleExport('csv')">导出 CSV</el-button>
                <el-button :icon="Download" @click="handleExport('xlsx')">导出 Excel</el-button>
              </div>
            </div>

            <el-alert
              v-else
              :title="queryResult.error || '查询失败'"
              type="error"
              show-icon
              :description="`SQL: ${queryResult.sql}`"
            />
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Search, ArrowLeft, Download } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { datasetApi } from '../api/dataset'
import { queryApi } from '../api/query'
import { exportApi, downloadBlob } from '../api/export'
import { ElMessage } from 'element-plus'

const route = useRoute()
const store = useUserStore()

const loading = ref(false)
const dataset = ref<any>(null)
const analysis = ref<any>(null)
const activeTab = ref('analysis')

const question = ref('')
const queryLoading = ref(false)
const queryResult = ref<any>(null)
const currentQueryId = ref<string | null>(null)

const canExport = computed(() => {
  const role = store.user?.role
  return role === 'admin' || role === 'analyst'
})

const resultColumns = computed(() => {
  if (!queryResult.value?.data?.length) return []
  return Object.keys(queryResult.value.data[0])
})

async function loadDataset(id: string) {
  loading.value = true
  queryResult.value = null
  currentQueryId.value = null
  try {
    const [detailRes, analysisRes] = await Promise.all([
      datasetApi.getDetail(id),
      datasetApi.getAnalysis(id).catch(() => ({ data: null })),
    ])
    dataset.value = detailRes.data
    analysis.value = analysisRes.data
  } finally {
    loading.value = false
  }
}

watch(() => route.params.id, (id) => {
  if (id) loadDataset(id as string)
}, { immediate: true })

async function handleQuery() {
  const id = route.params.id as string
  if (!question.value.trim()) {
    ElMessage.warning('请输入查询问题')
    return
  }
  queryLoading.value = true
  queryResult.value = null
  try {
    const res = await queryApi.query(id, question.value)
    queryResult.value = res.data
    currentQueryId.value = res.data.query_id || null
    if (!res.data.success) {
      ElMessage.error(res.data.error || '查询失败')
    }
  } finally {
    queryLoading.value = false
  }
}

async function handleExport(format: 'csv' | 'xlsx') {
  if (!currentQueryId.value) {
    ElMessage.error('未找到查询记录，无法导出')
    return
  }
  try {
    const res = await exportApi.exportFile(currentQueryId.value, format)
    const ext = format === 'csv' ? '.csv' : '.xlsx'
    const filename = `${dataset.value?.name || 'export'}_result${ext}`
    downloadBlob(res.data as Blob, filename)
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  }
}

function statusType(s: string) {
  const map: Record<string, string> = { completed: 'success', processing: '', pending: 'info', failed: 'danger' }
  return map[s] || 'info'
}

function statusLabel(s: string) {
  const map: Record<string, string> = { completed: '已完成', processing: '处理中', pending: '等待中', failed: '失败' }
  return map[s] || s
}

function formatSize(bytes: number) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}
</script>

<style scoped>
.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.info-row {
  margin-bottom: 20px;
}

.analysis-section h4 {
  margin-bottom: 12px;
  color: #303133;
}

.query-workspace {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.query-input-row {
  max-width: 800px;
}

.result-section {
  margin-top: 8px;
}

.result-header {
  margin-bottom: 8px;
  font-size: 14px;
  color: #606266;
}

.result-table {
  margin-bottom: 12px;
}

.sql-collapse {
  margin-bottom: 12px;
}

.sql-code {
  display: block;
  padding: 12px;
  background: #f5f7fa;
  border-radius: 4px;
  font-family: 'Courier New', monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
}

.export-row {
  display: flex;
  gap: 12px;
}
</style>
