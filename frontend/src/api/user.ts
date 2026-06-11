import request from './request'

export const userApi = {
  register(data: { username: string; password: string; email: string }) {
    return request.post('/api/users/register/', data)
  },

  login(data: { username: string; password: string }) {
    return request.post('/api/users/login/', data)
  },

  logout() {
    return request.post('/api/users/logout/')
  },

  getProfile() {
    return request.get('/api/users/profile/')
  },

  getUserList() {
    return request.get('/api/users/manage/')
  },

  updateUserRole(id: number, role: string) {
    return request.patch(`/api/users/manage/${id}/`, { role })
  },

  disableUser(id: number) {
    return request.delete(`/api/users/manage/${id}/`)
  },
}
