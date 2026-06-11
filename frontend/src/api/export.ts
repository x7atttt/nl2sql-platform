import request from './request'

export const exportApi = {
  exportFile(queryId: string, format: 'csv' | 'xlsx') {
    return request.get(`/api/export/${queryId}/${format}/`, {
      responseType: 'blob',
    })
  },
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
