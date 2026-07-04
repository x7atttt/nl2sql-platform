<template>
  <div class="result-chart page-section">
    <!-- 不适合可视化时 -->
    <el-empty v-if="currentSuggestion.chartType === null" :description="currentSuggestion.reason">
      <template #image>
        <el-icon :size="48" color="var(--el-text-color-secondary)"><PieChart /></el-icon>
      </template>
    </el-empty>

    <!-- 可视化区 -->
    <div v-else>
      <!-- 工具栏：图表类型切换 + 轴选择 + AI 优化状态 -->
      <div class="chart-toolbar">
        <el-radio-group v-model="currentType" size="small" @change="onUserOverride">
          <el-radio-button value="bar">柱状</el-radio-button>
          <el-radio-button value="line">折线</el-radio-button>
          <el-radio-button value="area">面积</el-radio-button>
          <el-radio-button value="pie">饼图</el-radio-button>
          <el-radio-button value="scatter">散点</el-radio-button>
        </el-radio-group>
        <div class="axis-selectors">
          <el-select v-model="currentXField" placeholder="X 轴" size="small" style="width: 140px" @change="onUserOverride">
            <el-option v-for="c in dimensionOptions" :key="c" :label="c" :value="c" />
          </el-select>
          <el-select
            v-model="currentYFields"
            placeholder="Y 轴"
            size="small"
            multiple
            collapse-tags
            collapse-tags-tooltip
            style="width: 200px"
            @change="onUserOverride"
          >
            <el-option v-for="c in measureOptions" :key="c" :label="c" :value="c" />
          </el-select>
          <!-- AI 优化状态指示 -->
          <span v-if="aiState === 'loading'" class="ai-status loading">
            <el-icon class="is-loading"><Loading /></el-icon> AI 优化中
          </span>
          <span v-else-if="aiState === 'done'" class="ai-status done" title="LLM 智能推荐已应用">
            ✨ AI 优化
          </span>
        </div>
      </div>

      <!-- ECharts 渲染 -->
      <v-chart
        class="chart-canvas"
        :option="chartOption"
        autoresize
      />

      <!-- 推荐理由 -->
      <div class="chart-reason">
        💡 {{ currentSuggestion.reason }}
        <span v-if="aiState === 'failed'" class="ai-failed">（AI 优化不可用，使用默认推荐）</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { PieChart, Loading } from '@element-plus/icons-vue'
// 按需引入 ECharts（减小打包体积，比全量 import 省 ~600KB）
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart as EPieChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  TitleComponent,
  DataZoomComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import {
  suggestChart,
  type ColumnType,
  type ChartType,
} from '../utils/chartSelector'
import { queryApi } from '../api/query'

use([
  CanvasRenderer,
  BarChart, LineChart, EPieChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent,
])

const props = defineProps<{
  data: Record<string, unknown>[]
  columns: string[]
  columnTypes: Record<string, ColumnType>
  /** 查询历史 ID，用于异步调 LLM 图表推荐 */
  queryId?: string
}>()

// 初次进入时按规则引擎推荐默认配置（0 等待，用户立即看到图）
const initial = suggestChart(props.columns, props.columnTypes, props.data)
const currentType = ref<Exclude<ChartType, null>>(initial.chartType ?? 'bar')
const currentXField = ref(initial.xField)
const currentYFields = ref<string[]>(initial.yFields)

// AI 优化状态：idle（未触发）/ loading（请求中）/ done（已应用）/ failed（降级）
const aiState = ref<'idle' | 'loading' | 'done' | 'failed'>('idle')
// 用户是否手动改过图表配置（改过则不被 LLM 建议覆盖）
let userOverridden = false

// 数据/列变化时重新用规则引擎推荐（如换了查询结果）
// 注意：不在这里重置 aiState/userOverridden，交由 queryId watch 统一管理
// （两个 watch 同 tick 触发，顺序不确定，这里重置会吞掉 queryId 的 loading/failed 状态）
watch(
  () => [props.columns, props.columnTypes, props.data],
  () => {
    const sug = suggestChart(props.columns, props.columnTypes, props.data)
    currentType.value = sug.chartType ?? 'bar'
    currentXField.value = sug.xField
    currentYFields.value = sug.yFields
    _lastSuggestion.value = sug
  },
  { deep: true },
)

// queryId 变化 = 新查询：重置 AI 状态 + 异步调 LLM 图表推荐
watch(
  () => props.queryId,
  async (newId) => {
    if (!newId) return
    // 新查询：重置用户覆盖标记 + 进入 loading
    userOverridden = false
    aiState.value = 'loading'
    try {
      const res = await queryApi.suggestChart(newId)
      if (res.data.success && res.data.suggestion && !userOverridden) {
        const sug = res.data.suggestion
        // LLM 判断不适合可视化（chartType=null）：保留规则引擎图，只标记 AI 已评估
        if (sug.chartType === null) {
          aiState.value = 'done'
          return
        }
        // 应用 LLM 建议切换图表
        currentType.value = (sug.chartType ?? 'bar') as Exclude<ChartType, null>
        currentXField.value = sug.xField
        currentYFields.value = sug.yFields
        _lastSuggestion.value = sug
        aiState.value = 'done'
      } else {
        aiState.value = 'failed'
      }
    } catch {
      // 网络错误/超时/服务端 500：静默降级，保持规则引擎图
      aiState.value = 'failed'
    }
  },
  { immediate: true },
)

