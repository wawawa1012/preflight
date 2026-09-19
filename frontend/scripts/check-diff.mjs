// I11 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// /diff 修改前后少了什么问题：打开页面只 GET 材料列表、零 POST（不会自动扫描材料库）；
// 同一份材料不发送且就地报错；两个不同 id 才 POST /api/v1/diffs（body 只含 before/after 两个 id）；
// 结果是变化时间线：hero 两个大数字（修改前 = 已解决+仍存在，修改后 = 仍存在+新增），
// 三组固定 已解决(emerald) / 仍存在(amber) / 新增(rose)，空组是合法结果；
// 引用点开 Drawer（按需 GET 两份材料 blocks，位置按 locatorLabel）。
// 页头/空态消费共享 review/PageHeader + review/EmptyState；页宽 max-w-6xl；结果区少边框（色调底 + divide 分隔）。
// /diff 已挂进 router/index.ts（本脚本只断言，不改路由）。合成数据只存在于本脚本（test-only）。
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
const templateSource = viewSource.slice(viewSource.indexOf('<template>'))
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')

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
const citationBefore2 = { block_id: 'blk_before1', line_number: 4, quote: '召回率 90%', start: 8, end: 15, value: '90%', unit: '%' }
const citationAfter = { block_id: 'blk_after1', line_number: 5, quote: '准确率 93%', start: 4, end: 11, value: '93%', unit: '%' }
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
    if (url.endsWith('/api/v1/materials')) return jsonResponse(materialsFixture)
    return jsonResponse([], 200)
  }
}
const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_(before|after)$/.test(call.url))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
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

  // A. 打开页面：SSR 只画页面骨架（数据来自 setup 里的 GET）；零 POST、零 diffs 请求、零原文 GET。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出 /diff 大白话标题、副标题与两个出口',
    initialHtml.includes('修改前后少了什么问题') &&
      initialHtml.includes('看审查发现哪些已解决、哪些还在、哪些是新的') &&
      initialHtml.includes('href="/materials"') &&
      initialHtml.includes('href="/"'),
  )
  check(
    '打开页面零 POST（不自动对照）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/diffs', state.calls.every((call) => !call.url.includes('/api/v1/diffs')))
  check('打开页面不取任何材料原文', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  check(
    '两个材料下拉绑定 修改前/修改后 两个 id ref，选项来自材料列表',
    (viewSource.match(/<select/g) || []).length === 2 &&
      viewSource.includes('v-model="materialIdBefore"') &&
      viewSource.includes('v-model="materialIdAfter"') &&
      viewSource.includes('<option v-for="item in materials"'),
  )
  check(
    '下拉标签与 aria-label 用 修改前 / 修改后',
    viewSource.includes('aria-label="修改前材料"') &&
      viewSource.includes('aria-label="修改后材料"') &&
      !viewSource.includes('材料 A') &&
      !viewSource.includes('材料 B'),
  )
  check('按钮文案 比较修改效果（加载中 对照中…）', viewSource.includes('比较修改效果') && viewSource.includes('对照中…'))

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
    '结果带入两份文件名与三组（resolved 2 / unchanged 1 / new 1）',
    bindings.result.value?.filename_before === 'draft.md' &&
      bindings.result.value?.filename_after === 'revised.md' &&
      bindings.result.value?.resolved.length === 2 &&
      bindings.result.value?.unchanged.length === 1 &&
      bindings.result.value?.new.length === 1 &&
      bindings.diffError.value === '',
  )
  check('对照全程只有这一个写请求（材料只读）', state.calls.filter((call) => call.method !== 'GET').length === 1)
  check(
    'hero 数字：修改前 = 已解决+仍存在 = 3，修改后 = 仍存在+新增 = 2',
    bindings.beforeCount?.value === 3 && bindings.afterCount?.value === 2,
    `before=${bindings.beforeCount?.value} after=${bindings.afterCount?.value}`,
  )
  check(
    '三组固定为 已解决 / 仍存在 / 新增，按 emerald / amber / rose 顺序',
    JSON.stringify(bindings.groups.value.map((group) => group.title)) === JSON.stringify(['已解决', '仍存在', '新增']) &&
      JSON.stringify(bindings.groups.value.map((group) => group.tone)) === JSON.stringify(['emerald', 'amber', 'rose']) &&
      bindings.groups.value.every((group) => typeof group.findings.length === 'number') &&
      viewSource.includes('group.findings.length'),
  )
  check(
    'finding 措辞只有数值不一致 / 待人工判断',
    bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
  )

  // C. 空三组是合法结果：不报错、hero 两个数字都是 0、给出空态说明，且三组仍然渲染。
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
    '空结果 hero 两个数字都是 0',
    emptyBindings.beforeCount?.value === 0 && emptyBindings.afterCount?.value === 0,
    `before=${emptyBindings.beforeCount?.value} after=${emptyBindings.afterCount?.value}`,
  )
  check(
    '空结果走空态文案且空组也渲染',
    emptyBindings.emptyResult.value === true &&
      emptyBindings.groups.value.length === 3 &&
      viewSource.includes('没有可对照的数值差异') &&
      viewSource.includes('这一组目前没有条目'),
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

  // E. 源码层：单一 POST 入口、变化时间线形态、措辞纪律、路由。
  check(
    'DiffView 只 POST /api/v1/diffs',
    viewSource.includes("method: 'POST'") &&
      viewSource.includes("'/api/v1/diffs'") &&
      !viewSource.includes("'/api/v1/comparisons'") &&
      !viewSource.includes('repair-suggestions'),
  )
  check(
    'DiffView 源码不含禁用词',
    ['已满足', '覆盖率', '分数', '打分', '笛卡尔积', '参赛', '提交前', 'COMPARE'].every((word) => !viewSource.includes(word)),
    ['已满足', '覆盖率', '分数', '打分', '笛卡尔积', '参赛', '提交前', 'COMPARE'].filter((word) => viewSource.includes(word)).join('、'),
  )
  check(
    '返回入口是 审查（不再出现 WORKBENCH 字样）',
    !/workbench/i.test(viewSource) && viewSource.includes('审查'),
    viewSource.match(/workbench/i) ? '仍含 workbench' : '',
  )
  check('不扫描材料库只留在注释里，不进页面文案', viewSource.includes('不会自动扫描材料库') && !templateSource.includes('不会自动扫描材料库'))
  check(
    '变化时间线在模板里：按组连线（止于最后一个节点）+ 三组色调映射',
    templateSource.includes('w-[2px] bg-slate-800') &&
      templateSource.includes('index < groups.length - 1') &&
      templateSource.includes('toneDot[group.tone]') &&
      templateSource.includes('toneCount[group.tone]') &&
      templateSource.includes('toneCard[group.tone]') &&
      viewSource.includes('border-emerald-400') &&
      viewSource.includes('border-amber-400') &&
      viewSource.includes('border-rose-400'),
  )
  check(
    'hero 两个大数字在模板里（修改前 N 个待处理 → 修改后 M 个待处理）',
    templateSource.includes('个待处理') &&
      templateSource.includes('beforeCount') &&
      templateSource.includes('afterCount') &&
      templateSource.includes('修改前') &&
      templateSource.includes('修改后'),
  )
  check(
    '按钮与三组标题在源码中',
    viewSource.includes('比较修改效果') && viewSource.includes('已解决') && viewSource.includes('仍存在') && viewSource.includes('新增'),
  )
  check(
    'DiffView 消费共享页头与空态（review/PageHeader + review/EmptyState）',
    viewSource.includes("import PageHeader from '../components/review/PageHeader.vue'") &&
      viewSource.includes("import EmptyState from '../components/review/EmptyState.vue'") &&
      templateSource.includes('<PageHeader') &&
      (templateSource.match(/<EmptyState/g) || []).length === 2,
  )
  check(
    '页宽 max-w-6xl，标题经 PageHeader 传入（模板不再自铺 h1）',
    viewSource.includes('max-w-6xl') &&
      !viewSource.includes('max-w-4xl') &&
      templateSource.includes('title="修改前后少了什么问题"') &&
      !templateSource.includes('<h1'),
  )
  check(
    '材料不足两份与读取失败都走 EmptyState，各自带 CTA',
    viewSource.includes('至少需要两份已保存的材料才能看修改前后的变化') &&
      viewSource.includes('添加材料') &&
      viewSource.includes('材料列表读取失败') &&
      viewSource.includes('重试'),
  )
  check(
    'less border：结果区不逐块加边框，改用色调底 + divide 分隔',
    !templateSource.includes('border border-slate-800') &&
      templateSource.includes('divide-y divide-slate-800') &&
      viewSource.includes('bg-slate-950/40'),
  )
  check('路由 /diff 指向 DiffView', routerSource.includes("path: '/diff'") && routerSource.includes('DiffView'))
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
