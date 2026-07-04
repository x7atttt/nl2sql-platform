import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // 拆分大依赖到独立 chunk：
        // 1) 利用浏览器缓存（依赖不变则 chunk hash 不变，刷新零下载）
        // 2) 并行下载（HTTP/2 多路复用，多个小 chunk 比一个 1MB 大文件快）
        // 3) 按需加载（echarts 只在进 DatasetDetail 时加载）
        manualChunks: {
          // Vue 核心：vue + vue-router + pinia（几乎不变，长期缓存）
          'vue-vendor': ['vue', 'vue-router', 'pinia'],
          // Element Plus：全量引入（按需引入会漏掉 TabNavRenderer 等深层组件
          // 导致 el-tabs 渲染崩溃），独立 chunk 长期缓存抵消体积
          'element-plus': ['element-plus'],
          // ECharts + vue-echarts：只在 DatasetDetail 用，独立 chunk 按需加载
          echarts: ['echarts', 'vue-echarts'],
        },
      },
    },
    chunkSizeWarningLimit: 1000,
  },
})
