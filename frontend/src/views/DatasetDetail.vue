<template>
  <div class="page-container">
    <div class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/datasets')">返回</el-button>
        <h2>{{ dataset?.name || '数据集详情' }}</h2>
      </div>
      <div class="header-right">
        <el-button
          v-if="canManage"
          :icon="EditPen"
          @click="openEditDialog"
        >
          编辑业务说明
        </el-button>
        <el-button
          v-if="canShare"
          type="primary"
          :icon="Share"
          :disabled="!canShareThisDataset"
          @click="openShareDialog"
        >
          分享数据集
        </el-button>
        <el-tag v-if="dataset" :type="statusType(dataset.status)" size="large">{{ statusLabel(dataset.status) }}</el-tag>
      </div>
    </div>

    <div v-if="dataset" class="info-row page-section">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="文件名">{{ dataset.file_name }}</el-descriptions-item>
        <el-descriptions-item label="行数">{{ dataset.row_count }}</el-descriptions-item>
        <el-descriptions-item label="列数">{{ dataset.column_count }}</el-descriptions-item>
        <el-descriptions-item label="文件大小">{{ formatSize(dataset.file_size) }}</el-descriptions-item>
        <el-descriptions-item label="业务说明" :span="4">
          <span v-if="dataset.business_description" class="business-desc">{{ dataset.business_description }}</span>
          <span v-else class="business-desc-empty">（未填写，NL2SQL 仅依赖列统计生成 SQL）</span>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <el-tabs v-if="dataset" v-model="activeTab" class="detail-tabs">
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
            <el-table-column label="高频值" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <span v-if="row.top_values" class="top-values">
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
          <!-- AI 推荐查询：上传后自动生成 4 条，点击只填入查询框不执行 -->
          <div
            v-if="dataset.suggested_questions && dataset.suggested_questions.length > 0"
            class="suggested-questions page-section"
          >
            <div class="sq-header">
              <el-icon class="sq-icon"><MagicStick /></el-icon>
              <span class="sq-title">试试这些问题</span>
            </div>
            <div class="sq-grid">
              <button
                v-for="(q, i) in dataset.suggested_questions"
                :key="i"
                class="sq-card"
                :class="{ active: question === q }"
                @click="question = q"
              >
                {{ q }}
              </button>
            </div>
          </div>

          <div class="query-input-card page-section">
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

          <!-- AI 思考动画：查询进行中显示，降低用户等待焦虑 -->
          <div v-if="queryLoading" class="thinking-card page-section">
            <div class="thinking-content">
              <div class="thinking-dots">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
              </div>
              <span class="thinking-text">{{ thinkingText }}</span>
            </div>
          </div>

          <div v-if="queryResult && !queryLoading" class="result-section">
            <div v-if="queryResult.success" class="result-success">
              <div class="result-header">
                <span>查询到 <strong>{{ queryResult.row_count }}</strong> 条数据，耗时 {{ queryResult.execution_time_ms }}ms</span>
              </div>

              <div class="result-table-wrapper">
                <el-table
                  :data="queryResult.data"
                  stripe border size="small"
                  max-height="400"
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
              </div>

              <div class="sql-block">
                <div class="sql-block-header">
                  <span>SQL</span>
                  <el-button text size="small" @click="copySql">
                    <el-icon><DocumentCopy /></el-icon> 复制
                  </el-button>
                </div>
                <pre>{{ queryResult.sql }}</pre>
              </div>

              <!-- 查询结果自动可视化（规则引擎先画默认图 + 后台异步调 LLM 智能优化） -->
              <ResultChart
                v-if="queryResult.data && queryResult.data.length > 0"
                :data="queryResult.data"
                :columns="resultColumns"
                :column-types="queryResult.column_types || {}"
                :query-id="currentQueryId || undefined"
              />

              <div v-if="canExport" class="export-row">
                <el-button @click="handleExport('csv')">
                  <el-icon><Download /></el-icon> 导出 CSV
                </el-button>
                <el-button @click="handleExport('xlsx')">
                  <el-icon><Download /></el-icon> 导出 Excel
                </el-button>
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
    <div v-else v-loading="true" class="detail-tabs-loading"></div>

    <!-- 分享数据集弹窗 -->
    <el-dialog v-model="shareDialogVisible" title="分享数据集" width="440px">
      <el-form label-width="80px">
        <el-form-item label="数据集">
          <span>{{ dataset?.name }}</span>
        </el-form-item>
        <el-form-item label="分享给">
          <el-select
            v-model="shareTargetId"
            placeholder="选择用户"
            filterable
            :loading="shareUsersLoading"
            style="width: 100%"
          >
            <el-option
              v-for="u in shareableUsers"
              :key="u.id"
              :label="`${u.username}（${roleLabel(u.role)}）`"
              :value="u.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="shareDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="sharing"
          :disabled="!shareTargetId"
          @click="handleShare"
        >
          确认分享
        </el-button>
      </template>
    </el-dialog>

    <!-- 编辑业务说明弹窗 -->
    <el-dialog v-model="editDialogVisible" title="编辑业务说明" width="600px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      >
        业务说明会注入 NL2SQL 提示词，帮助 AI 理解字段业务语义（列统计只告诉它"数据长什么样"，业务说明告诉它"数据是什么意思"）。
      </el-alert>
      <el-form label-width="80px">
        <el-form-item label="业务说明">
          <el-input
            v-model="editBusinessDesc"
            type="textarea"
            :rows="8"
            maxlength="2000"
            show-word-limit
            placeholder="填写数据集业务背景/字段含义，例如：
