// I11 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// /diff 修改效果对照：打开页面只 GET 材料列表、零 POST（绝不自动扫描材料库）；
// 同一份材料不发送且就地报错；两个不同 id 才 POST /api/v1/diffs（body 只含 before/after 两个 id）；
// 三组固定 已解决 / 仍存在 / 新增，都渲染条数，空组是合法结果；
// 引用点开 Drawer（按需 GET 两份材料 blocks，位置按 locatorLabel）。
// /diff 尚未挂进 router/index.ts（集成方负责）：本脚本在本地注册 /diff 路由后再 SSR。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-diff.mjs
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

const viewSource = readFileSync(new URL('../src/views/DiffView.vue', import.meta.url), 'utf8')

const materialsFixture = [
  { id: 'mat_before', filename: 'draft.md', created_at: '2026-09-18T06:00:00+00:00', block_count: 2 },
  { id: 'mat_after', filename: 'revised.md', created_at: '2026-09-19T06:00:00+00:00', block_count: 1 },
]
const blocksBefore = [
  { id: 'blk_before1', document_id: 'mat_before', ordinal: 1, text: '实验组准确率 88%。', locator: { kind: 'line', index: 3, block_index: 1 } },
]
const blocksAfter = [
  { id: 'blk_after1', document_id: 'mat_after', ordinal: 1, text: '实验组准确率 93%。', locator: { kind: 'line', index: 5, block_index: 1 } },
]
const citationBefore = { block_id: 'blk_before1', line_number: 3, quote: '准确率 88%', start: 4, end: 11, value: '88%', unit: '%' }
const citationAfter = { block_id: 'blk_after1', line_number: 5, quote: '准确率 93%', start: 4, end: 11, value: '93%', unit: '%' }
const resolvedFinding = {
  material_id: 'mat_before',
  kind: 'numeric_inconsistency',
  measure: '准确率',
  values: ['88%', '93%'],
  searched_block_count: 2,
  searched_statement_count: 2,
  explanation: '修改前同一度量词下数值不一致，修改后不再出现。',
  citations: [citationBefore],
}
const newFinding = {
  material_id: 'mat_after',
  kind: 'numeric_inconsistency',
  measure: '准确率',
  values: ['93%', '96%'],
  searched_block_count: 1,
  searched_statement_count: 2,
  explanation: '修改后新出现的同度量词数值不一致。',
  citations: [citationAfter],
}
const diffBody = {
  material_id_before: 'mat_before',
  material_id_after: 'mat_after',
  filename_before: 'draft.md',
  filename_after: 'revised.md',
  resolved: [resolvedFinding],
  unchanged: [],
  new: [newFinding],
}

