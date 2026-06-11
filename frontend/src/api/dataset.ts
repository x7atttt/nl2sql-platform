import request from './request'

export const datasetApi = {
  getList(page = 1) {
    return request.get('/api/datasets/', { params: { page } })
  },

  getDetail(id: string) {
    return request.get(`/api/datasets/${id}/`)
  },

  upload(formData: FormData) {
    return request.post('/api/datasets/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
  },

  delete(id: string) {
    return request.delete(`/api/datasets/${id}/`)
  },

  getAnalysis(id: string) {
    return request.get(`/api/datasets/${id}/analysis/`)
  },
}
