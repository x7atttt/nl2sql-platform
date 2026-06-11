import { defineStore } from 'pinia'
import { ref } from 'vue'
import { userApi } from '../api/user'

export interface UserInfo {
  id: number
  username: string
  email: string
  role: 'admin' | 'analyst' | 'viewer'
  is_active: boolean
  date_joined: string
}

export const useUserStore = defineStore('user', () => {
  const user = ref<UserInfo | null>(null)
  const isLoggedIn = ref(false)

  function setUser(info: UserInfo) {
    user.value = info
    isLoggedIn.value = true
    sessionStorage.setItem('user', JSON.stringify(info))
  }

  function clearUser() {
    user.value = null
    isLoggedIn.value = false
    sessionStorage.removeItem('user')
  }

  async function fetchProfile() {
    const res = await userApi.getProfile()
    setUser(res.data)
  }

  function initFromStorage() {
    const stored = sessionStorage.getItem('user')
    if (stored) {
      user.value = JSON.parse(stored)
      isLoggedIn.value = true
    }
  }

  return { user, isLoggedIn, setUser, clearUser, fetchProfile, initFromStorage }
})
