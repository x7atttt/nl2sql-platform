<template>
  <div class="page-container">
    <div class="page-header">
      <h2>{{ headerTitle }}</h2>
      <el-button :icon="Refresh" @click="fetchShares" :loading="loading">刷新</el-button>
    </div>

    <div class="page-section">
      <el-table :data="records" v-loading="loading" stripe empty-text="暂无分享记录">
        <el-table-column label="数据集" min-width="140">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDataset(row.dataset.id)">
              {{ row.dataset.name }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="分享人" width="100">
          <template #default="{ row }">{{ row.shared_by.username }}</template>
        </el-table-column>
        <!-- 箭头列：viewer 不显示（被分享人就是自己，无需流向指示） -->
        <el-table-column v-if="!isViewer" label="" width="56" align="center" class-name="arrow-col">
          <template #default>
            <el-icon class="arrow-icon"><Right /></el-icon>
          </template>
        </el-table-column>
        <el-table-column v-if="!isViewer" label="被分享人" min-width="120">
          <template #default="{ row }">
            {{ row.shared_to.username }}
            <el-tag size="small" :type="roleTagType(row.shared_to.role)" class="role-tag">
              {{ roleLabel(row.shared_to.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="分享时间" min-width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <!-- 撤销列：仅 admin/analyst 可见（viewer 无权撤销） -->
        <el-table-column v-if="canRevoke" label="操作" width="70" fixed="right">
          <template #default="{ row }">
            <el-popconfirm
              title="确定撤销该用户的查询权限？"
              confirm-button-text="撤销"
              cancel-button-text="取消"
              @confirm="handleUnshare(row)"
            >
              <template #reference>
                <el-button class="action-icon-btn" link type="danger" :icon="Delete" />
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datasetApi } from '../api/dataset'
import { useUserStore } from '../stores/user'

const router = useRouter()
const store = useUserStore()
const role = computed(() => store.user?.role)
const isAdmin = computed(() => role.value === 'admin')
const isAnalyst = computed(() => role.value === 'analyst')
const isViewer = computed(() => role.value === 'viewer')
const canRevoke = computed(() => isAdmin.value || isAnalyst.value)

const headerTitle = computed(() => {
  if (isAdmin.value) return '全平台分享记录'
  if (isAnalyst.value) return '我的分享记录'
  return '分享给我的数据集'
})

interface ShareRecord {
  id: string
  dataset: { id: string; name: string }
  shared_to: { id: number; username: string; role: string }
  shared_by: { id: number; username: string }
  permission: string
  created_at: string
}

const records = ref<ShareRecord[]>([])
const loading = ref(false)

async function fetchShares() {
  loading.value = true
  try {
    const res = await datasetApi.getSharesList()
    records.value = res.data
  } catch {
    ElMessage.error('获取分享记录失败')
  } finally {
    loading.value = false
  }
}

async function handleUnshare(row: ShareRecord) {
  try {
    await datasetApi.unshare(row.dataset.id, row.id)
    ElMessage.success('已撤销分享')
    fetchShares()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '撤销失败')
  }
}

function goDataset(id: string) {
  router.push({ name: 'dataset-detail', params: { id } })
}

function roleLabel(r: string) {
  const map: Record<string, string> = { admin: '管理员', analyst: '分析师', viewer: '只读用户' }
  return map[r] || r
}

function roleTagType(r: string): 'danger' | 'warning' | 'info' {
  const map: Record<string, 'danger' | 'warning' | 'info'> = { admin: 'danger', analyst: 'warning', viewer: 'info' }
  return map[r] || 'info'
}

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}

onMounted(fetchShares)
</script>

<style scoped>
/* 分享流向箭头列 */
.arrow-icon {
  font-size: 32px;
  background: linear-gradient(90deg, var(--brand-primary), var(--brand-accent));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

:deep(.arrow-col .cell) {
  padding: 0;
}

.role-tag {
  margin-left: 6px;
}

/* 操作列图标按钮：方形热区 */
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
</style>
