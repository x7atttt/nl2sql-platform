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
          <!-- 查询交互已统一到 AI 对话页（流式回答/多轮/过程追溯），此处为入口 -->
          <div class="chat-entry-card page-section">
            <div class="sq-header">
              <el-icon class="sq-icon"><MagicStick /></el-icon>
              <span class="sq-title">在 AI 对话中查询这个数据集</span>
            </div>
            <p class="chat-entry-desc">
              支持流式回答、多轮追问、图表/数据/SQL/过程追溯——比单次查询更适合探索数据。
            </p>
            <el-button type="primary" size="large" round @click="goChat()">
              <el-icon style="margin-right: 6px"><ChatDotRound /></el-icon>
              开始 AI 对话
            </el-button>
          </div>

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
                @click="goChat(q)"
              >
                {{ q }}
              </button>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
    <div v-else v-loading="true" class="detail-tabs-loading"></div>

    <!-- 分享数据集弹窗（含当前分享记录 + 撤销）-->
    <el-dialog v-model="shareDialogVisible" title="分享数据集" width="560px">
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

      <!-- 当前分享记录（admin 任意 / analyst 仅自己 owner 的） -->
      <div class="share-records-section">
        <div class="share-records-header">
          <span>当前分享记录（{{ shareRecords.length }}）</span>
        </div>
        <el-table
          :data="shareRecords"
          size="small"
          v-loading="sharesLoading"
          empty-text="暂无分享记录"
        >
          <el-table-column label="被分享人" min-width="130">
            <template #default="{ row }">
              {{ row.shared_to.username }}（{{ roleLabel(row.shared_to.role) }}）
            </template>
          </el-table-column>
          <el-table-column label="分享人" width="100">
            <template #default="{ row }">{{ row.shared_by.username }}</template>
          </el-table-column>
          <el-table-column label="分享时间" width="155">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="64" fixed="right">
            <template #default="{ row }">
              <el-popconfirm
                title="确定撤销该用户的查询权限？"
                confirm-button-text="撤销"
                cancel-button-text="取消"
                @confirm="handleUnshare(row.id)"
              >
                <template #reference>
                  <el-button class="action-icon-btn" link type="danger" :icon="Delete" />
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </div>

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
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Share, EditPen, MagicStick, Delete, ChatDotRound } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { datasetApi } from '../api/dataset'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const loading = ref(false)
const dataset = ref<any>(null)
const analysis = ref<any>(null)
const activeTab = ref('analysis')


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

// 分享记录（对话框内展示 + 撤销操作）
interface ShareRecord {
  id: string
  shared_to: { id: number; username: string; role: string }
  shared_by: { id: number; username: string }
  permission: string
  created_at: string
}
const shareRecords = ref<ShareRecord[]>([])
const sharesLoading = ref(false)

async function loadDataset(id: string) {
  loading.value = true
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

/** 跳转 AI 对话页（预选本数据集；带问题则预填输入框） */
function goChat(question?: string) {
  router.push({
    path: '/chat',
    query: { dataset: route.params.id, ...(question ? { q: question } : {}) },
  })
}

watch(() => route.params.id, (id) => {
  if (id) loadDataset(id as string)
}, { immediate: true })


async function openShareDialog() {
  shareDialogVisible.value = true
  shareTargetId.value = null
  // 同时拉取可分享用户列表 + 当前分享记录
  shareUsersLoading.value = true
  sharesLoading.value = true
  try {
    const [usersRes, sharesRes] = await Promise.all([
      datasetApi.getShareableUsers(),
      dataset.value ? datasetApi.getShares(dataset.value.id) : Promise.resolve({ data: [] }),
    ])
    shareableUsers.value = usersRes.data
    shareRecords.value = sharesRes.data
  } catch {
    ElMessage.error('获取分享信息失败')
  } finally {
    shareUsersLoading.value = false
    sharesLoading.value = false
  }
}

async function refreshShares() {
  if (!dataset.value) return
  try {
    const res = await datasetApi.getShares(dataset.value.id)
    shareRecords.value = res.data
  } catch {
    /* 静默失败，不打断主流程 */
  }
}

async function handleShare() {
  if (!shareTargetId.value || !dataset.value) return
  sharing.value = true
  try {
    const res = await datasetApi.share(dataset.value.id, shareTargetId.value)
    ElMessage.success(res.data.message || '分享成功')
    shareTargetId.value = null  // 清空选择，便于继续分享给下一个
    refreshShares()  // 刷新分享记录，让新分享立即出现在表格里
  } catch (e: any) {
    const msg = e?.response?.data?.error || '分享失败'
    ElMessage.error(msg)
  } finally {
    sharing.value = false
  }
}

async function handleUnshare(shareId: string) {
  if (!dataset.value) return
  try {
    await datasetApi.unshare(dataset.value.id, shareId)
    ElMessage.success('已撤销分享')
    refreshShares()
  } catch (e: any) {
    const msg = e?.response?.data?.error || '撤销失败'
    ElMessage.error(msg)
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

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}
</script>

<style scoped>
/* 操作列图标按钮：方形热区（与 DatasetList/QueryHistory 一致） */
.action-icon-btn {
  width: 32px;
  height: 32px;
  padding: 0 !important;
  margin: 0 !important;
  border-radius: var(--brand-radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  transition: background 0.15s ease;
}

.action-icon-btn:hover {
  background: var(--brand-primary-light-9);
}

/* 分享记录区域（对话框内） */
.share-records-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--brand-border);
}

.share-records-header {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-text-secondary);
  margin-bottom: 8px;
}

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

/* AI 思考提示：紧贴输入框下方的轻量内联条（非独立卡片，避免被挤出可视区）*/
.thinking-inline {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  margin-top: -8px;       /* 向上贴近输入框，消除输入卡片与本条的间距 */
  margin-bottom: var(--space-md);
  background: var(--brand-primary-light-9);
  border-radius: 0 0 var(--brand-radius-md) var(--brand-radius-md);
}

/* 三个跳动圆点：错峰动画营造"思考"感 */
.thinking-dots {
  display: flex;
  gap: 5px;
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
.chat-entry-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 36px 24px;
  text-align: center;
}

.chat-entry-desc {
  margin: 0;
  color: var(--el-text-color-secondary);
  font-size: 13.5px;
  max-width: 420px;
}
</style>
