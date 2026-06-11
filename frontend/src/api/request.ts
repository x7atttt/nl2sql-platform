import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const request = axios.create({
  baseURL: '',
  timeout: 30000,
  withCredentials: true,
})

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('user')
      router.push({ name: 'login' })
      ElMessage.error('登录已过期，请重新登录')
    } else if (error.response?.status === 403) {
      ElMessage.error('没有操作权限')
    } else {
      const msg = error.response?.data?.error || error.response?.data?.detail || '请求失败'
      ElMessage.error(msg)
    }
    return Promise.reject(error)
  }
)

export default request
