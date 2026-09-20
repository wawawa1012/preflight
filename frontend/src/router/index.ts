import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ReviewNewView from '../views/review/ReviewNewView.vue'
import ReviewWorkspaceView from '../views/review/ReviewWorkspaceView.vue'
import ReviewOverviewView from '../views/review/ReviewOverviewView.vue'
import ReviewConsistencyView from '../views/review/ReviewConsistencyView.vue'
import ReviewDiffView from '../views/review/ReviewDiffView.vue'
import ReviewGrillView from '../views/review/ReviewGrillView.vue'
import ReviewMembersView from '../views/review/ReviewMembersView.vue'
import SourceReaderView from '../views/review/SourceReaderView.vue'
import RevisionEditorView from '../views/review/RevisionEditorView.vue'
import ReportView from '../views/ReportView.vue'
import MaterialNewView from '../views/MaterialNewView.vue'
import MaterialsView from '../views/MaterialsView.vue'
import MaterialDetailView from '../views/MaterialDetailView.vue'
import MaterialReportView from '../views/MaterialReportView.vue'

// 导航模型：Home（审查入口）→ Review Workspace（同一次审查的视角集合）→ Source Reader（沉浸阅读原文）。
// 独立的 /compare /diff /grill 已并入工作区，旧链接重定向到 Home。
export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/reviews/new', name: 'review-new', component: ReviewNewView },
    {
      path: '/reviews/:reviewId',
      component: ReviewWorkspaceView,
      children: [
        { path: '', name: 'review-overview', component: ReviewOverviewView },
        { path: 'consistency', name: 'review-consistency', component: ReviewConsistencyView },
        { path: 'diff', name: 'review-diff', component: ReviewDiffView },
        { path: 'grill', name: 'review-grill', component: ReviewGrillView },
        { path: 'members', name: 'review-members', component: ReviewMembersView },
      ],
    },
    // Source Reader 独立于 workspace shell：沉浸阅读，返回经 session store 恢复来源页。
    { path: '/reviews/:reviewId/reader/:materialId', name: 'source-reader', component: SourceReaderView },
    // 修订稿编辑器：Review 模式保存时自动加入本次审查；独立模式继承 parent 绑定、不入任何 Review。
    { path: '/reviews/:reviewId/reader/:materialId/revise', name: 'revision-editor', component: RevisionEditorView },
    { path: '/materials/:materialId/revise', name: 'material-revise', component: RevisionEditorView },
    { path: '/report', name: 'report', component: ReportView },
    { path: '/materials', name: 'materials', component: MaterialsView },
    // 静态段优先于 /materials/:materialId，不会落入详情路由。
    { path: '/materials/new', name: 'material-new', component: MaterialNewView },
    { path: '/materials/:materialId', name: 'material-detail', component: MaterialDetailView },
    { path: '/materials/:materialId/report', name: 'material-report', component: MaterialReportView },
    // 兼容旧链接：三个独立工具页已并入 Review Workspace。
    { path: '/compare', redirect: '/' },
    { path: '/diff', redirect: '/' },
    { path: '/grill', redirect: '/' },
    { path: '/preview', redirect: '/materials/new' },
  ],
})
