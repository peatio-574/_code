// 前端入口：挂载 Pinia、路由与 Element Plus。
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import router from './router'
// 全局基础样式（字号基线、Element Plus 变量覆盖），需在组件库样式之后引入
import './styles/global.css'

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
