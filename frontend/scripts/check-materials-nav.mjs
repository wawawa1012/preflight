// Materials 导航 invariant 检查（真实 SSR 渲染 + 数据状态 + 行为级 setup，不引入测试框架）：
// 二级工作区必须有显式回 Workbench 的入口；并核对 Golden Journey 的关键链接与数据。
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

const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const routes = [
  { path: '/', component: { template: '<div />' } },
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

  // A. 渲染层：显式回 Workbench 出口 + 页内导航目标。
  // 首页会 fetch 预审摘要列表：stub 必须按 URL 返回数组，不能给 `{}`。
  const workbench = await context('/src/views/WorkbenchView.vue', '/', async (input) => {
    const url = String(input)
    if (url.includes('/api/v1/preflight-summaries')) return jsonResponse([])
    if (url.includes('/api/v1/health')) return jsonResponse({ status: 'ok', contract_version: '0.1.0' })
    return jsonResponse([])
  })
  const workbenchHtml = await renderToString(workbench.app)
  check(
    'Workbench 渲染出 Materials 两个入口',
    workbenchHtml.includes('href="/materials"') && workbenchHtml.includes('href="/materials/new"'),
  )
  const workbenchSource = readFileSync(new URL('../src/views/WorkbenchView.vue', import.meta.url), 'utf8')
  check(
    'Workbench 源码不含禁用词',
    ['已满足', '已支撑', '覆盖率', '就绪度', 'Trust Layer'].every((word) => !workbenchSource.includes(word)),
    ['已满足', '已支撑', '覆盖率', '就绪度', 'Trust Layer'].filter((word) => workbenchSource.includes(word)).join('、'),
  )
  check(
    'Workbench 模板含「已确认依据 k / n 项」与范围句',
    workbenchSource.includes('已确认依据') && workbenchSource.includes('当前范围尚未发现引用'),
  )
  check(
    'Workbench 不再使用「条要求已有关联」旧措辞',
    !workbenchSource.includes('条要求已有关联'),
  )
  check(
    'Workbench 未绑定行显示未绑定',
    workbenchSource.includes('未绑定') && workbenchSource.includes('criteriaLabel'),
  )
  // 主按钮「开始预检」：按摘要决定目标（有已绑定材料就进报告页，否则去添加材料）。
  // 锚点用按钮自身的 icon 属性，避免命中 <script> 里的同名注释。
  const heroButtonBlock = (() => {
    const at = workbenchSource.indexOf('i-lucide-upload">开始预检')
    return at < 0 ? '' : workbenchSource.slice(Math.max(0, at - 200), at)
  })()
  check(
    '主按钮「开始预检」绑定动态目标（startTarget）',
    heroButtonBlock.includes(':to="startTarget"'),
    heroButtonBlock.slice(-120),
  )
  check(
    '主按钮不再硬编码 /materials/new',
    !heroButtonBlock.includes('to="/materials/new"'),
  )
  check(
    '行链接：已绑定进报告页、未绑定进详情',
    workbenchSource.includes('item.bound ? `/materials/${item.material_id}/report` : `/materials/${item.material_id}`'),
  )

  const materials = await context(
    '/src/views/MaterialsView.vue',
    '/materials',
    materialsFetch([summary, draftSummary], [boundSummary, unboundSummary]),
  )
  const materialsHtml = await renderToString(materials.app)
  check('/materials 渲染 Workbench 出口', materialsHtml.includes('href="/"') && materialsHtml.includes('Workbench'))
  check('/materials 渲染 添加材料 主 CTA', materialsHtml.includes('href="/materials/new"'))

  const materialNew = await context('/src/views/MaterialNewView.vue', '/materials/new', async () => jsonResponse({}))
  const materialNewHtml = await renderToString(materialNew.app)
  check(
    '/materials/new 渲染 Workbench 出口与内部导航',
    materialNewHtml.includes('href="/"') && materialNewHtml.includes('Workbench') && materialNewHtml.includes('href="/materials"'),
  )
  check('/materials/new 初始态含文件输入', materialNewHtml.includes('type="file"'))

  const detailContext = await context('/src/views/MaterialDetailView.vue', '/materials/mat_demo_1', async () =>
    jsonResponse(detail),
  )
  const detailHtml = await renderToString(detailContext.app)
  check('/materials/:id 渲染 Workbench 出口', detailHtml.includes('href="/"') && detailHtml.includes('Workbench'))
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

  // 首页数据层：装载一条已绑定摘要（另一次 mount，stub 返回真实形状）。
  const workbenchData = await context('/src/views/WorkbenchView.vue', '/', async (input) => {
    const url = String(input)
    if (url.includes('/api/v1/preflight-summaries')) return jsonResponse([boundSummary])
    return jsonResponse([])
  })
  const workbenchBindings = workbenchData.app.runWithContext(() =>
    workbenchData.module.default.setup({}, { expose() {} }),
  )
  await flush()
  check(
    '首页装载已绑定摘要并显示计数',
    workbenchBindings.summaries.value.length === 1 &&
      workbenchBindings.summaries.value[0].filename === 'ev.md' &&
      workbenchBindings.summaries.value[0].verified_citation_count === 2,
    workbenchBindings.summaries.value.length,
  )
  check(
    '首页行标签为「已确认依据 k / n 项」，标准不可用时为未评估',
    workbenchBindings.criteriaLabel(boundSummary) === '已确认依据 1 / 2 项' &&
      workbenchBindings.criteriaLabel({ ...boundSummary, criteria_total: null, criteria_with_citations: null }) === '未评估',
    workbenchBindings.criteriaLabel(boundSummary),
  )
  check(
    '主按钮目标：有已绑定材料时进第一条已绑定的报告页',
    workbenchBindings.startTarget.value === '/materials/mat_demo_1/report',
    workbenchBindings.startTarget.value,
  )
  const unboundOnly = await context('/src/views/WorkbenchView.vue', '/', async (input) =>
    String(input).includes('/api/v1/preflight-summaries') ? jsonResponse([unboundSummary]) : jsonResponse([]),
  )
  const unboundBindings = unboundOnly.app.runWithContext(() => unboundOnly.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '主按钮目标：没有已绑定材料时回 /materials/new',
    unboundBindings.startTarget.value === '/materials/new',
    unboundBindings.startTarget.value,
  )
  const mixedOrder = await context('/src/views/WorkbenchView.vue', '/', async (input) =>
    String(input).includes('/api/v1/preflight-summaries') ? jsonResponse([unboundSummary, boundSummary]) : jsonResponse([]),
  )
  const mixedBindings = mixedOrder.app.runWithContext(() => mixedOrder.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '主按钮目标：跳过未绑定，取摘要顺序里第一条已绑定材料',
    mixedBindings.startTarget.value === '/materials/mat_demo_1/report',
    mixedBindings.startTarget.value,
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
  check('预览态仍有 Workbench 出口与 Materials 面包屑', newSource.includes('Workbench') && newSource.includes('to="/materials"'))
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
