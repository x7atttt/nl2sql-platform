import request from './request'

/** Dashboard BI 概览聚合数据（GET /api/query/stats/） */
export interface DashboardStats {
  trend: TrendPoint[]
  dataset_health: DatasetHealth[]
  summary: Summary
}

export interface TrendPoint {
  date: string      // YYYY-MM-DD
  count: number     // 当日总查询数
  success_count: number  // 当日成功查询数
}

export interface DatasetHealth {
  id: string
  name: string
  query_count: number
  success_rate: number    // 0-1
  avg_time_ms: number
  last_query_at: string | null
}

export interface Summary {
  total_queries: number
  success_rate: number    // 0-1
  avg_time_ms: number
  active_datasets: number
}

export const dashboardApi = {
  getStats() {
    return request.get<DashboardStats>('/api/query/stats/')
  },
}
