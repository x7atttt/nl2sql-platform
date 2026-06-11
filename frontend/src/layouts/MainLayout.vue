<template>
  <el-container class="main-layout">
    <el-aside :width="isCollapse ? '64px' : '200px'" class="sidebar">
      <div class="logo">
        <span v-show="!isCollapse">AI 数据分析</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapse"
        background-color="#304156"
        text-color="#bfcbd9"
        active-text-color="#409eff"
        router
      >
        <el-menu-item index="/">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>仪表盘</template>
        </el-menu-item>
        <el-menu-item index="/datasets">
          <el-icon><FolderOpened /></el-icon>
          <template #title>数据集</template>
        </el-menu-item>
        <el-menu-item index="/query/history">
          <el-icon><Clock /></el-icon>
          <template #title>查询历史</template>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users/manage">
          <el-icon><User /></el-icon>
          <template #title>用户管理</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="top-bar">
        <el-icon class="collapse-btn" @click="isCollapse = !isCollapse">
          <Fold v-if="!isCollapse" />
          <Expand v-else />
        </el-icon>
        <div class="user-area">
          <el-dropdown>
            <span class="user-name">
              {{ store.user?.username }}
              <el-tag size="small" :type="roleTagType" class="role-tag">{{ roleLabel }}</el-tag>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { userApi } from '../api/user'
import { ElMessage } from 'element-plus'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const isCollapse = ref(false)

store.initFromStorage()

const activeMenu = computed(() => {
  if (route.path.startsWith('/datasets')) return '/datasets'
  return route.path
})

const isAdmin = computed(() => store.user?.role === 'admin')

const roleLabel = computed(() => {
  const map: Record<string, string> = { admin: '管理员', analyst: '分析师', viewer: '只读用户' }
  return map[store.user?.role || 'viewer']
})

const roleTagType = computed(() => {
  const map: Record<string, string> = { admin: 'danger', analyst: 'warning', viewer: 'info' }
  return map[store.user?.role || 'viewer'] as any
})

async function handleLogout() {
  try {
    await userApi.logout()
  } finally {
    store.clearUser()
    ElMessage.success('已退出登录')
    router.push({ name: 'login' })
  }
}
</script>

<style scoped>
.main-layout {
  height: 100vh;
}

.sidebar {
  background-color: #304156;
  transition: width 0.3s;
  overflow: hidden;
}

.logo {
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.el-menu {
  border-right: none;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e6e6e6;
  background: #fff;
}

.collapse-btn {
  font-size: 20px;
  cursor: pointer;
  color: #606266;
}

.user-area {
  display: flex;
  align-items: center;
}

.user-name {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
}

.role-tag {
  margin-left: 4px;
}
</style>
