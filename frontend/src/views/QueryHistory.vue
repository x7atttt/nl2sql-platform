<template>
  <div class="page-container">
    <div class="page-header">
      <h2>查询历史</h2>
      <el-select v-model="filterDatasetId" placeholder="按数据集筛选" clearable @change="fetchHistory">
        <el-option
          v-for="ds in datasetOptions"
          :key="ds.id"
          :label="ds.name"
          :value="ds.id"
        />
      </el-select>
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

                <!-- 重跑完整结果（覆盖展示） -->
                <div v-if="rerunResult[row.id]" class="rerun-result">
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

        <el-table-column prop="dataset_name" label="数据集" min-width="120" />
        <el-table-column prop="question" label="问题" min-width="200" show-overflow-tooltip />
        <el-table-column label="SQL" min-width="250">
          <template #default="{ row }">
            <el-tooltip :content="row.generated_sql" placement="top">
              <span class="sql-preview">{{ row.generated_sql }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_success ? 'success' : 'danger'" size="small">
              {{ row.is_success ? '成功' : '失败' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="行数" width="80">
          <template #default="{ row }">
            {{ row.is_success ? row.result_count : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.execution_time_ms ? row.execution_time_ms + 'ms' : '-' }}</template>
        </el-table-column>
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.dataset)">查看</el-button>
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
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { queryApi } from '../api/query'
import { datasetApi } from '../api/dataset'

const router = useRouter()
const loading = ref(false)
const records = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const filterDatasetId = ref('')
const datasetOptions = ref<any[]>([])

// 重跑状态：rerunningId 标记哪条正在重跑，rerunResult 存重跑结果
const rerunningId = ref<string | null>(null)
const rerunResult = reactive<Record<string, any>>({})

onMounted(async () => {
  fetchHistory()
  const res = await datasetApi.getList()
  datasetOptions.value = res.data.results
})

async function fetchHistory() {
  loading.value = true
  try {
    const params: any = { page: page.value }
    if (filterDatasetId.value) params.dataset_id = filterDatasetId.value
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
.sql-preview {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--brand-font-mono);
  font-size: 12px;
  color: var(--brand-text-secondary);
  background: var(--brand-code-bg);
  padding: 2px 8px;
  border-radius: 4px;
}

.expand-content {
  padding: 16px 24px;
  background: var(--el-fill-color-light);
}

.expand-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
