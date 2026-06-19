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

/** WebSocket 推送的消息格式（与后端 tasks._send_progress 对应） */
export interface ProgressMessage {
  progress: number   // 已处理行数
  status: 'processing' | 'completed' | 'failed'
  message: string
}

/**
 * 创建数据集处理进度 WebSocket 连接
 *
 * 浏览器原生 WebSocket，自动携带同源 session cookie（无需手动传认证）。
 * dev 下走 Vite /ws 代理，生产走 nginx /ws/ 代理。
 *
 * @param datasetId 数据集 ID（UUID）
 * @param onMessage 收到进度/终态消息的回调
 * @param onError   连接异常回调（如后端不可用，调用方可回退 HTTP 查询）
 * @returns WebSocket 实例（调用方负责在组件卸载时 close）
 */
export function createProgressSocket(
  datasetId: string,
  onMessage: (data: ProgressMessage) => void,
  onError?: (e: Event) => void,
): WebSocket {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  // dev 下直连后端 8000（绕过 Vite 的 WS 代理坑），生产走同源（nginx 代理）
  const host = import.meta.env.DEV ? 'localhost:8000' : location.host
  const url = `${protocol}//${host}/ws/datasets/${datasetId}/progress/`
  const socket = new WebSocket(url)

  socket.onmessage = (ev) => {
    try {
      onMessage(JSON.parse(ev.data))
    } catch {
      /* 忽略非 JSON 帧 */
    }
  }
  socket.onerror = (e) => onError?.(e)

  return socket
}
