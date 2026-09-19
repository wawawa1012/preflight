// Materials 导航 invariant 检查（真实 SSR 渲染 + 数据状态 + 行为级 setup，不引入测试框架）：
// 二级工作区必须有显式回 Workbench 的入口；并核对 Golden Journey 的关键链接与数据。
// 本轮追加：行内「已确认依据 k / n 项」（只来自 preflight-summaries）、未绑定、UModal 删除确认。
// 本轮修订：首页主 CTA 改为「开始审查」大卡 → /materials/new；新增 AppShell 一级导航检查（品牌 Preflight）。
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
  { path: '/report', component: { template: '<div />' } },
  { path: '/materials', component: { template: '<div />' } },
  { path: '/materials/new', component: { template: '<div />' } },
  { path: '/materials/:materialId', component: { template: '<div />' } },
  { path: '/compare', component: { template: '<div />' } },
  { path: '/diff', component: { template: '<div />' } },
  { path: '/grill', component: { template: '<div />' } },
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
    return jsonResponse([])
  })
  const workbenchHtml = await renderToString(workbench.app)
  check(
    'Workbench 渲染开始审查 CTA → /materials/new',
    workbenchHtml.includes('href="/materials/new"') && workbenchHtml.includes('开始审查'),
  )
  check('Workbench 渲染「最近审查」区块', workbenchHtml.includes('最近审查'))
  const workbenchSource = readFileSync(new URL('../src/views/WorkbenchView.vue', import.meta.url), 'utf8')
  check(
    'Workbench 源码不含禁用词',
    bannedWords.every((word) => !workbenchSource.includes(word)),
    bannedWords.filter((word) => workbenchSource.includes(word)).join('、'),
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
  // 主 CTA：一张大卡承担「开始审查」→ /materials/new；旧主按钮「添加材料」退役。
  check(
    '主 CTA「开始审查」固定指向 /materials/new',
    near(workbenchSource, '上传材料并按标准检查').includes('to="/materials/new"') &&
      near(workbenchSource, '上传材料并按标准检查').includes('开始审查'),
  )
  check(
    '空态 CTA 为「开始审查」→ /materials/new',
    near(workbenchSource, '还没有材料').includes('to="/materials/new"') &&
      near(workbenchSource, '还没有材料').includes('开始审查'),
  )
  check(
    '旧主按钮「添加材料」与 startTarget 已退役',
    !workbenchSource.includes('添加材料') && !workbenchSource.includes('startTarget'),
  )
  check(
    'Workbench 不再出现旧标题与旧副标题',
    !workbenchSource.includes('WORKBENCH') &&
      !workbenchSource.includes('让关键结论回到原文') &&
      !workbenchSource.includes('不是打分'),
  )
  check('Workbench 新标题为「让重要结论有据可查」', workbenchSource.includes('让重要结论有据可查'))
  check(
    '行链接：已绑定进报告页、未绑定进详情',
    workbenchSource.includes('item.bound ? `/materials/${item.material_id}/report` : `/materials/${item.material_id}`'),
  )

  // AppShell：品牌 Preflight、五项一级入口、按 useRoute().path 高亮（含子路由归属）。
  const shell = await context('/src/components/AppShell.vue', '/compare', async () => jsonResponse([]))
  const shellHtml = await renderToString(shell.app)
  check(
    'AppShell 渲染品牌 Preflight 与五个一级入口',
    shellHtml.includes('Preflight') &&
      ['/', '/compare', '/diff', '/grill', '/materials'].every((path) => shellHtml.includes(`href="${path}"`)),
  )
  check('AppShell 不出现 WORKBENCH 品牌', !shellHtml.includes('WORKBENCH'))
  const shellBindings = shell.app.runWithContext(() => shell.module.default.setup({}, { expose() {} }))
  check(
    'AppShell 按 useRoute().path 高亮当前项',
    shellBindings.isActive('/compare') === true &&
      shellBindings.isActive('/') === false &&
      shellBindings.isActive('/materials') === false,
  )
  const shellMaterials = await context('/src/components/AppShell.vue', '/materials/mat_demo_1', async () => jsonResponse([]))
  const shellMaterialsBindings = shellMaterials.app.runWithContext(() =>
    shellMaterials.module.default.setup({}, { expose() {} }),
  )
  check(
    'AppShell 子路由归属一级入口（/materials/:id → 材料）',
    shellMaterialsBindings.isActive('/materials') === true && shellMaterialsBindings.isActive('/diff') === false,
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
    '首页 setup 暴露 loadSummaries 与 criteriaLabel（行为级可测）',
    typeof workbenchBindings.loadSummaries === 'function' && typeof workbenchBindings.criteriaLabel === 'function',
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
