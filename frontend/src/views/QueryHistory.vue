<template>
  <div class="page-container">
    <div class="page-header">
      <h2>查询历史</h2>
      <div class="filter-bar">
        <el-input
          v-model="searchKeyword"
          placeholder="搜索问题..."
          clearable
          :prefix-icon="Search"
          style="width: 240px"
          @input="onSearchInput"
          @clear="fetchHistory"
        />
        <el-select v-model="filterValue" placeholder="按来源筛选" clearable filterable @change="fetchHistory">
          <el-option-group label="数据集">
            <el-option
              v-for="ds in datasetOptions"
              :key="ds.id"
              :label="ds.name"
              :value="`ds:${ds.id}`"
            />
          </el-option-group>
          <el-option-group v-if="sourceOptions.length > 0" label="数据源">
            <el-option
              v-for="src in sourceOptions"
              :key="src.id"
              :label="`${src.name}（${src.db_type === 'mysql' ? 'MySQL' : 'PostgreSQL'}）`"
              :value="`src:${src.id}`"
            />
          </el-option-group>
        </el-select>
      </div>
    </div>

    <div class="page-section">
      <el-table :data="records" v-loading="loading" stripe @expand-change="onExpand">
        <!-- 展开行：预览 + 重跑 -->
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-content">
              <!-- 失败查询：展示错误 -->
              <el-alert
                v-if="!row.is_success"
                :title="row.error_message || '查询失败'"
                type="error"
                :closable="false"
                show-icon
              />

              <!-- 成功查询：预览数据 + 重跑按钮 -->
              <template v-else>
                <!-- 预览模式（未重跑或已收起重跑结果） -->
                <div v-if="!rerunResult[row.id]">
                  <div class="expand-header">
                    <span>
                      共 <strong>{{ row.result_count }}</strong> 行
                      <el-tag v-if="row.result_count > 20" size="small" type="info" class="preview-tag">
                        仅展示前 20 行预览
                      </el-tag>
                    </span>
                    <el-button
                      type="primary"
                      size="small"
                      :loading="rerunningId === row.id"
                      @click="handleRerun(row)"
                    >
                      <el-icon><Refresh /></el-icon>
                      重跑获取完整结果
                    </el-button>
                  </div>

                  <!-- 预览表格 -->
                  <el-table
                    v-if="row.result_preview && row.result_preview.length"
                    :data="row.result_preview"
                    stripe border size="small"
                    max-height="320"
                    class="preview-table"
                  >
                    <el-table-column
                      v-for="col in (row.result_columns || [])"
                      :key="col"
                      :prop="col"
                      :label="col"
                      min-width="120"
                      show-overflow-tooltip
                    />
                  </el-table>
                  <el-empty v-else description="无预览数据" :image-size="60" />
                </div>

                <!-- 重跑完整结果（增量替换预览，不重复展示） -->
                <div v-else class="rerun-result">
                  <div class="rerun-header">
                    <span>
                      重跑结果：共 <strong>{{ rerunResult[row.id].row_count }}</strong> 行
                    </span>
                    <el-button text size="small" @click="clearRerun(row.id)">收起</el-button>
                  </div>
                  <el-table
                    :data="rerunResult[row.id].data"
                    stripe border size="small"
                    max-height="400"
                  >
                    <el-table-column
                      v-for="col in (row.result_columns || [])"
                      :key="col"
                      :prop="col"
                      :label="col"
                      min-width="120"
                      show-overflow-tooltip
                    />
                  </el-table>
                </div>
              </template>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="来源" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <template v-if="row.dataset_name">
              <el-icon class="source-icon"><FolderOpened /></el-icon>
              {{ row.dataset_name }}
            </template>
            <template v-else-if="row.source_name">
              <el-tag size="small" class="source-tag"
                      :type="row.source_db_type === 'mysql' ? 'warning' : 'success'">
                {{ row.source_db_type === 'mysql' ? 'MySQL' : 'PG' }}
              </el-tag>
              {{ row.source_name }}
            </template>
            <span v-else class="text-tertiary">-</span>
          </template>
        </el-table-column>
        <el-table-column v-if="isAdmin" prop="username" label="查询人" width="90" />
        <el-table-column prop="question" label="问题" min-width="160" show-overflow-tooltip />
        <el-table-column label="SQL" min-width="200">
          <template #default="{ row }">
            <!-- 收起态：单行 truncate + 展开链接 -->
            <div v-if="expandedSqlId !== row.id" class="sql-collapsed">
              <span class="sql-preview" @click="toggleSql(row.id)">{{ row.generated_sql }}</span>
              <el-button link type="primary" size="small" class="sql-toggle" @click="toggleSql(row.id)">展开</el-button>
            </div>
            <!-- 展开态：完整 SQL 代码块 + 复制 + 收起 -->
            <div v-else class="sql-expanded">
              <div class="sql-expanded-header">
                <span class="sql-label">SQL</span>
                <div class="sql-expanded-actions">
                  <el-button link type="primary" size="small" :icon="DocumentCopy" @click="copySql(row.generated_sql)">复制</el-button>
                  <el-button link size="small" @click="toggleSql(row.id)">收起</el-button>
                </div>
              </div>
              <pre class="sql-code-block">{{ row.generated_sql }}</pre>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="70">
          <template #default="{ row }">
            <el-tag :type="row.is_success ? 'success' : 'danger'" size="small">
              {{ row.is_success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="行数" width="70">
          <template #default="{ row }">
            {{ row.is_success ? row.result_count : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="80">
          <template #default="{ row }">{{ row.execution_time_ms ? row.execution_time_ms + 'ms' : '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <div class="action-btns">
              <el-tooltip :content="row.dataset ? '查看数据集' : '查看数据源'" placement="top">
                <el-button v-if="row.dataset" class="action-icon-btn" link type="primary" :icon="View" @click="goDetail(row.dataset)" />
                <el-button v-else-if="row.source" class="action-icon-btn" link type="primary" :icon="Coin" @click="goSourceQuery(row.source)" />
              </el-tooltip>
              <el-tooltip
                :content="row.dataset ? '导出数据' : '外部数据源导出开发中'"
                placement="top"
              >
                <el-button
                  class="action-icon-btn"
                  link
                  type="success"
                  :icon="Download"
                  :disabled="!row.is_success || !row.dataset"
                  @click="openExportDialog(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="pagination-row">
      <el-pagination
        v-model:current-page="page"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="onPageChange"
      />
    </div>

    <!-- 导出格式选择对话框 -->
    <el-dialog v-model="exportDialogVisible" title="导出查询结果" width="380px">
      <el-radio-group v-model="exportFormat" class="export-format-group">
        <el-radio-button value="csv">CSV（通用）</el-radio-button>
        <el-radio-button value="xlsx">Excel</el-radio-button>
      </el-radio-group>
      <div class="export-hint">将导出完整查询结果（最多 1000 行），可能需要几秒</div>
      <template #footer>
        <el-button @click="exportDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="exporting" @click="confirmExport">导出</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, View, DocumentCopy, Download, Search, Coin, FolderOpened } from '@element-plus/icons-vue'
import { ElMessage, ElLoading } from 'element-plus'
import { queryApi } from '../api/query'
import { datasetApi } from '../api/dataset'
import { datasourceApi } from '../api/datasource'
import { exportApi, downloadBlob } from '../api/export'
import { useUserStore } from '../stores/user'

const router = useRouter()
const store = useUserStore()
const isAdmin = computed(() => store.user?.role === 'admin')
const loading = ref(false)
const records = ref<any[]>([])
const total = ref(0)
const page = ref(1)
// 来源筛选值：'ds:{id}'（数据集）或 'src:{id}'（外部数据源）
const filterValue = ref('')
const datasetOptions = ref<any[]>([])
const sourceOptions = ref<any[]>([])

// 搜索（防抖，避免每输一个字就请求）
const searchKeyword = ref('')
let searchTimer: ReturnType<typeof setTimeout> | null = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    fetchHistory()
  }, 400)
}

// 重跑状态：rerunningId 标记哪条正在重跑，rerunResult 存重跑结果
const rerunningId = ref<string | null>(null)
const rerunResult = reactive<Record<string, any>>({})

// SQL 展开状态：只展开一行（点击另一行自动收起前一行，类似手风琴）
const expandedSqlId = ref<string | null>(null)

function toggleSql(id: string) {
  expandedSqlId.value = expandedSqlId.value === id ? null : id
}

async function copySql(sql: string) {
  try {
    await navigator.clipboard.writeText(sql)
    ElMessage.success('SQL 已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

// 导出：调 /api/export/<id>/<fmt>/，后端内部重跑 SQL 取完整结果（≤1000 行）
const exportDialogVisible = ref(false)
const exportFormat = ref<'csv' | 'xlsx'>('csv')
const exporting = ref(false)
const exportRow = ref<any>(null)

function openExportDialog(row: any) {
  exportRow.value = row
  exportFormat.value = 'csv'
  exportDialogVisible.value = true
}

async function confirmExport() {
  if (!exportRow.value) return
  exporting.value = true
  const loading = ElLoading.service({ fullscreen: true, text: '导出中，请稍候...' })
  try {
    const res = await exportApi.exportFile(exportRow.value.id, exportFormat.value)
    const ext = exportFormat.value === 'csv' ? '.csv' : '.xlsx'
    const filename = `${exportRow.value.dataset_name
      || exportRow.value.source_name || 'query'}_result${ext}`
    downloadBlob(res.data as Blob, filename)
    ElMessage.success('导出成功')
    exportDialogVisible.value = false
  } catch {
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
    loading.close()
  }
}

onMounted(async () => {
  fetchHistory()
  const res = await datasetApi.getList()
  datasetOptions.value = res.data.results
  // 数据源选项（viewer 无权限访问数据源接口，静默跳过不显示该分组）
  try {
    const srcRes = await datasourceApi.getList()
    sourceOptions.value = srcRes.data
  } catch {
    sourceOptions.value = []
  }
})

async function fetchHistory() {
  loading.value = true
  try {
    const params: any = { page: page.value }
    if (filterValue.value) {
      const [kind, id] = filterValue.value.split(':')
      if (kind === 'ds') params.dataset_id = id
      else if (kind === 'src') params.source_id = id
    }
    if (searchKeyword.value) params.search = searchKeyword.value
    const res = await queryApi.getHistory(params)
    records.value = res.data.results
    total.value = res.data.count
  } finally {
    loading.value = false
  }
}

function onPageChange(p: number) {
  page.value = p
  fetchHistory()
}

function goDetail(datasetId: string) {
  router.push({ name: 'dataset-detail', params: { id: datasetId } })
}

function goSourceQuery(sourceId: string) {
  router.push(`/datasources/${sourceId}/query`)
}

/**
 * 行展开回调：可用于按需加载（当前预览已在列表数据里，无需额外请求）
 */
function onExpand(_row: any, _expanded: any[]) {
  // 预留：如果以后预览改成懒加载，在这里触发
}

/**
 * 重跑：用历史 SQL 重新执行，拿完整结果展示在展开行内
 */
async function handleRerun(row: any) {
  rerunningId.value = row.id
  try {
    const res = await queryApi.rerun(row.id)
    rerunResult[row.id] = res.data
    ElMessage.success(`重跑完成，共 ${res.data.row_count} 行`)
  } catch (e: any) {
    const msg = e?.response?.data?.error || '重跑失败'
    ElMessage.error(msg)
  } finally {
    rerunningId.value = null
  }
}

function clearRerun(id: string) {
  delete rerunResult[id]
}

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}
</script>

<style scoped>
/* 筛选栏：搜索框 + 数据集下拉并排 */
/* 来源列：数据集图标 / 外部数据源类型 tag */
.source-icon {
  vertical-align: -2px;
  margin-right: 4px;
  color: var(--el-text-color-secondary);
}
.source-tag {
  margin-right: 4px;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* SQL 列：收起态（单行 truncate + 展开按钮）*/
.sql-collapsed {
  display: flex;
  align-items: center;
  gap: 6px;
}

.sql-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--brand-font-mono);
  font-size: 12px;
  color: var(--brand-text-secondary);
  background: var(--brand-code-bg);
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
}

.sql-toggle {
  flex-shrink: 0;
  padding: 2px 4px;
  font-size: 12px;
}

/* SQL 列：展开态（完整代码块 + 复制按钮）*/
.sql-expanded {
  width: 100%;
}

.sql-expanded-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.sql-label {
  font-size: 12px;
  color: var(--brand-text-tertiary);
  font-weight: 500;
}

.sql-expanded-actions {
  display: flex;
  gap: 4px;
}

.sql-code-block {
  margin: 0;
  padding: 10px 12px;
  background: var(--brand-code-bg);
  border-radius: var(--brand-radius-md);
  font-family: var(--brand-font-mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--brand-text-primary);
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

/* 操作列图标按钮：加大点击热区（方形 36×36）*/
.action-icon-btn {
  width: 36px;
  height: 36px;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: var(--brand-radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  transition: background 0.15s ease;
}

.action-icon-btn:hover {
  background: var(--brand-primary-light-9);
}

/* 操作列按钮组：图标按钮紧凑排列 */
.action-btns {
  display: inline-flex;
  align-items: center;
  gap: 2px;
}

/* 导出格式选择对话框 */
.export-format-group {
  display: flex;
  justify-content: center;
  width: 100%;
  margin-bottom: 12px;
}

.export-format-group :deep(.el-radio-button) {
  flex: 1;
}

.export-format-group :deep(.el-radio-button__inner) {
  width: 100%;
}

.export-hint {
  text-align: center;
  font-size: 12px;
  color: var(--brand-text-tertiary);
}

.expand-content {
  padding: 16px 20px;
  background: var(--el-fill-color-light);
}

.expand-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.preview-tag {
  margin-left: 8px;
}

.preview-table {
  margin-bottom: 16px;
}

.rerun-result {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px dashed var(--el-border-color);
}

.rerun-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
</style>