// 请求记录 + 可注入的 diffs 响应；stub 按 URL 区分材料列表与单份材料详情。
const state = { calls: [], posts: [], diffBody }
const resetState = () => {
  state.calls = []
  state.posts = []
  state.diffBody = diffBody
}
const detailResponse = (id, filename, blocks) => ({
  id,
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: blocks.length,
  created_at: '2026-09-18T06:00:00+00:00',
  blocks,
})
function stubFetch() {
  return async (input, init = {}) => {
    const url = String(input)
    const method = (init && init.method) || 'GET'
    state.calls.push({ url, method })
    if (method === 'POST') {
      if (url.endsWith('/api/v1/diffs')) {
        state.posts.push({ url, body: init.body })
        return jsonResponse(state.diffBody)
      }
      return jsonResponse({ code: 'unexpected_write', message: 'unexpected write', details: [] }, 500)
    }
    if (url.endsWith('/api/v1/materials/mat_before')) return jsonResponse(detailResponse('mat_before', 'draft.md', blocksBefore))
    if (url.endsWith('/api/v1/materials/mat_after')) return jsonResponse(detailResponse('mat_after', 'revised.md', blocksAfter))
    if (url.endsWith('/api/v1/materials')) return jsonResponse(materialsFixture)
    return jsonResponse([], 200)
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  // /diff 尚未挂进 router/index.ts：本地注册一条，只服务本检查。
  const routes = [
    { path: '/diff', component: { template: '<div />' } },
    { path: '/materials', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
  ]
  async function context() {
    const module = await server.ssrLoadModule('/src/views/DiffView.vue')
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/diff')
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return { module, app }
  }
  const locatorModule = await server.ssrLoadModule('/src/utils/locatorLabel.ts')

  // A. 打开页面：SSR 只画页面骨架（数据来自 setup 里的 GET）；零 POST、零 diffs 请求。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出 /diff 页面骨架与两个出口',
    initialHtml.includes('修改效果对照') && initialHtml.includes('href="/materials"') && initialHtml.includes('href="/"'),
  )
  check(
    '打开页面零 POST（不自动对照）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/diffs', state.calls.every((call) => !call.url.includes('/api/v1/diffs')))
  check(
    '两个材料下拉绑定 修改前/修改后 两个 id ref，选项来自材料列表',
    (viewSource.match(/<select/g) || []).length === 2 &&
      viewSource.includes('v-model="materialIdBefore"') &&
      viewSource.includes('v-model="materialIdAfter"') &&
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
      bindings.materials.value[0].id === 'mat_before' &&
      bindings.materials.value[1].filename === 'revised.md' &&
      bindings.loading.value === false,
    bindings.materials.value.length,
  )
  check('装载后仍零 POST', state.posts.length === 0, `posts=${state.posts.length}`)

  bindings.materialIdBefore.value = 'mat_before'
  bindings.materialIdAfter.value = 'mat_before'
  await bindings.compare()
  check('同一份材料不发送 POST', state.posts.length === 0, `posts=${state.posts.length}`)
  check('同一份材料就地报错', bindings.diffError.value.includes('不能对照同一份材料'), bindings.diffError.value)
  check('同一份材料不产生结果', bindings.result.value === null)

  bindings.materialIdAfter.value = 'mat_after'
  await bindings.compare()
  check(
    '两个不同 id 只 POST 一次 /api/v1/diffs',
    state.posts.length === 1 && state.posts[0].url.endsWith('/api/v1/diffs'),
    state.posts.map((post) => post.url).join(' | '),
  )
  check(
    'POST body 只含 before/after 两个显式选中的 id',
    state.posts.length === 1 &&
      JSON.stringify(JSON.parse(state.posts[0].body)) ===
        JSON.stringify({ material_id_before: 'mat_before', material_id_after: 'mat_after' }),
    state.posts[0] ? state.posts[0].body : '无 POST',
  )
  check(
    '结果带入两份文件名与三组（resolved 1 / unchanged 0 / new 1）',
    bindings.result.value?.filename_before === 'draft.md' &&
      bindings.result.value?.filename_after === 'revised.md' &&
      bindings.result.value?.resolved.length === 1 &&
      bindings.result.value?.unchanged.length === 0 &&
      bindings.result.value?.new.length === 1 &&
      bindings.diffError.value === '',
  )
  check(
    '三组固定为 已解决 / 仍存在 / 新增 且都渲染条数',
    JSON.stringify(bindings.groups.value.map((group) => group.title)) === JSON.stringify(['已解决', '仍存在', '新增']) &&
      bindings.groups.value.every((group) => typeof group.findings.length === 'number') &&
      viewSource.includes('group.findings.length'),
  )
  check('对照全程只有这一个写请求（材料只读）', state.calls.filter((call) => call.method !== 'GET').length === 1)
  check(
    'finding 措辞只有数值不一致 / 待人工判断',
    bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
  )

  // C. 空三组是合法结果：不报错、给出空态说明，且三组仍然渲染。
  resetState()
  state.diffBody = { ...diffBody, resolved: [], unchanged: [], new: [] }
  globalThis.fetch = stubFetch()
  const emptyView = await context()
  const emptyBindings = emptyView.app.runWithContext(() => emptyView.module.default.setup({}, { expose() {} }))
  await flush()
  emptyBindings.materialIdBefore.value = 'mat_before'
  emptyBindings.materialIdAfter.value = 'mat_after'
  await emptyBindings.compare()
  check(
    '空三组合法：结果对象仍在且不报错',
    emptyBindings.diffError.value === '' &&
      emptyBindings.result.value !== null &&
      emptyBindings.result.value.resolved.length === 0 &&
      emptyBindings.result.value.unchanged.length === 0 &&
      emptyBindings.result.value.new.length === 0,
    emptyBindings.diffError.value,
  )
  check(
    '空结果走空态文案且空组也渲染',
    emptyBindings.emptyResult.value === true &&
      emptyBindings.groups.value.length === 3 &&
      viewSource.includes('空结果合法') &&
      viewSource.includes('本组为空'),
  )

  // D. 引用点开 Drawer：按需 GET 两份材料 blocks，位置用 locatorLabel。
  resetState()
  globalThis.fetch = stubFetch()
  const drawerView = await context()
  const drawerBindings = drawerView.app.runWithContext(() => drawerView.module.default.setup({}, { expose() {} }))
  await flush()
  drawerBindings.materialIdBefore.value = 'mat_before'
  drawerBindings.materialIdAfter.value = 'mat_after'
  await drawerBindings.compare()
  const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_(before|after)$/.test(call.url))
  check('对照本身不取原文 blocks', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  await drawerBindings.openCitation(citationAfter)
  check(
    '点引用后按需 GET 两份材料的 blocks',
    detailCalls().some((call) => call.url.endsWith('/mat_before')) && detailCalls().some((call) => call.url.endsWith('/mat_after')),
    detailCalls().map((call) => call.url).join(' | '),
  )
  check(
    'Drawer 打开并定位到该引用',
    drawerBindings.drawerOpen.value === true &&
      JSON.stringify(drawerBindings.highlight.value) === JSON.stringify({ line_number: 5, start: 4, end: 11 }),
  )
  check(
    'Drawer 取到引用所在 Block，位置按 locatorLabel 说',
    drawerBindings.drawerBlock.value?.id === 'blk_after1' &&
      drawerBindings.rowLocation('blk_after1', 5) === locatorModule.locatorLabel({ kind: 'line', index: 5 }),
    drawerBindings.rowLocation('blk_after1', 5),
  )

  // E. 源码层：单一 POST 入口、措辞纪律、三组标题。
  check(
    'DiffView 只 POST /api/v1/diffs',
    viewSource.includes("method: 'POST'") &&
      viewSource.includes("'/api/v1/diffs'") &&
      !viewSource.includes("'/api/v1/comparisons'") &&
      !viewSource.includes('repair-suggestions'),
  )
  check(
    'DiffView 源码不含禁用词',
    ['已满足', '覆盖率', '分数', '打分'].every((word) => !viewSource.includes(word)),
    ['已满足', '覆盖率', '分数', '打分'].filter((word) => viewSource.includes(word)).join('、'),
  )
  check('DiffView 明说不扫描整个材料库', viewSource.includes('不会自动扫描材料库'))
  check(
    '按钮与三组标题在源码中',
    viewSource.includes('比较修改效果') && viewSource.includes('已解决') && viewSource.includes('仍存在') && viewSource.includes('新增'),
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
