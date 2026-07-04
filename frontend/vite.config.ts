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
          // ECharts + vue-echarts：只在 DatasetDetail 用，独立 chunk 按需加载
          echarts: ['echarts', 'vue-echarts'],
          // 注意：element-plus 不再强制独立 chunk。
          // 原方案是全量引入 + 独立 chunk 长期缓存抵消体积；
          // 现改为 main.ts 手动按需注册，若仍把 'element-plus' 整包归为一个 chunk，
          // rollup 会把整个 es/index.mjs 的 re-export 图都拉进来（跨 chunk tree-shake 失效），
          // 按需引入形同虚设。移除后各组件随使用方分散到对应 chunk，才能真正 tree-shake。
        },
      },
    },
    chunkSizeWarningLimit: 1000,
  },
})
