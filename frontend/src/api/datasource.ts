import request from './request'

export interface DataSource {
  id: string
  name: string
  db_type: 'mysql' | 'postgresql'
  host: string
  port: number
  database: string
  username: string
  business_description: string
  status: 'active' | 'error'
  last_tested_at: string | null
  owner: number
  owner_name: string
  created_at: string
}

export const datasourceApi = {
  getList() {
    return request.get('/api/datasources/')
  },

  create(payload: Record<string, unknown>) {
    return request.post('/api/datasources/', payload)
  },

  remove(id: string) {
    return request.delete(`/api/datasources/${id}/`)
  },

  /** 保存前按连接参数测试连通性（不落库） */
  testParams(payload: Record<string, unknown>) {
    return request.post('/api/datasources/test-params/', payload, {
      timeout: 15000, // 连接超时 5s + 余量
    })
  },

  /** 对已存数据源重测 */
  test(id: string) {
    return request.post(`/api/datasources/${id}/test/`, {}, { timeout: 15000 })
  },

  /** 表结构浏览（表/列/注释/近似行数/top 值） */
  getTables(id: string) {
    return request.get(`/api/datasources/${id}/tables/`, { timeout: 30000 })
  },

  /** 自然语言查询（表数超上限时须传 tables） */
  query(id: string, question: string, tables?: string[]) {
    return request.post(`/api/datasources/${id}/query/`, {
      question, ...(tables ? { tables } : {}),
    })
  },
}
