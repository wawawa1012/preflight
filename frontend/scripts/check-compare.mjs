// Leaf B 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// /compare 两材料对照：打开页面只 GET 材料列表、零 POST（绝不自动扫描材料库）；
// 同一份材料不发送且就地报错；两个不同 id 才 POST /api/v1/comparisons（body 只含两个选中 id）；
// 空 findings 是合法结果；引用点开 Drawer（按需 GET 两份材料 blocks，位置按 locatorLabel）。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-compare.mjs
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

const viewSource = readFileSync(new URL('../src/views/CompareView.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
const workbenchSource = readFileSync(new URL('../src/views/WorkbenchView.vue', import.meta.url), 'utf8')

const materialsFixture = [
  { id: 'mat_a', filename: 'alpha.md', created_at: '2026-09-16T06:00:00+00:00', block_count: 2 },
  { id: 'mat_b', filename: 'beta.md', created_at: '2026-09-16T05:00:00+00:00', block_count: 2 },
]
const blocksA = [
  { id: 'blk_a1', document_id: 'mat_a', ordinal: 1, text: '实验组准确率 90%。', locator: { kind: 'line', index: 3, block_index: 1 } },
]
const blocksB = [
  { id: 'blk_b1', document_id: 'mat_b', ordinal: 1, text: '实验组准确率 85%。', locator: { kind: 'line', index: 5, block_index: 1 } },
]
const citationA = { block_id: 'blk_a1', line_number: 3, quote: '准确率 90%', start: 4, end: 11, value: '90%', unit: '%' }
const citationB = { block_id: 'blk_b1', line_number: 5, quote: '准确率 85%', start: 4, end: 11, value: '85%', unit: '%' }
const finding = {
  material_id: 'mat_a',
  kind: 'numeric_inconsistency',
  measure: '准确率',
  values: ['90%', '85%'],
  searched_block_count: 2,
  searched_statement_count: 2,
  explanation: '两份材料在同一度量词下给出不同数值。',
  citations: [citationA, citationB],
}
const compareBody = {
  material_id_a: 'mat_a',
  material_id_b: 'mat_b',
  filename_a: 'alpha.md',
  filename_b: 'beta.md',
  findings: [finding],
}

// 请求记录 + 可注入的 comparisons 响应；stub 按 URL 区分材料列表与单份材料详情。
const state = { calls: [], posts: [], compareStatus: 200, compareBody }
const resetState = () => {
  state.calls = []
  state.posts = []
  state.compareStatus = 200
  state.compareBody = compareBody
}
const detailResponse = (id, filename, blocks) => ({
  id,
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: blocks.length,
  created_at: '2026-09-16T06:00:00+00:00',
  blocks,
})
function stubFetch() {
  return async (input, init = {}) => {
    const url = String(input)
    const method = (init && init.method) || 'GET'
    state.calls.push({ url, method })
    if (method === 'POST') {
      if (url.endsWith('/api/v1/comparisons')) {
        state.posts.push({ url, body: init.body })
        return jsonResponse(state.compareBody, state.compareStatus)
      }
      return jsonResponse({ code: 'unexpected_write', message: 'unexpected write', details: [] }, 500)
    }
    if (url.endsWith('/api/v1/materials/mat_a')) return jsonResponse(detailResponse('mat_a', 'alpha.md', blocksA))
    if (url.endsWith('/api/v1/materials/mat_b')) return jsonResponse(detailResponse('mat_b', 'beta.md', blocksB))
    if (url.endsWith('/api/v1/materials')) return jsonResponse(materialsFixture)
    return jsonResponse([], 200)
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const routes = [
    { path: '/compare', component: { template: '<div />' } },
    { path: '/materials', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
  ]
  async function context() {
    const module = await server.ssrLoadModule('/src/views/CompareView.vue')
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/compare')
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return { module, app }
  }
  const locatorModule = await server.ssrLoadModule('/src/utils/locatorLabel.ts')

  // A. 打开页面：SSR 只画页面骨架（数据来自 setup 里的 GET）；零 POST、零 comparisons 请求。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check('SSR 画出 /compare 页面骨架与两个出口', initialHtml.includes('两材料对照') && initialHtml.includes('href="/materials"') && initialHtml.includes('href="/"'))
  check(
    '打开页面零 POST（不自动对照）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/comparisons', state.calls.every((call) => !call.url.includes('/api/v1/comparisons')))
  check(
    '两个材料下拉绑定两个 id ref，选项来自材料列表',
    (viewSource.match(/<select/g) || []).length === 2 &&
      viewSource.includes('v-model="materialIdA"') &&
      viewSource.includes('v-model="materialIdB"') &&
      viewSource.includes('<option v-for="item in materials"'),
  )

  // B. setup 行为：装载材料列表；同一份材料不发；两份不同才 POST 一次，body 只含两个选中 id。
  resetState()
  globalThis.fetch = stubFetch()
  const view = await context()
  const bindings = view.app.runWithContext(() => view.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '材料下拉来自 GET /api/v1/materials（2 条）',
    bindings.materials.value.length === 2 &&
      bindings.materials.value[0].id === 'mat_a' &&
      bindings.materials.value[1].filename === 'beta.md' &&
      bindings.loading.value === false,
    bindings.materials.value.length,
  )
  check('装载后仍零 POST', state.posts.length === 0, `posts=${state.posts.length}`)

  bindings.materialIdA.value = 'mat_a'
  bindings.materialIdB.value = 'mat_a'
  await bindings.compare()
  check('同一份材料不发送 POST', state.posts.length === 0, `posts=${state.posts.length}`)
  check('同一份材料就地报错', bindings.compareError.value.includes('不能对照同一份材料'), bindings.compareError.value)
  check('同一份材料不产生结果', bindings.result.value === null)

  bindings.materialIdB.value = 'mat_b'
  await bindings.compare()
  check(
    '两个不同 id 只 POST 一次 /api/v1/comparisons',
    state.posts.length === 1 && state.posts[0].url.endsWith('/api/v1/comparisons'),
    state.posts.map((post) => post.url).join(' | '),
  )
  check(
    'POST body 只含两个显式选中的 id',
    state.posts.length === 1 &&
      JSON.stringify(JSON.parse(state.posts[0].body)) === JSON.stringify({ material_id_a: 'mat_a', material_id_b: 'mat_b' }),
    state.posts[0] ? state.posts[0].body : '无 POST',
  )
  check(
    '结果带入两份文件名与 findings',
    bindings.result.value?.filename_a === 'alpha.md' &&
      bindings.result.value?.filename_b === 'beta.md' &&
      bindings.result.value?.findings.length === 1 &&
      bindings.compareError.value === '',
  )
  check('对照全程只有这一个写请求（材料只读）', state.calls.filter((call) => call.method !== 'GET').length === 1)
  check(
    'finding 措辞只有数值不一致 / 待人工判断',
    bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
  )

  // C. 空 findings 是合法结果：不报错、给出空态说明。
  resetState()
  state.compareBody = { ...compareBody, findings: [] }
  globalThis.fetch = stubFetch()
  const emptyView = await context()
  const emptyBindings = emptyView.app.runWithContext(() => emptyView.module.default.setup({}, { expose() {} }))
  await flush()
  emptyBindings.materialIdA.value = 'mat_a'
  emptyBindings.materialIdB.value = 'mat_b'
  await emptyBindings.compare()
  check(
    '空 findings 合法：结果对象仍在且不报错',
    emptyBindings.compareError.value === '' && emptyBindings.result.value !== null && emptyBindings.result.value.findings.length === 0,
    emptyBindings.compareError.value,
  )
  check('空结果走空态文案', emptyBindings.emptyResult.value === true && viewSource.includes('空结果合法'))

  // D. 引用点开 Drawer：按需 GET 两份材料 blocks，位置用 locatorLabel。
  resetState()
  globalThis.fetch = stubFetch()
  const drawerView = await context()
  const drawerBindings = drawerView.app.runWithContext(() => drawerView.module.default.setup({}, { expose() {} }))
  await flush()
  drawerBindings.materialIdA.value = 'mat_a'
  drawerBindings.materialIdB.value = 'mat_b'
  await drawerBindings.compare()
  const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_[ab]$/.test(call.url))
  check('对照本身不取原文 blocks', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  await drawerBindings.openCitation(citationB)
  check(
    '点引用后按需 GET 两份材料的 blocks',
    detailCalls().some((call) => call.url.endsWith('/mat_a')) && detailCalls().some((call) => call.url.endsWith('/mat_b')),
    detailCalls().map((call) => call.url).join(' | '),
  )
  check(
    'Drawer 打开并定位到该引用',
    drawerBindings.drawerOpen.value === true &&
      JSON.stringify(drawerBindings.highlight.value) === JSON.stringify({ line_number: 5, start: 4, end: 11 }),
  )
  check(
    'Drawer 取到引用所在 Block，位置按 locatorLabel 说',
    drawerBindings.drawerBlock.value?.id === 'blk_b1' &&
      drawerBindings.rowLocation('blk_b1', 5) === locatorModule.locatorLabel({ kind: 'line', index: 5 }),
    drawerBindings.rowLocation('blk_b1', 5),
  )

  // E. 源码层：单一 POST 入口、路由、导航入口、措辞纪律。
  check(
    'CompareView 只 POST /api/v1/comparisons',
    viewSource.includes("method: 'POST'") && viewSource.includes("'/api/v1/comparisons'") && !viewSource.includes('repair-suggestions'),
  )
  check(
    'CompareView 源码不含禁用词',
    ['已满足', '分数'].every((word) => !viewSource.includes(word)),
    ['已满足', '分数'].filter((word) => viewSource.includes(word)).join('、'),
  )
  check('CompareView 明说不扫描整个材料库', viewSource.includes('不会自动扫描材料库'))
  check('路由新增一条 /compare', routerSource.includes("path: '/compare'") && routerSource.includes('CompareView'))
  check('Workbench 有指向 /compare 的低权重入口', workbenchSource.includes('to="/compare"'))
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
