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
}
