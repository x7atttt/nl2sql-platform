<template>
  <div class="page-container">
    <div class="page-header">
      <h2>数据源查询</h2>
    </div>

    <div class="page-section">
      <div v-if="loadingMeta" v-loading="true" class="meta-loading"></div>

      <el-alert v-else-if="metaError" :title="metaError" type="error" show-icon :closable="false" />

      <template v-else>
        <!-- 表结构浏览（折叠面板） -->
        <div class="tables-bar">
          <span class="tables-label">
            共 {{ tablesData.count }} 张表
            <el-tag v-if="tablesData.over_limit" size="small" type="warning" class="over-tag">
              超过 {{ tablesData.max_tables }} 张，查询前需先选择表
            </el-tag>
          </span>
          <el-button text size="small" :icon="Back" @click="goBack">返回列表</el-button>
        </div>

        <el-collapse class="tables-collapse" v-if="tablesData.tables.length > 0">
          <el-collapse-item v-for="t in tablesData.tables.slice(0, 50)" :key="t.name"
                            :name="t.name">
            <template #title>
              <span class="table-title">{{ t.name }}</span>
              <span v-if="t.row_estimate != null && t.row_estimate >= 0" class="table-meta">
                约 {{ Number(t.row_estimate).toLocaleString() }} 行
              </span>
              <span v-if="t.comment" class="table-comment">{{ t.comment }}</span>
            </template>
            <div class="table-columns">
              <div v-for="c in t.columns" :key="c.name" class="col-line">
                <code class="col-name">{{ c.name }}</code>
                <span class="col-type">{{ c.type }}</span>
                <span v-if="c.comment" class="col-comment">{{ c.comment }}</span>
                <span v-if="t.text_tops && t.text_tops[c.name]" class="col-tops">
                  top: {{ t.text_tops[c.name].join(', ') }}
                </span>
              </div>
            </div>
          </el-collapse-item>
        </el-collapse>

        <!-- 表数超上限时：选表 -->
        <div v-if="tablesData.over_limit" class="table-select">
          <div class="table-select-label">
            选择本次查询涉及的表（已选 {{ selectedTables.length }}/{{ tablesData.max_tables }}）：
          </div>
          <el-select v-model="selectedTables" multiple filterable
                     placeholder="选择要查询的表" style="width: 100%">
            <el-option v-for="t in tablesData.tables" :key="t.name"
                       :label="t.comment ? `${t.name}（${t.comment}）` : t.name"
                       :value="t.name" />
          </el-select>
        </div>

        <!-- 查询输入 -->
        <div class="query-row">
          <el-input
            v-model="question"
            placeholder="用自然语言提问，跨表问题自动 JOIN，如：各客户的城市和订单总额"
            clearable
            :disabled="queryLoading"
            @keyup.enter="submitQuery"
          />
          <el-button
            type="primary"
            :loading="queryLoading"
            :disabled="!question.trim() || (tablesData.over_limit && selectedTables.length === 0)"
            @click="submitQuery"
          >
            查询
          </el-button>
        </div>

        <!-- AI 思考动画 -->
        <div v-if="queryLoading" class="thinking-inline">
          <div class="thinking-dots">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
          </div>
          <span class="thinking-text">{{ thinkingText }}</span>
        </div>

        <!-- 查询结果：表格 + SQL + 图表（与其他查询页共用展示结构） -->
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
              <div class="sql-block-header"><span>SQL</span></div>
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
            :description="queryResult.sql ? `SQL: ${queryResult.sql}` : undefined"
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
import { datasourceApi } from '../api/datasource'
import ResultChart from '../components/ResultChart.vue'

const route = useRoute()
const router = useRouter()
const sourceId = route.params.id as string

const loadingMeta = ref(true)
const metaError = ref('')
const tablesData = ref<any>({ count: 0, over_limit: false, max_tables: 20, tables: [], fk_hints: [] })
const selectedTables = ref<string[]>([])

