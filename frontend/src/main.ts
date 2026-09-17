//前端入口。创建 Vue 应用，安装插件
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ui from '@nuxt/ui/vue-plugin'
import { router } from './router'
import App from './App.vue'
import './style.css'

createApp(App).use(createPinia()).use(router).use(ui).mount('#app')
