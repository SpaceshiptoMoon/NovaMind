import 'element-plus/dist/index.css'
import './assets/main.css'
import 'highlight.js/styles/github.min.css'

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
