// Home/Review/Materials 导航 invariant 检查（真实 SSR 渲染 + 数据状态 + 行为级 setup，不引入测试框架）：
// 新 IA：Home（/）是审查入口与延续，Review Workspace（/reviews/:id）承载一致性/修改效果/质询视角，
// Materials（/materials）是事实源库；二级工作区必须有显式回审查首页（/）的入口。
// 本轮追加：行内「已确认依据 k / n 项」（只来自 preflight-summaries）、未绑定、UModal 删除确认。
// 运行：cd frontend && node scripts/check-materials-nav.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

// 以锚点为中心取一段源码窗口：断言「文案与链接处在同一个区块内」。
const near = (source, anchor, span = 240) => {
  const at = source.indexOf(anchor)
  return at < 0 ? '' : source.slice(Math.max(0, at - span), at + span)
}

// 首页禁用词：旧口号与不可用的能力词都不允许回到文案里。
const bannedWords = ['已满足', '已支撑', '覆盖率', '就绪度', 'Trust Layer', '提交前', '参赛', '评分工具', '不是打分', 'WORKBENCH']

const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const routes = [
  { path: '/', component: { template: '<div />' } },
  { path: '/reviews/new', component: { template: '<div />' } },
  { path: '/reviews/:reviewId', component: { template: '<div />' } },
  { path: '/reviews/:reviewId/consistency', component: { template: '<div />' } },
  { path: '/report', component: { template: '<div />' } },
  { path: '/materials', component: { template: '<div />' } },
  { path: '/materials/new', component: { template: '<div />' } },
  { path: '/materials/:materialId', component: { template: '<div />' } },
]

const summary = {
  id: 'mat_demo_1',
  filename: 'demo.md',
  created_at: '2026-09-16T06:00:00+00:00',
  block_count: 2,
}
const draftSummary = {
  id: 'mat_demo_2',
  filename: 'draft.md',
  created_at: '2026-09-16T05:00:00+00:00',
  block_count: 1,
}
const boundSummary = {
  material_id: 'mat_demo_1',
  filename: 'ev.md',
  created_at: '2026-09-16T06:00:00+00:00',
  block_count: 1,
  bound: true,
  rubric_revision: 1,
  verified_citation_count: 2,
  criteria_total: 2,
  criteria_with_citations: 1,
  criteria_without_citations: 1,
}
const unboundSummary = {
  material_id: 'mat_demo_2',
  filename: 'draft.md',
  created_at: '2026-09-16T05:00:00+00:00',
  block_count: 1,
  bound: false,
  rubric_revision: null,
  verified_citation_count: 0,
  criteria_total: null,
  criteria_with_citations: null,
  criteria_without_citations: null,
}
const detail = {
  id: 'mat_demo_1',
  filename: 'demo.md',
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: 2,
  created_at: '2026-09-16T06:00:00+00:00',
  blocks: [],
}