region: 销售大区（east=华东, north=华北, south=华南, west=西部）
amount: 订单金额（人民币元，含税）
status: 订单状态（paid=已支付, pending=待付款, refunded=已退款）
created_at: 下单时间（UTC）"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingDesc" @click="saveBusinessDesc">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { Search, ArrowLeft, Download, DocumentCopy, Share, EditPen, MagicStick } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { datasetApi } from '../api/dataset'
import { queryApi } from '../api/query'
import { exportApi, downloadBlob } from '../api/export'
import ResultChart from '../components/ResultChart.vue'
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

// AI 思考动画：查询进行中循环切换文案，降低用户等待焦虑
const thinkingTexts = [
  '正在分析数据结构',
  '正在生成 SQL 查询',
  '正在校验安全性',
  '正在执行查询',
  '正在整理结果',
]
const thinkingText = ref(thinkingTexts[0])
let thinkingTimer: ReturnType<typeof setInterval> | null = null
let thinkingIndex = 0

function startThinking() {
  thinkingIndex = 0
  thinkingText.value = thinkingTexts[0]
  thinkingTimer = setInterval(() => {
    thinkingIndex = (thinkingIndex + 1) % thinkingTexts.length
    thinkingText.value = thinkingTexts[thinkingIndex]
  }, 1800) // 每 1.8 秒切换一句，配合 NL2SQL 5 步流水线的体感
}

function stopThinking() {
  if (thinkingTimer) {
    clearInterval(thinkingTimer)
    thinkingTimer = null
  }
}

onUnmounted(stopThinking)

const canExport = computed(() => {
  const role = store.user?.role
  return role === 'admin' || role === 'analyst'
})

// 业务说明编辑：admin 全部可改，analyst 只能改自己 owner 的（与 share 权限对齐）
const canManage = computed(() => {
  if (!dataset.value) return false
  const role = store.user?.role
  if (role === 'admin') return true
  if (role === 'analyst') return dataset.value.owner === store.user?.id
  return false
})

// 业务说明编辑弹窗状态
const editDialogVisible = ref(false)
const editBusinessDesc = ref('')
const savingDesc = ref(false)

// 分享功能：admin/analyst 可见按钮；analyst 只能分享自己 owner 的
const canShare = computed(() => {
  const role = store.user?.role
  return role === 'admin' || role === 'analyst'
})
const canShareThisDataset = computed(() => {
  if (!dataset.value) return false
  const role = store.user?.role
  if (role === 'admin') return true                        // admin 能分享任意
  if (role === 'analyst') return dataset.value.owner === store.user?.id  // analyst 只能分享自己的
  return false
})

// 分享弹窗状态
const shareDialogVisible = ref(false)
const shareableUsers = ref<{ id: number; username: string; role: string }[]>([])
const shareUsersLoading = ref(false)
const shareTargetId = ref<number | null>(null)
const sharing = ref(false)

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
  startThinking()
  try {
    const res = await queryApi.query(id, question.value)
    queryResult.value = res.data
    currentQueryId.value = res.data.query_id || null
    if (!res.data.success) {
      ElMessage.error(res.data.error || '查询失败')
    }
  } finally {
    queryLoading.value = false
    stopThinking()
  }
}

