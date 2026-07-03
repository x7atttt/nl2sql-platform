import { createApp } from 'vue'
import { createPinia } from 'pinia'
import './styles/variables.css'
// element-plus 样式覆盖（组件本体样式由 unplugin-vue-components 按需注入）
import './styles/element-overrides.css'
// 图标全量注册（图标库体积小 ~50KB，且模板里按名引用无法静态分析，保留全局注册）
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

import App from './App.vue'
import router from './router'
import './styles/index.css'
import './styles/transitions.css'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.mount('#app')
