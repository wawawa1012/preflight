// Leaf B 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// /compare 检查两份材料说法是否一致：打开页面只 GET 材料列表、零 POST（不自动扫描材料库）；
// 同一份材料不发送且就地报错；两个不同 id 才 POST /api/v1/comparisons（body 只含两个选中 id）；
// 检查成功后按需 GET 两份材料的 blocks（左右分栏靠 document_id 判侧，引用点开 Drawer，位置按 locatorLabel）；
// 页面头与空态消费共享 review/PageHeader、review/EmptyState，页面宽度 max-w-6xl；空 findings 是合法结果，走共享空态。
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
const templateSource = viewSource.slice(viewSource.indexOf('<template>'))
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
  explanation: '两份材料在同一指标下给出不同数字。',
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
const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_[ab]$/.test(call.url))

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

  // A. 打开页面：SSR 只画页面骨架（数据来自 setup 里的 GET）；零 POST、零 comparisons 请求、零原文 GET。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出 /compare 正式名称与两个出口',
    initialHtml.includes('一致性检查') &&
      initialHtml.includes('检查两份材料是否对同一指标使用了不同数值') &&
      initialHtml.includes('href="/materials"') &&
      initialHtml.includes('href="/"'),
  )
  check(
    '打开页面零 POST（不自动检查）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/comparisons', state.calls.every((call) => !call.url.includes('/api/v1/comparisons')))
  check('打开页面不取任何材料原文', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  check(
    '两个材料下拉绑定两个 id ref，选项来自材料列表',
    (viewSource.match(/<select/g) || []).length === 2 &&
      viewSource.includes('v-model="materialIdA"') &&
      viewSource.includes('v-model="materialIdB"') &&
      viewSource.includes('<option v-for="item in materials"'),
  )
  check(
    '下拉标签与 aria-label 用 主材料 / 对照材料',
    viewSource.includes('aria-label="主材料"') &&
      viewSource.includes('aria-label="对照材料"') &&
      !viewSource.includes('材料 A') &&
      !viewSource.includes('材料 B'),
  )
  check('按钮文案 检查一致性（加载中 检查中…）', viewSource.includes('检查一致性') && viewSource.includes('检查中…'))

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
  check('同一份材料就地报错', bindings.compareError.value.includes('两份材料不能相同'), bindings.compareError.value)
  check('同一份材料不产生结果', bindings.result.value === null)
  check('同一份材料也不取原文', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))

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
    '检查成功后取两份材料原文，只取这两份（分栏判侧所需）',
    detailCalls().length === 2 &&
      detailCalls().some((call) => call.url.endsWith('/mat_a')) &&
      detailCalls().some((call) => call.url.endsWith('/mat_b')) &&
      detailCalls().every((call) => call.method === 'GET'),
    detailCalls().map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  const postIndex = state.calls.findIndex((call) => call.method === 'POST')
  const firstDetailIndex = state.calls.findIndex((call) => /\/api\/v1\/materials\/mat_[ab]$/.test(call.url))
  check('先 POST 检查、后取原文', postIndex >= 0 && firstDetailIndex > postIndex)
  check(
    'finding 措辞只有数值不一致 / 待人工判断',
    bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
  )
  check(
    '分栏按 Block.document_id 判侧：左 = 主材料、右 = 对照材料',
    bindings.sideCitations(finding, 'a').length === 1 &&
      bindings.sideCitations(finding, 'a')[0].block_id === 'blk_a1' &&
      bindings.sideCitations(finding, 'b').length === 1 &&
      bindings.sideCitations(finding, 'b')[0].block_id === 'blk_b1' &&
      bindings.unsidedCitations(finding).length === 0,
    JSON.stringify(bindings.sideCitations(finding, 'a').map((citation) => citation.block_id)),
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
  check(
    '空结果走人话空态',
    emptyBindings.emptyResult.value === true &&
      viewSource.includes('当前没有发现两份材料对同一指标使用不同数值') &&
      viewSource.includes('换个对照材料'),
  )

  // D. 引用点开 Drawer：检查成功后原文已到手，点引用不重复取；位置用 locatorLabel。
  resetState()
  globalThis.fetch = stubFetch()
  const drawerView = await context()
  const drawerBindings = drawerView.app.runWithContext(() => drawerView.module.default.setup({}, { expose() {} }))
  await flush()
  drawerBindings.materialIdA.value = 'mat_a'
  drawerBindings.materialIdB.value = 'mat_b'
  await drawerBindings.compare()
  check('检查成功后已取两份材料原文（分栏判侧）', detailCalls().length === 2, detailCalls().map((call) => call.url).join(' | '))
  await drawerBindings.openCitation(citationB)
  check('点引用不重复取原文（已缓存）', detailCalls().length === 2, detailCalls().map((call) => call.url).join(' | '))
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
  const bannedWords = ['已满足', '分数', '笛卡尔积', '参赛', '提交前', '材料 A', '材料 B', 'COMPARE']
  check(
    'CompareView 源码不含禁用词',
    bannedWords.every((word) => !viewSource.includes(word)),
    bannedWords.filter((word) => viewSource.includes(word)).join('、'),
  )
  check(
    'hero 不再出现 COMPARE 眉题，标题用正式名称、副标题说真实能力',
    !viewSource.includes('COMPARE') &&
      viewSource.includes('一致性检查') &&
      viewSource.includes('检查两份材料是否对同一指标使用了不同数值'),
  )
  check(
    '页头消费共享 PageHeader（标题/副标题走 props，右侧出口走插槽）',
    viewSource.includes("import PageHeader from '../components/review/PageHeader.vue'") &&
      templateSource.includes('<PageHeader') &&
      templateSource.includes('title="一致性检查"') &&
      templateSource.includes('subtitle="检查两份材料是否对同一指标使用了不同数值。"') &&
      !templateSource.includes('<h1'),
  )
  check(
    '空结果走共享 EmptyState（review/EmptyState）',
    viewSource.includes("import EmptyState from '../components/review/EmptyState.vue'") &&
      templateSource.includes('v-if="emptyResult"') &&
      templateSource.includes('<EmptyState'),
  )
  check(
    '页面宽度 max-w-6xl，返回 审查 到 /',
    viewSource.includes('mx-auto max-w-6xl') &&
      !viewSource.includes('max-w-4xl') &&
      templateSource.includes('to="/"') &&
      templateSource.includes('审查'),
  )
  check(
    '分栏保留：左右两栏各放一份材料的引用',
    (templateSource.match(/sm:grid-cols-2/g) || []).length >= 2 &&
      templateSource.includes('主材料 · ') &&
      templateSource.includes('对照材料 · '),
  )
  check(
    '每条问题先给人话结论，再左右摊开两边数值与引用（split 对照主视觉）',
    viewSource.includes('findingHeadline') &&
      viewSource.includes("sideValue(finding, 'a')") &&
      viewSource.includes("sideValue(finding, 'b')") &&
      templateSource.includes('↔'),
  )
  check('结果头部说 发现 N 处待核对项', viewSource.includes('处待核对项') && !viewSource.includes('处需要核对'))
  check('不扫描材料库只留在注释里，不进页面文案', viewSource.includes('自动扫描材料库') && !templateSource.includes('自动扫描材料库'))
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
