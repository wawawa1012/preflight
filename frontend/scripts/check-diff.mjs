// Review 修改效果检查（SSR 载入 + setup 行为级，不引入测试框架）：
// ReviewDiffView 在本次审查的成员里选「修改前 / 修改后」两份材料，看一致性待核对项的变化：
// 打开只读材料库、零 POST；同一份材料不发送且就地报错；
// 两个不同 id 才 POST /api/v1/diffs（body 只含 before/after 两个 id）；
// 结果是变化时间线：hero 两个大数字（修改前 = 未再检出+仍存在，修改后 = 仍存在+新增），
// 三组固定 本次未再检出(emerald) / 仍存在(amber) / 新增(rose)，空组是合法结果；
// 引用点开 Drawer（按需 GET 两份材料 blocks，位置按 locatorLabel）。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-diff.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp, ref } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const viewSource = readFileSync(new URL('../src/views/review/ReviewDiffView.vue', import.meta.url), 'utf8')
const templateSource = viewSource.slice(viewSource.indexOf('<template>'))
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
const workspaceSource = readFileSync(new URL('../src/views/review/ReviewWorkspaceView.vue', import.meta.url), 'utf8')

const membersFixture = [
  { id: 'mat_before', filename: 'draft.md', created_at: '2026-09-18T06:00:00+00:00', block_count: 2 },
  { id: 'mat_after', filename: 'revised.md', created_at: '2026-09-19T06:00:00+00:00', block_count: 1 },
]
const reviewFixture = {
  id: 'rev_1',
  title: '春季申报',
  rubric_id: 'rub_x',
  rubric_revision: 1,
  created_at: '2026-09-18T06:00:00+00:00',
  updated_at: '2026-09-19T06:00:00+00:00',
  materials: [
    { material_id: 'mat_before', label: '初稿', position: 0 },
    { material_id: 'mat_after', label: '修订稿', position: 1 },
  ],
}
const blocksBefore = [
  { id: 'blk_before1', document_id: 'mat_before', ordinal: 1, text: '实验组准确率 88%。', locator: { kind: 'line', index: 3, block_index: 1 } },
]
const blocksAfter = [
  { id: 'blk_after1', document_id: 'mat_after', ordinal: 1, text: '实验组准确率 93%。', locator: { kind: 'line', index: 5, block_index: 1 } },
]
const citationBefore = { block_id: 'blk_before1', line_number: 3, quote: '准确率 88%', start: 4, end: 11, value: '88', unit: '%' }
const citationBefore2 = { block_id: 'blk_before1', line_number: 4, quote: '召回率 90%', start: 8, end: 15, value: '90', unit: '%' }
const citationAfter = { block_id: 'blk_after1', line_number: 5, quote: '准确率 93%', start: 4, end: 11, value: '93', unit: '%' }
const makeFinding = (materialId, measure, values, citations) => ({
  material_id: materialId,
  kind: 'numeric_inconsistency',
  measure,
  values,
  searched_block_count: 2,
  searched_statement_count: 2,
  explanation: '同一度量词下数值不一致。',
  citations,
})
// 三组数字刻意各不相同：resolved 2 / unchanged 1 / new 1 → 修改前 3、修改后 2，能区分错位的计数公式。
const resolvedFindings = [
  makeFinding('mat_before', '准确率', ['88%', '93%'], [citationBefore]),
  makeFinding('mat_before', '召回率', ['90%', '95%'], [citationBefore2]),
]
const unchangedFinding = makeFinding('mat_before', '样本量', ['1200', '1200'], [citationBefore2])
const newFinding = makeFinding('mat_after', '准确率', ['93%', '96%'], [citationAfter])
const diffBody = {
  material_id_before: 'mat_before',
  material_id_after: 'mat_after',
  filename_before: 'draft.md',
  filename_after: 'revised.md',
  resolved: resolvedFindings,
  unchanged: [unchangedFinding],
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
    if (url.endsWith('/api/v1/materials')) return jsonResponse(membersFixture)
    return jsonResponse([], 200)
  }
}
const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_(before|after)$/.test(call.url))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const piniaModule = await server.ssrLoadModule('pinia')
  const contextModule = await server.ssrLoadModule('/src/views/review/reviewContext.ts')
  const reviewContextKey = contextModule.reviewContextKey
  const routes = [
    { path: '/reviews/:reviewId/diff', component: { template: '<div />' } },
    { path: '/materials', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
  ]
  async function context() {
    const module = await server.ssrLoadModule('/src/views/review/ReviewDiffView.vue')
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/reviews/rev_1/diff')
    await router.isReady()
    const pinia = piniaModule.createPinia()
    const app = createSSRApp(module.default)
    app.use(router)
    app.use(pinia)
    piniaModule.setActivePinia(pinia)
    app.provide(reviewContextKey, { review: ref({ ...reviewFixture }), rubricTitle: ref('标准X'), refresh: async () => {} })
    app.provide(ssrContextKey, { modules: new Set() })
    return { module, app, pinia }
  }
  const locatorModule = await server.ssrLoadModule('/src/utils/locatorLabel.ts')

  // A. 打开页面：SSR 只画页面骨架；零 POST、零 diffs 请求、零原文 GET。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出修改效果正式名称与成员入口',
    initialHtml.includes('修改效果') && initialHtml.includes('比较本次检测结果'),
  )
  check(
    '打开页面零 POST（不自动比较）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/diffs', state.calls.every((call) => !call.url.includes('/api/v1/diffs')))
  check('打开页面不取任何材料原文', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  check(
    '两个材料下拉绑定两个 id ref，选项来自审查成员',
    viewSource.includes('v-model="materialIdBefore"') &&
      viewSource.includes('v-model="materialIdAfter"') &&
      viewSource.includes('<option v-for="member in members"'),
  )
  check(
    '下拉标签与 aria-label 用 修改前材料 / 修改后材料',
    viewSource.includes('aria-label="修改前材料"') && viewSource.includes('aria-label="修改后材料"'),
  )
  check('按钮文案 比较修改效果（加载中 比较中…）', viewSource.includes('比较修改效果') && viewSource.includes('比较中…'))

  // B. setup 行为：同一份材料不发；两份不同才 POST 一次，body 只含 before/after 两个 id。
  resetState()
  globalThis.fetch = stubFetch()
  const view = await context()
  const bindings = view.app.runWithContext(() => view.module.default.setup({}, { expose() {} }))
  await flush()
  check(
    '成员来自 Review 上下文（2 名），材料库只读装载',
    bindings.library.value.length === 2 && bindings.loading.value === false,
    bindings.library.value.length,
  )
  check('装载后仍零 POST', state.posts.length === 0, `posts=${state.posts.length}`)

  bindings.materialIdBefore.value = 'mat_before'
  bindings.materialIdAfter.value = 'mat_before'
  await bindings.diff()
  check('同一份材料不发送 POST', state.posts.length === 0, `posts=${state.posts.length}`)
  check('同一份材料就地报错', bindings.diffError.value.includes('两份材料不能相同'), bindings.diffError.value)
  check('同一份材料不产生结果', bindings.result.value === null)

  bindings.materialIdAfter.value = 'mat_after'
  await bindings.diff()
  check(
    '两个不同 id 只 POST 一次 /api/v1/diffs',
    state.posts.length === 1 && state.posts[0].url.endsWith('/api/v1/diffs'),
    state.posts.map((post) => post.url).join(' | '),
  )
  check(
    'POST body 只含修改前/后两个 id',
    state.posts.length === 1 &&
      JSON.stringify(JSON.parse(state.posts[0].body)) ===
        JSON.stringify({ material_id_before: 'mat_before', material_id_after: 'mat_after' }),
    state.posts[0] ? state.posts[0].body : '无 POST',
  )
  check(
    'hero 数字：修改前 = 未再检出+仍存在 = 3，修改后 = 仍存在+新增 = 2',
    bindings.beforeCount.value === 3 && bindings.afterCount.value === 2,
    `before=${bindings.beforeCount.value} after=${bindings.afterCount.value}`,
  )
  check(
    '三组固定为 本次未再检出 / 仍存在 / 新增（未再检出不代表风险已解决）',
    bindings.groups.value.map((group) => group.title).join('/') === '本次未再检出/仍存在/新增' &&
      bindings.groups.value[0].findings.length === 2 &&
      bindings.groups.value[1].findings.length === 1 &&
      bindings.groups.value[2].findings.length === 1,
  )
  check(
    'delta 句子说清变化方向',
    bindings.deltaSentence.value.includes('少了 1 个待核对项'),
    bindings.deltaSentence.value,
  )
  check('对照全程只有这一个写请求（材料只读）', state.calls.filter((call) => call.method !== 'GET').length === 1)
  check(
    'finding 措辞只有数值不一致 / 待人工判断',
    bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
  )
  check(
    '选择与结果写入会话快照（切页返回可恢复）',
    view.pinia.state.value.session?.capabilitySnapshots?.['rev_1:diff']?.materialIdBefore === 'mat_before' &&
      view.pinia.state.value.session?.capabilitySnapshots?.['rev_1:diff']?.result?.new?.length === 1,
  )

  // C. 空结果是合法结果：三组全空走空态，不报错。
  resetState()
  state.diffBody = { ...diffBody, resolved: [], unchanged: [], new: [] }
  globalThis.fetch = stubFetch()
  const emptyView = await context()
  const emptyBindings = emptyView.app.runWithContext(() => emptyView.module.default.setup({}, { expose() {} }))
  await flush()
  emptyBindings.materialIdBefore.value = 'mat_before'
  emptyBindings.materialIdAfter.value = 'mat_after'
  await emptyBindings.diff()
  check(
    '空结果合法：结果对象仍在且不报错',
    emptyBindings.diffError.value === '' && emptyBindings.result.value !== null && emptyBindings.emptyResult.value === true,
    emptyBindings.diffError.value,
  )
  check(
    '空结果走人话空态',
    viewSource.includes('这两份材料之间没有发现一致性待核对项的变化') && viewSource.includes('换一组版本再看'),
  )

  // D. 引用点开 Drawer：位置用 locatorLabel；引用折叠为二级 details。
  resetState()
  globalThis.fetch = stubFetch()
  const drawerView = await context()
  const drawerBindings = drawerView.app.runWithContext(() => drawerView.module.default.setup({}, { expose() {} }))
  await flush()
  drawerBindings.materialIdBefore.value = 'mat_before'
  drawerBindings.materialIdAfter.value = 'mat_after'
  await drawerBindings.diff()
  await drawerBindings.openCitation(citationAfter)
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
  check('引用折叠为二级（details/原文引用）', templateSource.includes('<details') && templateSource.includes('原文引用'))

  // E. 源码层：单一 POST 入口、路由、Workspace 入口、措辞纪律。
  check(
    'ReviewDiffView 只 POST /api/v1/diffs',
    viewSource.includes("method: 'POST'") && viewSource.includes("'/api/v1/diffs'") && !viewSource.includes('repair-suggestions'),
  )
  const bannedWords = ['已满足', '覆盖率', '分数', '打分', 'COMPARE']
  check(
    'ReviewDiffView 源码不含禁用词',
    bannedWords.every((word) => !viewSource.includes(word)),
    bannedWords.filter((word) => viewSource.includes(word)).join('、'),
  )
  check(
    '标题用正式名称、副标题说清未再检出≠已解决',
    viewSource.includes('修改效果') && viewSource.includes('未再检出不代表风险已解决'),
  )
  check(
    '成员不足与空结果走共享 EmptyState（review/EmptyState）',
    viewSource.includes("from '../../components/review/EmptyState.vue'") &&
      templateSource.includes('本次审查的材料不足两份') &&
      templateSource.includes('v-if="emptyResult"'),
  )
  check(
    '路由挂载 Review 修改效果子视角，旧 /diff 重定向到 Home',
    routerSource.includes("path: 'diff'") &&
      routerSource.includes('review-diff') &&
      routerSource.includes("path: '/diff', redirect: '/'"),
  )
  check(
    'Workspace rail 有修改效果入口（同一次审查的视角）',
    workspaceSource.includes("key: 'diff'") && workspaceSource.includes('修改效果'),
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
