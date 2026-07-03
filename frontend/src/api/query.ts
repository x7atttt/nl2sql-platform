import request from './request'

export const queryApi = {
  query(datasetId: string, question: string) {
    return request.post(`/api/query/${datasetId}/`, { question })
  },

  getHistory(params: { page?: number; dataset_id?: string } = {}) {
    return request.get('/api/query/history/', { params })
  },

  rerun(historyId: string) {
    return request.post(`/api/query/history/${historyId}/rerun/`)
  },

  /** LLM 智能图表推荐（异步，前端拿到查询结果后单独请求） */
  suggestChart(queryId: string) {
    return request.post(`/api/query/${queryId}/chart-suggest/`, {}, {
      timeout: 60000, // LLM 调用可能较慢（7-15秒），放宽到 60 秒
    })
  },
}
