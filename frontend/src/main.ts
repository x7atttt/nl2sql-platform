import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Element Plus 按需引入（手动注册）
// 说明：
// 1. 相比 app.use(ElementPlus) 全量引入，这里只注册项目实际用到的组件，
//    首屏（登录页）不再加载完整 element-plus（gzip ~150KB）。
// 2. 用 app.use(ElXxx) 而非 app.component('ElXxx', ElXxx)：前者会触发组件自身的
//    install 方法，自动注册其内部子组件（如 ElTabs 会注册 TabNav/TabNavRenderer 等），
//    这是手动按需比 unplugin 自动按需更安全的根本原因——后者只解析模板顶层标签，
//    会漏掉 TabNavRenderer 导致 el-tabs 渲染崩溃。
// 3. CSS 必须手动逐个引入：每个组件对应 element-plus/es/components/<name>/style/css。
// 4. 服务式 API（ElMessage/ElMessageBox）的样式也要单独引入，否则弹窗无样式。
// 直接从子模块路径导入，绕开 element-plus 主入口（es/index.mjs）的整包 re-export。
// 主入口静态 re-export 所有组件且副作用标记不完整，rollup 无法跨 chunk 摇掉未用组件；
// 子模块路径（element-plus/es/components/<name>）只拉对应组件的依赖图，tree-shake 才真正生效。
// 说明：子组件（aside/header/main、form-item、tab-pane 等）没有独立目录，从父模块统一导入。
// withInstall 的父组件（如 ElTabs/ElContainer/ElButton）会自动注册其内部子组件，
// 所以即使只 use(ElTabs) 也能正常渲染 TabNav/TabNavRenderer（这是手动按需比 unplugin
// 自动按需更安全的根因——后者只解析模板顶层标签，漏掉 TabNavRenderer 导致崩溃）。
import { ElAlert } from 'element-plus/es/components/alert/index'
import { ElButton } from 'element-plus/es/components/button/index'
import { ElContainer, ElAside, ElHeader, ElMain } from 'element-plus/es/components/container/index'
import { ElDialog } from 'element-plus/es/components/dialog/index'
import { ElDropdown, ElDropdownItem, ElDropdownMenu } from 'element-plus/es/components/dropdown/index'
import { ElEmpty } from 'element-plus/es/components/empty/index'
import { ElForm, ElFormItem } from 'element-plus/es/components/form/index'
import { ElIcon } from 'element-plus/es/components/icon/index'
import { ElInput } from 'element-plus/es/components/input/index'
import { ElDescriptions, ElDescriptionsItem } from 'element-plus/es/components/descriptions/index'
import { ElMenu, ElMenuItem } from 'element-plus/es/components/menu/index'
import { ElPagination } from 'element-plus/es/components/pagination/index'
import { ElRadioGroup, ElRadioButton } from 'element-plus/es/components/radio/index'
import { ElSelect, ElOption } from 'element-plus/es/components/select/index'
import { ElSwitch } from 'element-plus/es/components/switch/index'
import { ElTable, ElTableColumn } from 'element-plus/es/components/table/index'
import { ElTabs, ElTabPane } from 'element-plus/es/components/tabs/index'
import { ElTag } from 'element-plus/es/components/tag/index'
import { ElTooltip } from 'element-plus/es/components/tooltip/index'
import { ElUpload } from 'element-plus/es/components/upload/index'

// 组件样式（按需）
import 'element-plus/es/components/alert/style/css'
import 'element-plus/es/components/aside/style/css'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/button-group/style/css'
import 'element-plus/es/components/container/style/css'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/empty/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/header/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import 'element-plus/es/components/main/style/css'
import 'element-plus/es/components/descriptions/style/css'
import 'element-plus/es/components/descriptions-item/style/css'
import 'element-plus/es/components/menu/style/css'
import 'element-plus/es/components/menu-item/style/css'
import 'element-plus/es/components/option/style/css'
import 'element-plus/es/components/pagination/style/css'
import 'element-plus/es/components/radio-button/style/css'
import 'element-plus/es/components/radio-group/style/css'
import 'element-plus/es/components/select/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/es/components/table/style/css'
import 'element-plus/es/components/table-column/style/css'
import 'element-plus/es/components/tabs/style/css'
import 'element-plus/es/components/tab-pane/style/css'
import 'element-plus/es/components/tag/style/css'
import 'element-plus/es/components/tooltip/style/css'
import 'element-plus/es/components/upload/style/css'
// 服务式 API 样式（ElMessage / ElMessageBox 在业务代码里 from 'element-plus' 调用，
// 其 CSS 不会自动加载，必须在这里手动引入，否则弹窗无样式）
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/overlay/style/css' // MessageBox 依赖的遮罩层

// 全局样式
import './styles/variables.css'
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

// Element Plus 组件按需注册
const elementPlugins = [
  ElAlert,
  ElAside,
  ElButton,
  ElContainer,
  ElDialog,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElEmpty,
  ElForm,
  ElFormItem,
  ElHeader,
  ElIcon,
  ElInput,
  ElMain,
  ElDescriptions,
  ElDescriptionsItem,
  ElMenu,
  ElMenuItem,
  ElOption,
  ElPagination,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElSwitch,
  ElTable,
  ElTableColumn,
  ElTabs,
  ElTabPane,
  ElTag,
  ElTooltip,
  ElUpload,
]
for (const plugin of elementPlugins) {
  app.use(plugin)
}

app.mount('#app')
