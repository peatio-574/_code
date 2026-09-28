// 前端入口：挂载 Pinia、路由与 Element Plus。
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
// 全局基础样式（字号基线、Element Plus 变量覆盖），需在组件库样式之后引入
import './styles/global.css'

// 发版后旧页面引用的分包哈希已失效（404），Vite 会抛出 preloadError。
// 这里自动刷新一次获取最新资源，避免用户看到 "Failed to fetch dynamically imported module"。
const RELOAD_GUARD_KEY = 'edu:chunk-reload-at'
window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  const last = Number(sessionStorage.getItem(RELOAD_GUARD_KEY) || 0)
  if (Date.now() - last < 10000) return
  sessionStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
  window.location.reload()
})

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
