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

import App from './App.vue'
import router from './router'
import { vPermission } from '@/directives/permission'
import { initTheme } from '@/composables/useTheme'

// 挂载前恢复主题，避免首屏亮暗闪烁
initTheme()

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus)
app.directive('permission', vPermission)

app.mount('#app')
