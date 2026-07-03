/**
 * 查询结果图表选型规则引擎（纯函数，借鉴 Vanna/Metabase 思路）
 *
 * 核心原则：信任 NL2SQL 语义——用户问聚合 SQL 就直接画，问明细就提示。
 * 不做前端二次聚合（前端 GROUP BY 会和用户意图不符）。
 */

export type ColumnType = 'number' | 'text' | 'date' | 'boolean'

/** null 表示"不建议可视化"（明细数据或无可视维度） */
export type ChartType = 'bar' | 'line' | 'pie' | 'scatter' | 'area' | null

export interface ChartSuggestion {
  chartType: ChartType
  xField: string
  yFields: string[]
  /** 推荐理由，展示给用户（小字灰色） */
  reason: string
  /** 该数据形状支持切换的其他图表类型（不含 chartType 本身） */
  alternatives: ChartType[]
}

/** 算某列 distinct 值数量（≤1000 行无性能压力） */
function distinctCount(data: Record<string, unknown>[], col: string): number {
  return new Set(data.map((r) => r[col])).size
}

/** 按列类型分组，返回维度列（可作 X 轴）和度量列（可作 Y 轴） */
function classifyColumns(
  columns: string[],
  types: Record<string, ColumnType>,
): { dimensions: string[]; measures: string[] } {
  const dimensions: string[] = []   // text / date → 分类/时间维度
  const measures: string[] = []     // number → 度量
  for (const col of columns) {
    const t = types[col]
    if (t === 'number') {
      measures.push(col)
    } else if (t === 'text' || t === 'date') {
      dimensions.push(col)
    }
    // boolean 暂不归类（少见，避免饼图碎裂）
  }
  return { dimensions, measures }
}

/**
 * 主选型函数：基于列类型组合 + distinct 数量选默认图表。
 *
 * 规则优先级：
 * 1. 明细护栏：行数 >50 且列数 >4 → 判为明细记录，不画图
 * 2. 日期趋势：1 日期维度 + 1+ 度量 → 折线
 * 3. 占比构成：1 文本维度 + 1 度量且 distinct≤7 → 饼图
 * 4. 分类对比：1 文本维度 + 1+ 度量且 distinct≤20 → 柱状
 * 5. 相关性：2 数值列 → 散点
 * 6. 单数值：仅 1 数值列无维度 → 柱状（取 top 20）
 * 7. 其余（全文本/单列）→ 不画图
 */
export function suggestChart(
  columns: string[],
  types: Record<string, ColumnType>,
  data: Record<string, unknown>[],
): ChartSuggestion {
  // 空数据兜底（理论上调用方已挡，双保险）
  if (!data.length) {
    return { chartType: null, xField: '', yFields: [], reason: '无数据', alternatives: [] }
  }

  // 1. 明细护栏：行数多 + 列数多 = 大概率明细记录，画图无意义
  if (data.length > 50 && columns.length > 4) {
    return {
      chartType: null,
      xField: '',
      yFields: [],
      reason: '数据看起来是明细记录（行数多、列数多），可视化效果不佳。建议用 GROUP BY 聚合后再查询。',
      alternatives: [],
    }
  }

  const { dimensions, measures } = classifyColumns(columns, types)
  const dateDims = dimensions.filter((c) => types[c] === 'date')
  const textDims = dimensions.filter((c) => types[c] === 'text')

  // 2. 日期趋势 → 折线
  if (dateDims.length >= 1 && measures.length >= 1) {
    return {
      chartType: 'line',
      xField: dateDims[0],
      yFields: measures.slice(0, 5),
      reason: `检测到日期列「${dateDims[0]}」+ ${measures.length} 个数值列，推荐折线图展示趋势`,
      alternatives: ['bar', 'area'],
    }
  }

  // 3. 单文本维度 + 单度量且类别少 → 饼图（占比构成）
  if (textDims.length >= 1 && measures.length === 1) {
    const dc = distinctCount(data, textDims[0])
    if (dc <= 7) {
      return {
        chartType: 'pie',
        xField: textDims[0],
        yFields: [measures[0]],
        reason: `检测到分类列「${textDims[0]}」（${dc} 个类别）+ 1 个数值列，推荐饼图展示占比构成`,
        alternatives: ['bar'],
      }
    }
  }

  // 4. 文本维度 + 度量，类别适中 → 柱状（分类对比）
  if (textDims.length >= 1 && measures.length >= 1) {
    const dc = distinctCount(data, textDims[0])
    if (dc <= 20) {
      return {
        chartType: 'bar',
        xField: textDims[0],
        yFields: measures.slice(0, 5),
        reason: `检测到分类列「${textDims[0]}」（${dc} 个类别）+ ${measures.length} 个数值列，推荐柱状图对比`,
        alternatives: ['line', 'pie', 'area'],
      }
    }
  }

  // 5. 两数值列 → 散点（相关性）
  if (measures.length >= 2 && dimensions.length === 0) {
    return {
      chartType: 'scatter',
      xField: measures[0],
      yFields: [measures[1]],
      reason: `检测到 2 个数值列「${measures[0]}」「${measures[1]}」，推荐散点图观察相关性`,
      alternatives: ['bar'],
    }
  }

  // 6. 单数值列无维度 → 柱状取 top 20
  if (measures.length === 1 && dimensions.length === 0) {
    return {
      chartType: 'bar',
      xField: '',
      yFields: [measures[0]],
      reason: `仅有 1 个数值列「${measures[0]}」，取前 20 行展示`,
      alternatives: ['line'],
    }
  }

  // 7. 其余：全文本/全单列/无度量 → 不画图
  return {
    chartType: null,
    xField: '',
    yFields: [],
    reason: '未检测到适合可视化的维度+度量组合（需要至少 1 个分类/日期列和 1 个数值列）。',
    alternatives: [],
  }
}