function copySql() {
  if (!queryResult.value?.sql) return
  navigator.clipboard.writeText(queryResult.value.sql)
  ElMessage.success('SQL 已复制')
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

async function openShareDialog() {
  shareDialogVisible.value = true
  shareTargetId.value = null
  shareUsersLoading.value = true
  try {
    const res = await datasetApi.getShareableUsers()
    shareableUsers.value = res.data
  } catch {
    ElMessage.error('获取用户列表失败')
  } finally {
    shareUsersLoading.value = false
  }
}

async function handleShare() {
  if (!shareTargetId.value || !dataset.value) return
  sharing.value = true
  try {
    const res = await datasetApi.share(dataset.value.id, shareTargetId.value)
    ElMessage.success(res.data.message || '分享成功')
    shareDialogVisible.value = false
  } catch (e: any) {
    const msg = e?.response?.data?.error || '分享失败'
    ElMessage.error(msg)
  } finally {
    sharing.value = false
  }
}

function roleLabel(role: string) {
  const map: Record<string, string> = { admin: '管理员', analyst: '分析师', viewer: '只读用户' }
  return map[role] || role
}

function openEditDialog() {
  // 打开编辑弹窗前回填当前业务说明（避免上次输入残留）
  editBusinessDesc.value = dataset.value?.business_description || ''
  editDialogVisible.value = true
}

async function saveBusinessDesc() {
  if (!dataset.value) return
  savingDesc.value = true
  try {
    await datasetApi.update(dataset.value.id, { business_description: editBusinessDesc.value })
    // 同步本地状态，避免再拉一次详情
    dataset.value.business_description = editBusinessDesc.value
    editDialogVisible.value = false
    ElMessage.success('业务说明已更新，下次查询将注入新内容')
  } catch (e: any) {
    const msg = e?.response?.data?.error || e?.response?.data?.detail || '保存失败'
    ElMessage.error(msg)
  } finally {
    savingDesc.value = false
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

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.info-row {
  margin-bottom: var(--space-lg);
  padding: var(--space-md) var(--space-lg);
}

.detail-tabs {
  background: transparent;
}

.detail-tabs-loading {
  min-height: 200px;
}

.analysis-section h4 {
  margin-bottom: 12px;
  color: var(--brand-text-primary);
  font-weight: 600;
}

/* 高频值单元格：内容超长时省略，配合 el-table show-overflow-tooltip 悬浮查看 */
.top-values {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.query-workspace {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
}

.query-input-card {
  padding: var(--space-lg);
  max-width: 800px;
}

.result-section {
  margin-top: 8px;
}

.result-header {
  margin-bottom: var(--space-md);
  font-size: 14px;
  color: var(--brand-text-secondary);
}

.result-table-wrapper {
  box-shadow: var(--brand-shadow-sm);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: var(--space-md);
}

/* AI 推荐查询卡片 */
.suggested-questions {
  margin-bottom: var(--space-md);
}

.sq-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.sq-icon {
  color: var(--brand-accent);
  font-size: 18px;
}

.sq-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-text-primary);
}

.sq-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 10px;
}

.sq-card {
  display: flex;
  align-items: center;
  padding: 12px 16px;
  background: var(--brand-surface);
  border: 1px solid var(--brand-border);
  border-radius: var(--brand-radius-md);
  font-size: 14px;
  color: var(--brand-text-secondary);
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
  line-height: 1.4;
}

.sq-card:hover {
  border-color: var(--brand-primary-light-5);
  background: var(--brand-primary-light-9);
  color: var(--brand-primary);
  transform: translateY(-1px);
  box-shadow: var(--brand-shadow-sm);
}

.sq-card.active {
  border-color: var(--brand-primary);
  background: var(--brand-primary-light-9);
  color: var(--brand-primary);
  font-weight: 500;
}

/* AI 思考动画卡片 */
.thinking-card {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-xl) var(--space-lg);
  margin-top: var(--space-md);
}

.thinking-content {
  display: flex;
  align-items: center;
  gap: 14px;
}

/* 三个跳动圆点：错峰动画营造"思考"感 */
.thinking-dots {
  display: flex;
  gap: 6px;
}

.thinking-dots .dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--brand-primary);
  animation: thinking-bounce 1.4s infinite ease-in-out both;
}

.thinking-dots .dot:nth-child(1) {
  animation-delay: -0.32s;
}

.thinking-dots .dot:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes thinking-bounce {
  0%, 80%, 100% {
    transform: scale(0.6);
    opacity: 0.4;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.thinking-text {
  font-size: 14px;
  color: var(--brand-text-secondary);
  font-weight: 500;
  /* 文案切换时淡入效果 */
  animation: thinking-fade 0.4s ease;
}

@keyframes thinking-fade {
  from {
    opacity: 0.3;
  }
  to {
    opacity: 1;
  }
}

@media (prefers-reduced-motion: reduce) {
  .thinking-dots .dot {
    animation: none;
    opacity: 0.7;
  }
  .thinking-text {
    animation: none;
  }
}

.sql-block {
  background: #1e293b;
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: var(--space-md);
}

.sql-block-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 16px;
  background: rgba(0, 0, 0, 0.2);
  font-size: 12px;
  color: #94a3b8;
}

.sql-block-header :deep(.el-button) {
  color: #94a3b8;
}

.sql-block-header :deep(.el-button:hover) {
  color: #e2e8f0;
}

.sql-block pre {
  margin: 0;
  padding: 16px;
  color: #e2e8f0;
  font-family: var(--brand-font-mono);
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.export-row {
  display: flex;
  gap: 12px;
  padding-top: var(--space-md);
  border-top: 1px solid var(--brand-border);
}

.business-desc {
  white-space: pre-wrap;
  line-height: 1.6;
  color: var(--brand-text-primary);
}

.business-desc-empty {
  color: var(--brand-text-secondary);
  font-style: italic;
}
</style>