/** 用户手动改图表配置时标记，防止后续 LLM 建议覆盖用户选择 */
function onUserOverride() {
  userOverridden = true
}

// 内部缓存 suggestion（reason 展示用，currentType 切换后保留原 reason）
const _lastSuggestion = ref(initial)
const currentSuggestion = computed(() => {
  // 若用户手动切换了类型，reason 仍展示原始推荐理由
  return {
    ..._lastSuggestion.value,
    chartType: currentType.value as ChartType,
  }
})

// 维度列候选（text/date/boolean 都可作 X 轴）
const dimensionOptions = computed(() =>
  props.columns.filter((c) => {
    const t = props.columnTypes[c]
    return t === 'text' || t === 'date' || t === 'boolean'
  }),
)
const measureOptions = computed(() =>
  props.columns.filter((c) => props.columnTypes[c] === 'number'),
)

// 数据行数过多时截断（散点/柱状超 100 项体验差）
const MAX_POINTS = 100
const displayData = computed(() => {
  if (props.data.length > MAX_POINTS) {
    return props.data.slice(0, MAX_POINTS)
  }
  return props.data
})

/** 格式化维度值：null/undefined/空字符串 → 可读标签，避免图表显示无名扇区/空白轴 */
function formatDimValue(val: unknown): string {
  if (val === null || val === undefined || val === '') return '（空值）'
  return String(val)
}

// ECharts option 派生
const chartOption = computed(() => {
  const type = currentType.value
  const x = currentXField.value
  const ys = currentYFields.value

  if (!ys.length) return {}

  if (type === 'pie') {
    return buildPieOption(x, ys[0])
  }
  if (type === 'scatter') {
    return buildScatterOption(x, ys[0])
  }
  // bar / line / area（共用 cartesian 坐标系）
  return buildCartesianOption(type, x, ys)
})

function buildCartesianOption(type: 'bar' | 'line' | 'area', x: string, ys: string[]) {
  const data = displayData.value
  const xData = x ? data.map((r) => formatDimValue(r[x])) : data.map((_, i) => `#${i + 1}`)
  const series = ys.map((y) => ({
    name: y,
    type: type === 'area' ? 'line' : type,
    data: data.map((r) => Number(r[y]) || 0),
    ...(type === 'area' ? { areaStyle: {} } : {}),
    smooth: type === 'line' || type === 'area',
  }))
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ys, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      axisLabel: { rotate: xData.length > 8 ? 30 : 0 },
    },
    yAxis: { type: 'value' },
    // 数据多时开启横向缩放
    dataZoom: data.length > 20 ? [{ type: 'inside' }, { type: 'slider', height: 16 }] : [],
    series,
  }
}

function buildPieOption(x: string, y: string) {
  const data = displayData.value
  return {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { type: 'scroll', orient: 'vertical', right: 10, top: 'middle' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['40%', '50%'],
        data: data.map((r) => ({ name: x ? formatDimValue(r[x]) : '', value: Number(r[y]) || 0 })),
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } },
      },
    ],
  }
}

function buildScatterOption(x: string, y: string) {
  const data = displayData.value
  // 散点图：x 必须是数值（如果用户选了文本列作 x，自动用索引）
  const pts = data.map((r) => [x ? Number(r[x]) || 0 : 0, Number(r[y]) || 0])
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => `${formatDimValue(data[p.dataIndex]?.[x])}: ${p.value[1]}`,
    },
    xAxis: { type: 'value', name: x || 'X' },
    yAxis: { type: 'value', name: y },
    series: [{ type: 'scatter', data: pts, symbolSize: 8 }],
  }
}
</script>

<style scoped>
.result-chart {
  padding: var(--space-lg);
  margin-top: var(--space-md);
}

.chart-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
}

.axis-selectors {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* AI 优化状态指示 */
.ai-status {
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
  padding: 0 8px;
}
.ai-status.loading {
  color: var(--el-color-primary);
}
.ai-status.done {
  color: var(--el-color-success);
  background: var(--el-color-success-light-9);
  border-radius: 10px;
  padding: 2px 10px;
}
.ai-failed {
  color: var(--el-text-color-secondary);
  font-size: 11px;
}

.chart-canvas {
  width: 100%;
  height: 380px;
}

.chart-reason {
  margin-top: 12px;
  font-size: 12px;
  color: var(--brand-text-secondary);
  line-height: 1.5;
}
</style>
