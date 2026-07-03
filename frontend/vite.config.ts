import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

export default defineConfig({
  plugins: [
    vue(),
    // Element Plus 按需引入：
    // 1) AutoImport：自动引入 ElMessage/ElMessageBox 等命令式 API
    // 2) Components：模板里用到的 <el-xxx> 自动按需引入对应组件
    // 效果：element-plus 从全量 989KB chunk → 按页面用到的组件 tree-shake
    AutoImport({ resolvers: [ElementPlusResolver()] }),
    Components({ resolvers: [ElementPlusResolver()] }),
  ],
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
        },
      },
    },
    chunkSizeWarningLimit: 600,
  },
})
