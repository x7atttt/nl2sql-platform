<template>
  <AuthLayout>
    <template #title>DataLens</template>
    <template #subtitle>登录以开始智能数据分析</template>
    <el-form :model="form" @submit.prevent="handleLogin">
      <el-form-item>
        <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" size="large" />
      </el-form-item>
      <el-form-item>
        <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" size="large" show-password />
      </el-form-item>
      <el-form-item>
        <SliderCaptcha ref="captchaRef" @verified="captchaVerified = true" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" size="large" :loading="loading" :disabled="!captchaVerified" native-type="submit">登录</el-button>
      </el-form-item>
    </el-form>
    <div class="link-row">
      没有账号？<router-link to="/register">去注册</router-link>
    </div>
  </AuthLayout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { User, Lock } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'
import { userApi } from '../api/user'
import { ElMessage } from 'element-plus'
import AuthLayout from '../components/AuthLayout.vue'
import SliderCaptcha from '../components/SliderCaptcha.vue'

const router = useRouter()
const store = useUserStore()
const loading = ref(false)
const form = ref({ username: '', password: '' })
const captchaVerified = ref(false)
const captchaRef = ref<InstanceType<typeof SliderCaptcha>>()

async function handleLogin() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const res = await userApi.login(form.value)
    store.setUser(res.data)
    ElMessage.success('登录成功')
    router.push({ name: 'dashboard' })
  } catch {
    // 登录失败：重置验证码，强制重新滑块（防暴力破解）
    captchaVerified.value = false
    captchaRef.value?.reset()
  } finally {
    loading.value = false
  }
}
</script>
