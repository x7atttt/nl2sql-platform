<template>
  <div class="page-container">
    <div class="stat-cards">
      <el-row :gutter="20">
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-number">{{ datasetCount }}</div>
            <div class="stat-label">数据集总数</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-number">{{ queryCount }}</div>
            <div class="stat-label">查询记录数</div>
          </el-card>
        </el-col>
        <el-col :span="8">
          <el-card shadow="hover" class="stat-card">
            <div class="stat-number">{{ store.user?.role === 'admin' ? '管理员' : store.user?.role === 'analyst' ? '分析师' : '只读用户' }}</div>
            <div class="stat-label">当前角色</div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <div class="quick-section">
      <div class="section-header">
        <h3>最近数据集</h3>
        <el-button link type="primary" @click="$router.push('/datasets')">查看全部</el-button>
      </div>
      <el-table :data="recentDatasets" stripe size="small">
        <el-table-column prop="name" label="名称" min-width="150" />
        <el-table-column label="行数" width="80">
          <template #default="{ row }">{{ row.row_count || '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'completed' ? 'success' : 'info'" size="small">
              {{ row.status === 'completed' ? '已完成' : '处理中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="60">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { datasetApi } from '../api/dataset'
import { queryApi } from '../api/query'

const router = useRouter()
const store = useUserStore()
const datasetCount = ref(0)
const queryCount = ref(0)
const recentDatasets = ref<any[]>([])

onMounted(async () => {
  try {
    const [dsRes, qRes] = await Promise.all([
      datasetApi.getList(),
      queryApi.getHistory(),
    ])
    datasetCount.value = dsRes.data.count
    queryCount.value = qRes.data.count
    recentDatasets.value = dsRes.data.results.slice(0, 5)
  } catch { /* interceptor handles error */ }
})

function goDetail(id: string) {
  router.push({ name: 'dataset-detail', params: { id } })
}

function formatTime(t: string) {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}
</script>

<style scoped>
.stat-cards {
  margin-bottom: 24px;
}

.stat-card {
  text-align: center;
}

.stat-number {
  font-size: 32px;
  font-weight: 600;
  color: #409eff;
  margin-bottom: 8px;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.section-header h3 {
  font-size: 16px;
  color: #303133;
}
</style>
