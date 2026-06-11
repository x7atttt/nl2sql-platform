import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('../views/Register.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('../layouts/MainLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          name: 'dashboard',
          component: () => import('../views/Dashboard.vue'),
        },
        {
          path: 'datasets',
          name: 'datasets',
          component: () => import('../views/DatasetList.vue'),
        },
        {
          path: 'datasets/:id',
          name: 'dataset-detail',
          component: () => import('../views/DatasetDetail.vue'),
        },
        {
          path: 'query/history',
          name: 'query-history',
          component: () => import('../views/QueryHistory.vue'),
        },
        {
          path: 'users/manage',
          name: 'user-manage',
          component: () => import('../views/UserManage.vue'),
          meta: { requiresAdmin: true },
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const userStr = sessionStorage.getItem('user')
  if (to.meta.requiresAuth !== false && !userStr) {
    return { name: 'login' }
  }
  if (to.meta.requiresAdmin) {
    try {
      const user = JSON.parse(userStr || '{}')
      if (user.role !== 'admin') return { name: 'dashboard' }
    } catch {
      sessionStorage.removeItem('user')
      return { name: 'login' }
    }
  }
})

export default router
