<template>
  <div class="page-container">
    <!-- 标题区分角色：admin=全平台运营视角，其他=个人面板 -->
    <div class="dashboard-header">
      <h2>{{ isAdmin ? '全平台运营概览' : '我的数据面板' }}</h2>
      <p class="dashboard-subtitle">
        {{ isAdmin ? '查看所有数据集与查询的整体表现' : '查看你的数据集与查询活动' }}
      </p>
    </div>

    <!-- 4 个数字卡片 -->
    <div class="stat-cards">
      <div
        class="stat-card stagger-item"
        v-for="(card, i) in statCards"
        :key="i"
        :style="{ '--stagger-index': i, '--card-accent': card.color }"
      >
        <el-icon class="decorative-icon"><component :is="card.icon" /></el-icon>
        <div class="stat-number">{{ card.value }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </div>
    </div>

    <!-- 查询趋势（30 天 ECharts 双线折线图） -->
    <div class="page-section">
      <div class="section-header">
        <h3>查询趋势（近 30 天）</h3>
      </div>
      <v-chart
        v-if="trendOption"
        class="trend-chart"
        :option="trendOption"
        autoresize
      />
      <el-empty v-else description="暂无查询记录" :image-size="80" />
    </div>

    <!-- 数据集健康度表 -->
    <div class="page-section">
      <div class="section-header">
        <h3>数据集健康度</h3>
      </div>
      <el-table :data="datasetHealth" stripe size="small" empty-text="暂有查询记录的数据集">
        <el-table-column prop="name" label="数据集" min-width="160" />
        <el-table-column label="查询数" width="90">
          <template #default="{ row }">{{ row.query_count }}</template>
        </el-table-column>
        <el-table-column label="成功率" width="110">
          <template #default="{ row }">
            <el-tag :type="successRateTagType(row.success_rate)" size="small">
              {{ (row.success_rate * 100).toFixed(0) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="平均耗时" width="100">
          <template #default="{ row }">{{ formatDuration(row.avg_time_ms) }}</template>
        </el-table-column>
        <el-table-column label="最后查询" width="160">
          <template #default="{ row }">{{ formatTime(row.last_query_at) }}</template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { DataAnalysis, FolderOpened, Timer, TrendCharts } from '@element-plus/icons-vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption } from 'echarts/charts'
import type { GridComponentOption, TooltipComponentOption, LegendComponentOption } from 'echarts/components'
import { useUserStore } from '../stores/user'
import { dashboardApi, type DashboardStats, type TrendPoint } from '../api/dashboard'

// ECharts 按需引入（只需折线图，比 ResultChart 更精简）
use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])
type EChartsOption = ComposeOption<
  LineSeriesOption | GridComponentOption | TooltipComponentOption | LegendComponentOption
>

const store = useUserStore()
const isAdmin = computed(() => store.user?.role === 'admin')

const stats = ref<DashboardStats | null>(null)

// 4 个汇总卡片
const statCards = computed(() => {
  const s = stats.value?.summary
  return [
    {
      label: '总查询数',
      value: s?.total_queries ?? 0,
      icon: DataAnalysis,
      color: '#2563eb',
    },
    {
      label: '成功率',
      value: s ? `${(s.success_rate * 100).toFixed(0)}%` : '0%',
      icon: TrendCharts,
      color: '#059669',
    },
    {
      label: '平均耗时',
      value: s ? formatDuration(s.avg_time_ms) : '-',
      icon: Timer,
      color: '#d97706',
    },
    {
      label: '活跃数据集',
      value: s?.active_datasets ?? 0,
      icon: FolderOpened,
      color: '#7c3aed',
    },
  ]
})

// 查询趋势 ECharts option（前端补齐 30 天连续日期，无数据的天补 0）
const trendOption = computed<EChartsOption | null>(() => {
  const trend = stats.value?.trend
  if (!trend || !trend.length) return null

  // 后端只返回有数据的天，前端补齐最近 30 天连续日期
  const fullRange = buildLast30Days(trend)
  const dates = fullRange.map((p) => p.date.slice(5))  // MM-DD 显示更紧凑
  const totalCounts = fullRange.map((p) => p.count)
  const successCounts = fullRange.map((p) => p.success_count)

  return {
    tooltip: {
      trigger: 'axis',
    },
    legend: {
      data: ['总查询', '成功查询'],
      bottom: 0,
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '12%',
      top: '8%',
      containLabel: true,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: dates,
    },
    yAxis: {
      type: 'value',
      minInterval: 1,  // 查询数是整数，不让 Y 轴出现小数
    },
    series: [
      {
        name: '总查询',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: totalCounts,
        itemStyle: { color: '#2563eb' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(37, 99, 235, 0.25)' },
              { offset: 1, color: 'rgba(37, 99, 235, 0)' },
            ],
          },
        },
      },
      {
        name: '成功查询',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 6,
        data: successCounts,
        itemStyle: { color: '#059669' },
      },
    ],
  }
})

const datasetHealth = computed(() => stats.value?.dataset_health ?? [])

onMounted(async () => {
  try {
    const res = await dashboardApi.getStats()
    stats.value = res.data
  } catch { /* interceptor handles error */ }
})

/**
 * 把后端返回的稀疏 trend（只含有数据的天）补齐为最近 30 天连续序列。
 * 无数据的天 count=0, success_count=0。
 */
function buildLast30Days(sparse: TrendPoint[]): TrendPoint[] {
  const map = new Map(sparse.map((p) => [p.date, p]))
  const result: TrendPoint[] = []
  const today = new Date()
  for (let i = 29; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const key = d.toISOString().slice(0, 10)  // YYYY-MM-DD
    const point = map.get(key)
    result.push({
      date: key,
      count: point?.count ?? 0,
      success_count: point?.success_count ?? 0,
    })
  }
  return result
}

function successRateTagType(rate: number): 'success' | 'warning' | 'danger' {
  if (rate >= 0.9) return 'success'
  if (rate >= 0.7) return 'warning'
  return 'danger'
}

function formatDuration(ms: number): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTime(t: string | null): string {
  if (!t) return '-'
  return t.replace('T', ' ').slice(0, 19)
}
</script>

<style scoped>
.dashboard-header {
  margin-bottom: var(--space-lg);
}

.dashboard-header h2 {
  font-size: 20px;
  font-weight: 700;
  color: var(--brand-text-primary);
  margin-bottom: 4px;
}

.dashboard-subtitle {
  font-size: 13px;
  color: var(--brand-text-tertiary);
}

.stat-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-lg);
  margin-bottom: var(--space-lg);
}

.stat-card {
  position: relative;
  padding: var(--space-lg);
  background: var(--brand-surface);
  border-radius: 12px;
  box-shadow: var(--brand-shadow-sm);
  overflow: hidden;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--brand-shadow-md);
}

.stat-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--card-accent, var(--brand-accent));
  border-radius: 0 2px 2px 0;
}

.decorative-icon {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 48px;
  opacity: 0.08;
  color: var(--card-accent, var(--brand-accent));
}

.stat-number {
  font-size: 32px;
  font-weight: 700;
  color: var(--card-accent, var(--brand-accent));
  margin-bottom: 4px;
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: var(--brand-text-tertiary);
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-md);
}

.section-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-text-primary);
}

.trend-chart {
  width: 100%;
  height: 320px;
}

@media (max-width: 768px) {
  .stat-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
