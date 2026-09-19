import { createRouter, createWebHistory } from 'vue-router'
import WorkbenchView from '../views/WorkbenchView.vue'
import ReportView from '../views/ReportView.vue'
import MaterialNewView from '../views/MaterialNewView.vue'
import MaterialsView from '../views/MaterialsView.vue'
import MaterialDetailView from '../views/MaterialDetailView.vue'
import MaterialReportView from '../views/MaterialReportView.vue'
import CompareView from '../views/CompareView.vue'
import DiffView from '../views/DiffView.vue'
import GrillView from '../views/GrillView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'workbench', component: WorkbenchView },
    { path: '/report', name: 'report', component: ReportView },
    { path: '/materials', name: 'materials', component: MaterialsView },
    // 静态段优先于 /materials/:materialId，不会落入详情路由。
    { path: '/materials/new', name: 'material-new', component: MaterialNewView },
    { path: '/materials/:materialId', name: 'material-detail', component: MaterialDetailView },
    { path: '/materials/:materialId/report', name: 'material-report', component: MaterialReportView },
    { path: '/compare', name: 'compare', component: CompareView },
    { path: '/diff', name: 'diff', component: DiffView },
    { path: '/grill', name: 'grill', component: GrillView },
    // 兼容旧链接：/preview 不再是正式导航目标。
    { path: '/preview', redirect: '/materials/new' },
  ],
})
