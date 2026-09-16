import { createRouter, createWebHistory } from 'vue-router'
import WorkbenchView from '../views/WorkbenchView.vue'
import ReportView from '../views/ReportView.vue'
import PreviewView from '../views/PreviewView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'workbench', component: WorkbenchView },
    { path: '/report', name: 'report', component: ReportView },
    { path: '/preview', name: 'preview', component: PreviewView },
  ],
})
