/**
 * 应用引导入口
 *
 * 装配 Pinia/Element Plus/路由/权限指令，挂载前先恢复主题避免亮暗闪烁。
 */
import 'element-plus/dist/index.css'
import 'katex/dist/katex.min.css'
import './assets/main.css'
import './assets/markdown.css'
import 'highlight.js/styles/github.min.css'
import './assets/hljs-dark.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router from './router'
import { vPermission } from '@/directives/permission'
import { initTheme } from '@/composables/useTheme'

// 挂载前恢复主题，避免首屏亮暗闪烁
initTheme()

const app = createApp(App)

app.use(createPinia())
app.use(router)
// 中文 locale：EP 内置文案（分页 Total、表格空态 No Data 等）统一走中文
app.use(ElementPlus, { locale: zhCn })
app.directive('permission', vPermission)

app.mount('#app')
