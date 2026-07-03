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
      <!-- 工具栏：图表类型切换 + 轴选择 -->
      <div class="chart-toolbar">
        <el-radio-group v-model="currentType" size="small">
          <el-radio-button value="bar">柱状</el-radio-button>
          <el-radio-button value="line">折线</el-radio-button>
          <el-radio-button value="area">面积</el-radio-button>
          <el-radio-button value="pie">饼图</el-radio-button>
          <el-radio-button value="scatter">散点</el-radio-button>
        </el-radio-group>
        <div class="axis-selectors">
          <el-select v-model="currentXField" placeholder="X 轴" size="small" style="width: 140px">
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
          >
            <el-option v-for="c in measureOptions" :key="c" :label="c" :value="c" />
          </el-select>
        </div>
      </div>

      <!-- ECharts 渲染 -->
      <v-chart
        class="chart-canvas"
        :option="chartOption"
        :loading="false"
        autoresize
      />

      <!-- 推荐理由 -->
      <div class="chart-reason">💡 {{ currentSuggestion.reason }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { PieChart } from '@element-plus/icons-vue'
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

use([
  CanvasRenderer,
  BarChart, LineChart, EPieChart, ScatterChart,
  GridComponent, TooltipComponent, LegendComponent, TitleComponent, DataZoomComponent,
])

const props = defineProps<{
  data: Record<string, unknown>[]
  columns: string[]
  columnTypes: Record<string, ColumnType>
}>()

// 初次进入时按规则引擎推荐默认配置
const initial = suggestChart(props.columns, props.columnTypes, props.data)
const currentType = ref<Exclude<ChartType, null>>(initial.chartType ?? 'bar')
const currentXField = ref(initial.xField)
const currentYFields = ref<string[]>(initial.yFields)

// 数据/列变化时重新推荐（如换了查询结果）
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
  const xData = x ? data.map((r) => String(r[x] ?? '')) : data.map((_, i) => `#${i + 1}`)
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
        data: data.map((r) => ({ name: x ? String(r[x] ?? '') : '', value: Number(r[y]) || 0 })),
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
    tooltip: { trigger: 'item' },
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
