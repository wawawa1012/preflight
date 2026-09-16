// Materials 导航 invariant 检查（真实 SSR 渲染 + 数据状态，不引入测试框架）：
// 二级工作区必须有显式回 Workbench 的入口；并核对 Golden Journey 的关键链接与数据。
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
const detail = {
  id: 'mat_demo_1',
  filename: 'demo.md',
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: 2,
  created_at: '2026-09-16T06:00:00+00:00',
  blocks: [],
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
  const workbench = await context('/src/views/WorkbenchView.vue', '/', async () => jsonResponse({}))
  const workbenchHtml = await renderToString(workbench.app)
  check(
    'Workbench 渲染出 Materials 两个入口',
    workbenchHtml.includes('href="/materials"') && workbenchHtml.includes('href="/materials/new"'),
  )

  const materials = await context('/src/views/MaterialsView.vue', '/materials', async () => jsonResponse([summary]))
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
  globalThis.fetch = async () => jsonResponse([summary])
  const materialsBindings = materials.app.runWithContext(() => materials.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '/materials 数据装载：1 条 summary 且 loading=false',
    materialsBindings.materials.value.length === 1 &&
      materialsBindings.materials.value[0].id === 'mat_demo_1' &&
      materialsBindings.loading.value === false,
    materialsBindings.materials.value.length,
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

  // C. 源码层：预览态与列表行的导航目标（SSR 初始态无法覆盖的状态）。
  const newSource = readFileSync(new URL('../src/views/MaterialNewView.vue', import.meta.url), 'utf8')
  const materialsSource = readFileSync(new URL('../src/views/MaterialsView.vue', import.meta.url), 'utf8')
  check('预览态仍有 Workbench 出口与 Materials 面包屑', newSource.includes('Workbench') && newSource.includes('to="/materials"'))
  check('列表行链接到各自详情', materialsSource.includes(':to="`/materials/${item.id}`"'))
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