// 同一页现在读两个只读端点：材料列表与预审摘要；stub 必须按 URL 区分。
function materialsFetch(materialsBody, summariesBody) {
  return async (input) => {
    const url = String(input)
    if (url.includes('/api/v1/preflight-summaries')) return jsonResponse(summariesBody)
    if (url.includes('/api/v1/materials')) return jsonResponse(materialsBody)
    return jsonResponse([])
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  async function context(modulePath, routePath, fetchImpl) {
    globalThis.fetch = fetchImpl
    const module = await server.ssrLoadModule(modulePath)
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push(routePath)
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return { module, app, router }
  }

  // A. 渲染层：Home 审查入口 + Review Workspace 入口 + 页内导航目标。
  // Home 会 fetch 审查列表与材料列表：stub 必须按 URL 返回数组，不能给 `{}`。
  const reviewFixture = {
    id: 'rev_1',
    title: '春季申报',
    rubric_id: 'rub_x',
    rubric_revision: 1,
    created_at: '2026-09-16T06:00:00+00:00',
    updated_at: '2026-09-16T07:00:00+00:00',
  }
  function homeFetch(reviewBody, materialsBody) {
    return async (input) => {
      const url = String(input)
      if (url.endsWith('/api/v1/reviews')) return jsonResponse(reviewBody)
      if (url.includes('/api/v1/materials')) return jsonResponse(materialsBody)
      return jsonResponse([])
    }
  }
  const home = await context('/src/views/HomeView.vue', '/', homeFetch([], [summary, draftSummary]))
  const homeHtml = await renderToString(home.app)
  check(
    'Home 渲染开始新审查 CTA → /reviews/new',
    homeHtml.includes('href="/reviews/new"') && homeHtml.includes('开始新审查'),
  )
  check(
    'Home 渲染添加材料 → /materials/new',
    homeHtml.includes('href="/materials/new"') && homeHtml.includes('添加材料'),
  )
  check('Home 渲染「继续审查」与材料库区块', homeHtml.includes('继续审查') && homeHtml.includes('材料库'))
  check(
    'Home 材料库出口指向 /materials',
    homeHtml.includes('href="/materials"') && homeHtml.includes('打开材料库'),
  )
  const homeSource = readFileSync(new URL('../src/views/HomeView.vue', import.meta.url), 'utf8')
  check(
    'Home 源码不含禁用词',
    bannedWords.every((word) => !homeSource.includes(word)),
    bannedWords.filter((word) => homeSource.includes(word)).join('、'),
  )
  check(
    'Home 审查行链入 Review Workspace（/reviews/:id）',
    homeSource.includes('`/reviews/${review.id}`'),
  )
  check(
    'Home 空态 CTA 为开始第一次审查 → /reviews/new',
    near(homeSource, '还没有进行中的审查').includes('to="/reviews/new"') &&
      near(homeSource, '还没有进行中的审查').includes('开始第一次审查'),
  )

  // ReviewNew：普通用户进入 Review Workspace 的入口（创建成功 replace 到 /reviews/:id）。
  const reviewNew = await context('/src/views/review/ReviewNewView.vue', '/reviews/new', async (input) => {
    const url = String(input)
    if (url.includes('/api/v1/rubrics')) return jsonResponse([])
    if (url.includes('/api/v1/materials')) return jsonResponse([])
    return jsonResponse([])
  })
  const reviewNewHtml = await renderToString(reviewNew.app)
  check('ReviewNew 渲染开始新审查页头与步骤条', reviewNewHtml.includes('开始新审查') && reviewNewHtml.includes('审哪些材料'))
  check('ReviewNew 渲染回审查首页出口', reviewNewHtml.includes('href="/"'))
  const reviewNewSource = readFileSync(new URL('../src/views/review/ReviewNewView.vue', import.meta.url), 'utf8')
  check(
    'ReviewNew 创建成功进入 Review Workspace',
    reviewNewSource.includes('router.replace(`/reviews/${reviewId}`)'),
  )

  // Router：Review Workspace 子视角挂载 + 旧独立工具路由重定向到 Home。
  const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  check(
    '路由挂载 Review Workspace（/reviews/new + /reviews/:reviewId 子视角）',
    routerSource.includes("path: '/reviews/new'") &&
      routerSource.includes("path: '/reviews/:reviewId'") &&
      routerSource.includes("path: 'consistency'") &&
      routerSource.includes("path: 'diff'") &&
      routerSource.includes("path: 'grill'") &&
      routerSource.includes("path: 'members'"),
  )
  check(
    '旧独立工具路由重定向到 Home（/compare /diff /grill）',
    routerSource.includes("path: '/compare', redirect: '/'") &&
      routerSource.includes("path: '/diff', redirect: '/'") &&
      routerSource.includes("path: '/grill', redirect: '/'"),
  )
  check(
    '不再引用已删除的 standalone views（Review* 子视角不算）',
    !routerSource.includes('views/CompareView.vue') &&
      !routerSource.includes('views/DiffView.vue') &&
      !routerSource.includes('views/GrillView.vue') &&
      !routerSource.includes('views/WorkbenchView.vue'),
  )

  // AppShell：品牌 Preflight、两项一级入口（审查/材料）、按 useRoute().path 高亮（含子路由归属）。
  const shell = await context('/src/components/AppShell.vue', '/', async () => jsonResponse([]))
  const shellHtml = await renderToString(shell.app)
  check(
    'AppShell 渲染品牌 Preflight 与两个一级入口（审查/材料），旧工具入口已退役',
    shellHtml.includes('Preflight') &&
      shellHtml.includes('href="/"') &&
      shellHtml.includes('href="/materials"') &&
      !shellHtml.includes('href="/compare"') &&
      !shellHtml.includes('href="/diff"') &&
      !shellHtml.includes('href="/grill"'),
  )
  check('AppShell 不出现 WORKBENCH 品牌', !shellHtml.includes('WORKBENCH'))
  const shellBindings = shell.app.runWithContext(() => shell.module.default.setup({}, { expose() {} }))
  check(
    'AppShell 首页高亮审查入口',
    shellBindings.isActive('/') === true && shellBindings.isActive('/materials') === false,
  )
  const shellReview = await context('/src/components/AppShell.vue', '/reviews/rev_1/consistency', async () =>
    jsonResponse([]),
  )
  const shellReviewBindings = shellReview.app.runWithContext(() =>
    shellReview.module.default.setup({}, { expose() {} }),
  )
  check(
    'AppShell Review 工作区归属审查入口（/reviews/* → 审查）',
    shellReviewBindings.isActive('/') === true && shellReviewBindings.isActive('/materials') === false,
  )
  const shellMaterials = await context('/src/components/AppShell.vue', '/materials/mat_demo_1', async () => jsonResponse([]))
  const shellMaterialsBindings = shellMaterials.app.runWithContext(() =>
    shellMaterials.module.default.setup({}, { expose() {} }),
  )
  check(
    'AppShell 子路由归属一级入口（/materials/:id → 材料）',
    shellMaterialsBindings.isActive('/materials') === true && shellMaterialsBindings.isActive('/') === false,
  )

  const materials = await context(
    '/src/views/MaterialsView.vue',
    '/materials',
    materialsFetch([summary, draftSummary], [boundSummary, unboundSummary]),
  )
  const materialsHtml = await renderToString(materials.app)
  check('/materials 渲染回审查首页出口（按钮文案「审查」）', materialsHtml.includes('href="/"') && materialsHtml.includes('审查'))
  check('/materials 渲染 添加材料 主 CTA', materialsHtml.includes('href="/materials/new"'))

  const materialNew = await context('/src/views/MaterialNewView.vue', '/materials/new', async () => jsonResponse({}))
  const materialNewHtml = await renderToString(materialNew.app)
  check(
    '/materials/new 渲染回审查首页出口与内部导航',
    materialNewHtml.includes('href="/"') && materialNewHtml.includes('审查') && materialNewHtml.includes('href="/materials"'),
  )
  check('/materials/new 初始态含文件输入', materialNewHtml.includes('type="file"'))

  const detailContext = await context('/src/views/MaterialDetailView.vue', '/materials/mat_demo_1', async () =>
    jsonResponse(detail),
  )
  const detailHtml = await renderToString(detailContext.app)
  check('/materials/:id 渲染回审查首页出口（「审查」）', detailHtml.includes('href="/"') && detailHtml.includes('审查'))
  check(
    '/materials/:id 渲染层无保存按钮/无上传控件',
    !detailHtml.includes('保存材料') && !detailHtml.includes('type="file"'),
  )

  // B. 数据层：手动执行 setup，验证真实响应进入页面状态（每个页面用各自的 fetch stub）。
  globalThis.fetch = materialsFetch([summary, draftSummary], [boundSummary, unboundSummary])
  const materialsBindings = materials.app.runWithContext(() => materials.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '/materials 数据装载：2 条 summary 且 loading=false',
    materialsBindings.materials.value.length === 2 &&
      materialsBindings.materials.value[0].id === 'mat_demo_1' &&
      materialsBindings.loading.value === false,
    materialsBindings.materials.value.length,
  )
  check(
    '/materials 行标签：已绑定显示「已确认依据 k / n 项」、未绑定显示未绑定',
    materialsBindings.relationshipLabel({ id: 'mat_demo_1' }) === '已确认依据 1 / 2 项' &&
      materialsBindings.relationshipLabel({ id: 'mat_demo_2' }) === '未绑定',
    materialsBindings.relationshipLabel({ id: 'mat_demo_1' }),
  )

  // Home 数据层：装载审查列表与材料列表（另一次 setup，stub 返回真实形状）。
  globalThis.fetch = homeFetch([reviewFixture], [summary, draftSummary])
  const homeBindings = home.app.runWithContext(() => home.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    'Home 数据装载：1 条审查 + 2 条材料且 loading=false',
    homeBindings.reviews.value.length === 1 &&
      homeBindings.reviews.value[0].id === 'rev_1' &&
      homeBindings.materials.value.length === 2 &&
      homeBindings.loading.value === false,
    homeBindings.reviews.value.length,
  )
  check(
    'Home setup 暴露 reviews 与 materials（行为级可测）',
    Array.isArray(homeBindings.reviews.value) && Array.isArray(homeBindings.materials.value),
  )

  globalThis.fetch = async () => jsonResponse(detail)
  const detailBindings = detailContext.app.runWithContext(() => detailContext.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '/materials/:id 按路由参数装载材料',
    detailBindings.material.value?.id === 'mat_demo_1' && detailBindings.loading.value === false,
  )

  const missing = await context('/src/views/MaterialDetailView.vue', '/materials/mat_missing', async () =>
    jsonResponse({ code: 'material_not_found', message: '找不到该材料', details: [] }, 404),
  )
  const missingBindings = missing.app.runWithContext(() => missing.module.default.setup({}, { expose() {} }))
  await flush()
  check('未知 ID 进入 notFound 状态（不 fallback）', missingBindings.notFound.value === true && missingBindings.material.value === null)

  // C. 行内删除：确认走 UModal；204 移除该行，404 视为已不存在，其余失败保留该行。
  async function deleteContext(deleteResponse) {
    const calls = []
    const mounted = await context('/src/views/MaterialsView.vue', '/materials', async (input, init) => {
      const url = String(input)
      const method = (init && init.method) || 'GET'
      calls.push({ url, method })
      if (method === 'DELETE') return deleteResponse(url)
      return materialsFetch([summary, draftSummary], [boundSummary, unboundSummary])(input)
    })
    const bindings = mounted.app.runWithContext(() => mounted.module.default.setup({}, { expose() {} }))
    await flush()
    return { bindings, calls }
  }

  const okDelete = await deleteContext(async () => new Response(null, { status: 204 }))
  okDelete.bindings.requestDelete(okDelete.bindings.materials.value[0])
  check(
    '删除确认只挂起该行，不立即发请求',
    okDelete.bindings.pendingDelete.value?.id === 'mat_demo_1' &&
      okDelete.calls.every((call) => call.method !== 'DELETE'),
  )
  await okDelete.bindings.confirmDelete()
  await flush()
  check(
    '确认后 DELETE 204：该行与摘要一起移除、确认态清空',
    okDelete.calls.some((call) => call.method === 'DELETE' && call.url === '/api/v1/materials/mat_demo_1') &&
      okDelete.bindings.materials.value.length === 1 &&
      okDelete.bindings.materials.value[0].id === 'mat_demo_2' &&
      okDelete.bindings.summaries.value.length === 1 &&
      okDelete.bindings.pendingDelete.value === null,
    okDelete.bindings.materials.value.length,
  )

  const goneDelete = await deleteContext(async () =>
    jsonResponse({ code: 'material_not_found', message: '找不到该材料', details: [] }, 404),
  )
  goneDelete.bindings.requestDelete(goneDelete.bindings.materials.value[0])
  await goneDelete.bindings.confirmDelete()
  await flush()
  check(
    'DELETE 404 视为该材料已不存在：同样移除该行且不报错',
    goneDelete.bindings.materials.value.length === 1 &&
      goneDelete.bindings.materials.value[0].id === 'mat_demo_2' &&
      goneDelete.bindings.deleteError.value === '',
  )

  const failedDelete = await deleteContext(async () =>
    jsonResponse({ code: 'internal_error', message: '服务器内部错误', details: [] }, 500),
  )
  failedDelete.bindings.requestDelete(failedDelete.bindings.materials.value[1])
  await failedDelete.bindings.confirmDelete()
  await flush()
  check(
    '删除失败保留该行并显示错误',
    failedDelete.bindings.materials.value.length === 2 &&
      failedDelete.bindings.deleteError.value.includes('服务器内部错误') &&
      failedDelete.bindings.pendingDelete.value?.id === 'mat_demo_2',
    failedDelete.bindings.deleteError.value,
  )

  // D. 源码层：预览态与列表行的导航目标（SSR 初始态无法覆盖的状态）。
  const newSource = readFileSync(new URL('../src/views/MaterialNewView.vue', import.meta.url), 'utf8')
  const materialsSource = readFileSync(new URL('../src/views/MaterialsView.vue', import.meta.url), 'utf8')
  check('预览态仍有回审查首页出口（「审查」）与 Materials 面包屑', newSource.includes('>审查</UButton>') && newSource.includes('to="/materials"'))
  check('列表行链接到各自详情', materialsSource.includes(':to="`/materials/${item.id}`"'))
  check(
    '/materials 不再使用「条要求已有关联」旧措辞',
    !materialsSource.includes('条要求已有关联') && materialsSource.includes('已确认依据'),
  )
  check(
    '删除确认用 UModal，不用 window.confirm',
    materialsSource.includes('<UModal') && !materialsSource.includes('window.confirm'),
  )
  check(
    'Materials 源码不含禁用词',
    ['已满足', '已支撑', '覆盖率', '就绪度', '分数'].every((word) => !materialsSource.includes(word)),
    ['已满足', '已支撑', '覆盖率', '就绪度', '分数'].filter((word) => materialsSource.includes(word)).join('、'),
  )
  check(
    '拖拽区高度缩短且未加假模块',
    /border-dashed px-6 py-10/.test(newSource) && !newSource.includes('py-16'),
  )
} finally {
  await server.close()
}

let failed = 0
for (const item of results) {
  if (!item.ok) failed += 1
  console.log(`${item.ok ? 'PASS' : 'FAIL'} ${item.name}${item.detail ? ' | ' + item.detail : ''}`)
}
console.log(`SUMMARY: ${results.length - failed}/${results.length} passed`)
if (failed > 0) process.exit(1)
