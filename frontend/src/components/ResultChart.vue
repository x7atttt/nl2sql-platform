<template>
  <div class="result-chart page-section">
    <!-- 折叠头：可视化开关 + AI 优化状态（关闭时不渲染图表，省首屏空间） -->
    <div class="chart-toggle-bar">
      <div class="chart-toggle-left">
        <el-icon class="chart-toggle-icon"><TrendCharts /></el-icon>
        <span class="chart-toggle-label">可视化</span>
        <el-switch v-model="showChart" size="small" />
        <!-- 不适合可视化的提示（开关关闭时显示，告知用户原因） -->
        <span v-if="!showChart && initial.chartType === null" class="chart-skip-hint">
          {{ initial.reason }}
        </span>
      </div>
      <!-- AI 优化状态（仅展开时显示） -->
      <div v-if="showChart" class="chart-toggle-right">
        <span v-if="aiState === 'loading'" class="ai-status loading">
          <el-icon class="is-loading"><Loading /></el-icon> AI 正在为你推荐合适的图表
        </span>
        <span v-else-if="aiState === 'done'" class="ai-status done" title="LLM 智能推荐已应用">
          ✨ AI已完成图表智能推荐
        </span>
      </div>
    </div>

    <!-- 可视化区（开关打开时才渲染，懒加载省资源） -->
    <div v-if="showChart">
      <!-- 工具栏：图表类型切换 + 轴选择 -->
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
import { Loading, TrendCharts } from '@element-plus/icons-vue'
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
  /** 对话场景：LLM 已选定的图表类型（帧 chart_type），优先于规则引擎默认推荐 */
  presetType?: Exclude<ChartType, null>
}>()

// 初次进入时按规则引擎推荐默认配置（0 等待，用户立即看到图）
const initial = suggestChart(props.columns, props.columnTypes, props.data)
const currentType = ref<Exclude<ChartType, null>>(props.presetType ?? initial.chartType ?? 'bar')
const currentXField = ref(initial.xField)
const currentYFields = ref<string[]>(initial.yFields)

// 可视化开关：智能默认——规则引擎判断"适合可视化"(chartType≠null)时自动展开，
// 否则默认收起（单数字/明细数据不需要图表，避免占位突兀）。用户可手动开/关
const showChart = ref((props.presetType ?? initial.chartType) !== null)

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
    // 新查询：按规则引擎结果重置展开状态（适合则展开，不适合则收起）
    showChart.value = sug.chartType !== null
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
        // LLM 判断不适合可视化（chartType=null）：收起开关 + 标记 AI 已评估
        if (sug.chartType === null) {
          showChart.value = false
          _lastSuggestion.value = sug
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
    // 柱状图：柱子之间留间隙，避免连成一片；barWidth 自适应
    ...(type === 'bar' ? { barGap: '20%', barCategoryGap: '40%' } : {}),
  }))
  // 标签过长时截断，避免撑爆 X 轴（商品名/URL 等可达数十字符）
  const truncateLabel = (val: string) => {
    const s = String(val ?? '')
    return s.length > 10 ? s.slice(0, 10) + '…' : s
  }
  return {
    tooltip: {
      trigger: 'axis',
      // tooltip 显示完整标签（不被截断）
      formatter: (params: any) => {
        const items = Array.isArray(params) ? params : [params]
        const title = xData[items[0]?.dataIndex] ?? ''
        return [title, ...items.map((p: any) => `${p.marker} ${p.seriesName}: ${p.value}`)].join('<br/>')
      },
    },
    legend: { data: ys, top: 0 },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: {
      type: 'category',
      data: xData,
      // 柱状图：柱子在刻度中间（boundaryGap 默认 true）；折线图：点落在刻度上
      boundaryGap: type === 'bar',
      axisLabel: {
        interval: 0,                          // 强制显示所有标签，不抽稀（修复"标签和柱子对不齐"）
        rotate: xData.length > 6 || (xData.some((d) => String(d).length > 6)) ? 35 : 0,
        formatter: truncateLabel,             // 截断长标签，避免重叠
        hideOverlap: false,                   // 关闭自动隐藏（ECharts 5 默认会隐藏重叠标签）
      },
    },
    yAxis: { type: 'value' },
    // 数据多时开启横向缩放
    dataZoom: data.length > 20 ? [{ type: 'inside' }, { type: 'slider', height: 16 }] : [],
    series,
  }
}

function buildPieOption(x: string, y: string) {
  const data = displayData.value
  // 标签截断：商品名/URL 等长标签会撑爆图例，统一截断到 12 字符
  const truncateName = (val: unknown) => {
    const s = String(val ?? '')
    return s.length > 12 ? s.slice(0, 12) + '…' : s
  }
  const fullNames = data.map((r) => (x ? formatDimValue(r[x]) : ''))
  const pieData = data.map((r, i) => ({
    name: truncateName(fullNames[i]),
    value: Number(r[y]) || 0,
  }))
  return {
    tooltip: {
      trigger: 'item',
      // tooltip 显示完整名称（不被截断）+ 数值 + 百分比
      formatter: (p: any) => `${fullNames[p.dataIndex] ?? p.name}: ${p.value} (${p.percent}%)`,
    },
    legend: {
      type: 'scroll',
      orient: 'vertical',
      right: 10,
      top: 'middle',
      formatter: truncateName,
    },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['35%', '50%'],   // 收窄饼图，给右侧图例留更多空间
        data: pieData,
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } },
        // 标签线引导 + 截断标签，避免重叠
        label: { formatter: '{b}', fontSize: 11 },
      },
    ],
  }
}

function buildScatterOption(x: string, y: string) {
  const data = displayData.value
  // 散点图要求 X 是数值。若用户选了文本列，所有点会堆在 x=0，
  // 这里检测并回退为"用索引做 X"，至少能看到 y 值分布（比堆成竖线可读）。
  let pts: number[][]
  let xIsNumeric = true
  if (x) {
    const numericVals = data.map((r) => Number(r[x]))
    const validCount = numericVals.filter((v) => !isNaN(v) && isFinite(v)).length
    // 有效数值占比 < 50% 视为文本列
    xIsNumeric = validCount > data.length / 2
  }
  if (x && xIsNumeric) {
    pts = data.map((r) => [Number(r[x]) || 0, Number(r[y]) || 0])
  } else {
    // X 是文本列或未选：用行索引做 X 轴，避免所有点堆在 x=0
    pts = data.map((r, i) => [i + 1, Number(r[y]) || 0])
  }
  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        const label = x && xIsNumeric ? `${x}=${p.value[0]}` : `#${p.value[0]}`
        return `${formatDimValue(data[p.dataIndex]?.[x]) ?? label}<br/>${x}: ${p.value[0]}<br/>${y}: ${p.value[1]}`
      },
    },
    xAxis: {
      type: xIsNumeric ? 'value' : 'category',
      name: xIsNumeric ? (x || 'X') : '行号',
    },
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

/* 可视化开关条 */
.chart-toggle-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-md);
}

.chart-toggle-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chart-toggle-icon {
  color: var(--brand-primary);
  font-size: 18px;
}

.chart-toggle-label {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-text-primary);
}

/* 不适合可视化的提示（开关关闭时显示） */
.chart-skip-hint {
  font-size: 12px;
  color: var(--brand-text-tertiary);
  margin-left: 4px;
}

.chart-toggle-right {
  display: flex;
  align-items: center;
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