const question = ref('')
const queryLoading = ref(false)
const queryResult = ref<any>(null)
const currentQueryId = ref<string | null>(null)

const resultColumns = computed(() => {
  const data = queryResult.value?.data
  return data && data.length > 0 ? Object.keys(data[0]) : []
})

const thinkingTexts = [
  '正在分析表结构', '正在推断关联关系', '正在生成 SQL',
  '正在校验安全性', '正在执行查询', '正在整理结果',
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
  if (thinkingTimer) { clearInterval(thinkingTimer); thinkingTimer = null }
}
onUnmounted(stopThinking)

onMounted(async () => {
  try {
    const res = await datasourceApi.getTables(sourceId)
    tablesData.value = res.data
  } catch (e: any) {
    metaError.value = e?.response?.data?.error || e?.message || '获取表结构失败'
  } finally {
    loadingMeta.value = false
  }
})

async function submitQuery() {
  if (!question.value.trim() || queryLoading.value) return
  if (tablesData.value.over_limit && selectedTables.value.length === 0) {
    ElMessage.warning('该库表较多，请先选择要查询的表')
    return
  }
  queryLoading.value = true
  queryResult.value = null
  currentQueryId.value = null
  startThinking()
  try {
    const res = await datasourceApi.query(
      sourceId, question.value.trim(),
      tablesData.value.over_limit ? selectedTables.value : undefined,
    )
    queryResult.value = res.data
    currentQueryId.value = res.data.query_id || null
    if (!res.data.success) ElMessage.warning(res.data.error || '查询失败')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || e?.message || '请求失败')
  } finally {
    queryLoading.value = false
    stopThinking()
  }
}

function goBack() {
  router.push('/datasources')
}
</script>

<style scoped>
.meta-loading { height: 120px; }
.tables-bar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px;
}
.tables-label { color: var(--el-text-color-secondary); font-size: 14px; }
.over-tag { margin-left: 8px; }
.tables-collapse { margin-bottom: 16px; }
.table-title { font-weight: 600; margin-right: 8px; }
.table-meta { color: var(--el-text-color-secondary); font-size: 12px; margin-right: 8px; }
.table-comment { color: var(--el-text-color-secondary); font-size: 12px; }
.table-columns { max-height: 240px; overflow-y: auto; }
.col-line { padding: 2px 0; font-size: 13px; }
.col-name { background: var(--el-fill-color-light); padding: 0 6px; border-radius: 3px; }
.col-type { color: var(--el-color-primary); margin: 0 8px; font-size: 12px; }
.col-comment { color: var(--el-text-color-secondary); margin-right: 8px; font-size: 12px; }
.col-tops { color: var(--el-text-color-secondary); font-size: 12px; }
.table-select { margin-bottom: 16px; }
.table-select-label { font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 6px; }
.query-row { display: flex; gap: 12px; }
.result-section { margin-top: 20px; }
.result-header { margin-bottom: 12px; color: var(--el-text-color-regular); }
.result-table-wrapper { margin-bottom: 16px; }
.sql-block {
  background: var(--el-fill-color-light); border-radius: 6px;
  padding: 12px; margin-bottom: 16px;
}
.sql-block-header {
  display: flex; justify-content: space-between;
  font-size: 13px; color: var(--el-text-color-secondary); margin-bottom: 6px;
}
.sql-block pre {
  margin: 0; font-size: 12px; white-space: pre-wrap; word-break: break-all;
  max-height: 200px; overflow-y: auto;
}
.thinking-inline {
  display: flex; align-items: center; gap: 10px; margin-top: 14px;
  padding: 8px 12px; border-radius: 6px;
  background: var(--el-color-primary-light-9);
}
.thinking-dots { display: flex; gap: 4px; }
.thinking-dots .dot {
  width: 6px; height: 6px; border-radius: 50%;
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
