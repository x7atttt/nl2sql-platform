<template>
  <div class="page-container">
    <div class="page-header">
      <h2>多数据集联合查询</h2>
    </div>

    <!-- 已选数据集（chips 展示，从列表页勾选带入） -->
    <div class="page-section">
      <div class="datasets-bar">
        <span class="datasets-label">参与数据集：</span>
        <el-tag
          v-for="ds in datasets"
          :key="ds.id"
          class="dataset-tag"
          type="info"
          effect="plain"
        >
          {{ ds.name }}
          <span class="tag-meta">{{ ds.row_count || '-' }} 行</span>
        </el-tag>
        <el-button text size="small" :icon="Back" @click="goBack">重新选择</el-button>
      </div>
      <div v-if="loadingDatasets" v-loading="true" class="datasets-loading"></div>

      <el-alert
        v-else-if="loadError"
        :title="loadError"
        type="error"
        show-icon
        :closable="false"
      />

      <template v-else>
        <!-- 查询输入 -->
        <div class="query-row">
          <el-input
            v-model="question"
            placeholder="用自然语言提问，跨数据集的问题将自动关联，如：各区域销售额和库存对比"
            clearable
            :disabled="queryLoading"
            @keyup.enter="submitQuery"
          />
          <el-button
            type="primary"
            :loading="queryLoading"
            :disabled="!question.trim()"
            @click="submitQuery"
          >
            查询
          </el-button>
        </div>
        <div class="hint-text">
          系统会自动分析各数据集的列值分布，推断关联列并生成 JOIN 查询
        </div>

        <!-- AI 思考动画 -->
        <div v-if="queryLoading" class="thinking-inline">
          <div class="thinking-dots">
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
          </div>
          <span class="thinking-text">{{ thinkingText }}</span>
        </div>

        <!-- 查询结果：表格 + SQL + 图表（复用单表查询的展示结构） -->
        <div v-if="queryResult && !queryLoading" class="result-section">
          <div v-if="queryResult.success" class="result-success">
            <div class="result-header">
              <span>
                查询到 <strong>{{ queryResult.row_count }}</strong> 条数据，
                耗时 {{ queryResult.execution_time_ms }}ms
                <el-tag v-if="queryResult.retry_count > 0" size="small" type="warning">
                  自动修复 {{ queryResult.retry_count }} 次
                </el-tag>
              </span>
            </div>

            <div class="result-table-wrapper">
              <el-table :data="queryResult.data" stripe border size="small" max-height="400">
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
              </div>
              <pre>{{ queryResult.sql }}</pre>
            </div>

            <ResultChart
              v-if="queryResult.data && queryResult.data.length > 0"
              :data="queryResult.data"
              :columns="resultColumns"
              :column-types="queryResult.column_types || {}"
              :query-id="currentQueryId || undefined"
            />
          </div>

          <el-alert
            v-else
            :title="queryResult.error || '查询失败'"
            type="error"
            show-icon
            :description="`SQL: ${queryResult.sql}`"
          />
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { datasetApi } from '../api/dataset'
import { queryApi } from '../api/query'
import ResultChart from '../components/ResultChart.vue'

const route = useRoute()
const router = useRouter()

// 从 URL 解析选中的数据集 ID（列表页跳转带入 ?ids=a,b,c）
const ids = computed(() => {
  const raw = route.query.ids as string | undefined
  if (!raw) return []
  return raw.split(',').filter(Boolean).slice(0, 3)
})

const datasets = ref<any[]>([])
const loadingDatasets = ref(false)
const loadError = ref('')

const question = ref('')
const queryLoading = ref(false)
const queryResult = ref<any>(null)
const currentQueryId = ref<string | null>(null)

const resultColumns = computed(() => {
  const data = queryResult.value?.data
  return data && data.length > 0 ? Object.keys(data[0]) : []
})

// AI 思考动画（与 DatasetDetail 一致的文案轮播）
const thinkingTexts = [
  '正在分析各数据集结构',
  '正在推断关联列',
  '正在生成联合 SQL',
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
  }, 1800)
}

function stopThinking() {
  if (thinkingTimer) {
    clearInterval(thinkingTimer)
    thinkingTimer = null
  }
}
onUnmounted(stopThinking)

onMounted(async () => {
  if (ids.value.length < 2) {
    loadError.value = '请先在数据集列表勾选 2-3 个数据集'
    return
  }
  loadingDatasets.value = true
  try {
    // 并行拉取各数据集详情（名称/行数展示用；无权访问的会被后端 404）
    const results = await Promise.all(
      ids.value.map(id => datasetApi.getDetail(id).then(r => r.data).catch(() => null)),
    )
    const ok = results.filter(Boolean)
    if (ok.length !== ids.value.length) {
      loadError.value = '部分数据集不存在或无权访问，请返回重新选择'
      return
    }
    datasets.value = ok
  } finally {
    loadingDatasets.value = false
  }
})

async function submitQuery() {
  if (!question.value.trim() || queryLoading.value) return
  queryLoading.value = true
  queryResult.value = null
  currentQueryId.value = null
  startThinking()
  try {
    const res = await queryApi.multiQuery(
      datasets.value.map(d => d.id),
      question.value.trim(),
    )
    queryResult.value = res.data
    currentQueryId.value = res.data.query_id || null
    if (!res.data.success) {
      ElMessage.warning(res.data.error || '查询失败')
    }
  } catch (e: any) {
    const detail = e?.response?.data?.error || e?.message || '请求失败'
    ElMessage.error(detail)
  } finally {
    queryLoading.value = false
    stopThinking()
  }
}

function goBack() {
  router.push('/datasets')
}
</script>

<style scoped>
.datasets-bar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.datasets-label {
  color: var(--el-text-color-secondary);
  font-size: 14px;
}
.dataset-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.tag-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.datasets-loading {
  height: 60px;
}
.query-row {
  display: flex;
  gap: 12px;
}
.hint-text {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.result-section {
  margin-top: 20px;
}
.result-header {
  margin-bottom: 12px;
  color: var(--el-text-color-regular);
}
.result-table-wrapper {
  margin-bottom: 16px;
}
.sql-block {
  background: var(--el-fill-color-light);
  border-radius: 6px;
  padding: 12px;
  margin-bottom: 16px;
}
.sql-block-header {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}
.sql-block pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

/* 思考动画（与 DatasetDetail 一致） */
.thinking-inline {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--el-color-primary-light-9);
}
.thinking-dots {
  display: flex;
  gap: 4px;
}
.thinking-dots .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-primary);
  animation: thinking-bounce 1.4s infinite ease-in-out both;
}
.thinking-dots .dot:nth-child(1) { animation-delay: 0s; }
.thinking-dots .dot:nth-child(2) { animation-delay: 0.16s; }
.thinking-dots .dot:nth-child(3) { animation-delay: 0.32s; }
@keyframes thinking-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}
</style>
