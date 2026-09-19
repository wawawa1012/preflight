// Leaf C 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// /grill 质询：打开页面只 GET 材料列表、零 POST（绝不自动生成追问）；
// 选中一份材料后点「生成追问」才 POST /api/v1/grill（body 只含该 material_id）；
// 空追问是合法结果；结果是编号追问卡片（01 起），依据 = 引用原文 + 位置，点开 Drawer
// （按需 GET 该材料 blocks，位置按 locatorLabel）；失败可见 + 重试；措辞纪律（不是打分只在小字、无禁用词）。
// 共享件纪律：页头消费 PageHeader（H1 由组件渲染，title 质询）、空追问消费 EmptyState、页面 max-w-6xl；
// 依据不新增「为什么会问」字段（quote + 位置，注明针对已核对的原文）。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-grill.mjs
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

const viewSource = readFileSync(new URL('../src/views/GrillView.vue', import.meta.url), 'utf8')
const headerSource = readFileSync(new URL('../src/components/review/PageHeader.vue', import.meta.url), 'utf8')
const emptySource = readFileSync(new URL('../src/components/review/EmptyState.vue', import.meta.url), 'utf8')

const materialsFixture = [
  { id: 'mat_a', filename: 'alpha.md', created_at: '2026-09-19T06:00:00+00:00', block_count: 2 },
  { id: 'mat_b', filename: 'beta.md', created_at: '2026-09-19T05:00:00+00:00', block_count: 1 },
]
const blocksA = [
  { id: 'blk_a1', document_id: 'mat_a', ordinal: 0, text: '本文系统准确率达到 95%。', locator: { kind: 'line', index: 7, block_index: 1 } },
  { id: 'blk_a2', document_id: 'mat_a', ordinal: 1, text: '复现实验的准确率达到 90%。', locator: { kind: 'line', index: 9, block_index: 1 } },
]
const questionsBody = [
  { prompt: '请说明「准确率达到 95%」的统计口径与实验条件。', quote: '准确率达到 95%', block_id: 'blk_a1', start: 4, end: 13 },
  { prompt: '「复现实验的准确率达到 90%」与主实验差异的原因是什么？', quote: '复现实验的准确率达到 90%', block_id: 'blk_a2', start: 0, end: 14 },
]

// 请求记录 + 可注入的 grill 响应；stub 按 URL 区分材料列表与单份材料详情。
const state = { calls: [], posts: [], grillStatus: 200, grillBody: questionsBody }
const resetState = () => {
  state.calls = []
  state.posts = []
  state.grillStatus = 200
  state.grillBody = questionsBody
}
const detailResponse = (id, filename, blocks) => ({
  id,
  filename,
  size_bytes: 10,
  sha256: 'a'.repeat(64),
  line_count: blocks.length,
  created_at: '2026-09-19T06:00:00+00:00',
  blocks,
})
function stubFetch() {
  return async (input, init = {}) => {
    const url = String(input)
    const method = (init && init.method) || 'GET'
    state.calls.push({ url, method })
    if (method === 'POST') {
      if (url.endsWith('/api/v1/grill')) {
        state.posts.push({ url, body: init.body })
        return jsonResponse(state.grillBody, state.grillStatus)
      }
      return jsonResponse({ code: 'unexpected_write', message: 'unexpected write', details: [] }, 500)
    }
    if (url.endsWith('/api/v1/materials/mat_a')) return jsonResponse(detailResponse('mat_a', 'alpha.md', blocksA))
    if (url.endsWith('/api/v1/materials')) return jsonResponse(materialsFixture)
    return jsonResponse([], 200)
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const routes = [
    { path: '/grill', component: { template: '<div />' } },
    { path: '/materials', component: { template: '<div />' } },
    { path: '/materials/new', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
  ]
  async function context() {
    const module = await server.ssrLoadModule('/src/views/GrillView.vue')
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/grill')
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return { module, app }
  }
  const locatorModule = await server.ssrLoadModule('/src/utils/locatorLabel.ts')

  // 0. 测试数据自检：引用必须是 Block 原文的精确片段（与后端复验口径一致）。
  const fixtureOk = questionsBody.every((question) => {
    const block = blocksA.find((item) => item.id === question.block_id)
    return block && Array.from(block.text).slice(question.start, question.end).join('') === question.quote
  })
  check('fixture：每条追问的 quote == block.text[start:end]', fixtureOk)

  // A. 打开页面：SSR 只画页面骨架（数据来自 setup 里的 GET）；零 POST、零 grill 请求。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出 /grill 页面骨架与两个出口',
    initialHtml.includes('质询') &&
      initialHtml.includes('根据材料里已经发现的问题，列出评审可能追问的点') &&
      initialHtml.includes('href="/materials"') &&
      initialHtml.includes('href="/"'),
  )
  // 页头纪律：H1 交给共享 PageHeader 渲染（title/subtitle 按约定），禁用词不许进英雄区。
  const headerTitle = viewSource.match(/<PageHeader[^>]*\stitle="([^"]+)"/)
  const headerSubtitle = viewSource.match(/<PageHeader[^>]*\ssubtitle="([^"]+)"/)
  const heroTexts = [headerTitle ? headerTitle[1] : '', headerSubtitle ? headerSubtitle[1] : '']
  check(
    '页头消费共享 PageHeader：title「质询」+ 指定副标题，H1 由组件渲染',
    viewSource.includes("import PageHeader from '../components/review/PageHeader.vue'") &&
      !viewSource.includes('<h1') &&
      headerSource.includes('<h1') &&
      headerSource.includes('{{ title }}') &&
      headerTitle?.[1] === '质询' &&
      headerSubtitle?.[1] === '根据材料里已经发现的问题，列出评审可能追问的点',
    headerTitle ? headerTitle[1] : '没有 PageHeader',
  )
  check(
    '英雄区不含禁用词（打分/参赛/提交前/不是打分）',
    Boolean(headerTitle) &&
      Boolean(headerSubtitle) &&
      heroTexts.every((text) => ['打分', '参赛', '提交前', '不是打分'].every((word) => !text.includes(word))),
    heroTexts.join(' | '),
  )
  check(
    '打开页面零 POST（不自动生成追问）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check(
    '打开页面只 GET 材料列表（一次）',
    state.calls.length === 1 && state.calls[0].url.endsWith('/api/v1/materials'),
    state.calls.map((call) => call.url).join(' | '),
  )
  check('打开页面从不请求 /api/v1/grill', state.calls.every((call) => !call.url.includes('/api/v1/grill')))

  // B. setup 行为：装载材料列表；未选材料不发；选中后点「生成追问」只 POST 一次，body 只含该 id。
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

  await bindings.generate()
  check('未选材料不发送 POST', state.posts.length === 0 && bindings.error.value === '')

  bindings.materialId.value = 'mat_a'
  await flush()
  await bindings.generate()
  check(
    '点「生成追问」只 POST 一次 /api/v1/grill',
    state.posts.length === 1 && state.posts[0].url.endsWith('/api/v1/grill'),
    state.posts.map((post) => post.url).join(' | '),
  )
  check(
    'POST body 只含选中的 material_id',
    state.posts.length === 1 && JSON.stringify(JSON.parse(state.posts[0].body)) === JSON.stringify({ material_id: 'mat_a' }),
    state.posts[0] ? state.posts[0].body : '无 POST',
  )
  check(
    '追问列表带入 2 条并清空错误',
    bindings.questions.value.length === 2 &&
      bindings.questions.value[0].quote === '准确率达到 95%' &&
      bindings.error.value === '' &&
      bindings.generated.value === true,
  )
  check('生成过程没有额外 GET（只有材料列表那一次）', state.calls.filter((call) => call.method === 'GET').length === 1)

  // C. 追问引用点开 Drawer：按需 GET 选中材料的 blocks，位置用 locatorLabel。
  const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_a$/.test(call.url))
  check('生成追问本身不取原文 blocks', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  await bindings.openQuestion(questionsBody[1])
  check('点引用后按需 GET 选中材料的 blocks', detailCalls().length === 1, detailCalls().map((call) => call.url).join(' | '))
  check(
    'Drawer 打开并定位到该引用',
    bindings.drawerOpen.value === true &&
      JSON.stringify(bindings.highlight.value) === JSON.stringify({ line_number: 9, start: 0, end: 14 }),
    JSON.stringify(bindings.highlight.value),
  )
  check(
    'Drawer 取到引用所在 Block，位置按 locatorLabel 说',
    bindings.drawerBlock.value?.id === 'blk_a2' &&
      bindings.rowLocation('blk_a2') === locatorModule.locatorLabel({ kind: 'line', index: 9 }),
    bindings.rowLocation('blk_a2'),
  )
  check('点击引用不产生任何写请求', state.calls.filter((call) => call.method !== 'GET').length === 1)

  // D. 空追问是合法结果：不报错、给出空态说明。
  resetState()
  state.grillBody = []
  globalThis.fetch = stubFetch()
  const emptyView = await context()
  const emptyBindings = emptyView.app.runWithContext(() => emptyView.module.default.setup({}, { expose() {} }))
  await flush()
  emptyBindings.materialId.value = 'mat_a'
  await flush()
  await emptyBindings.generate()
  check(
    '空追问合法：不报错、列表为空',
    emptyBindings.error.value === '' && emptyBindings.questions.value.length === 0 && emptyBindings.generated.value === true,
    `error=${emptyBindings.error.value}`,
  )
  check(
    '空结果走空态文案',
    emptyBindings.emptyResult.value === true && viewSource.includes('当前范围没有可引用的追问'),
  )

  // E. 失败可见 + 重试：502 上游不可用 → 显示错误且不伪造追问；重试成功 → 展示追问并清错。
  resetState()
  state.grillStatus = 502
  state.grillBody = { code: 'llm_unavailable', message: 'LLM 上游不可用', details: [] }
  globalThis.fetch = stubFetch()
  const failingView = await context()
  const failing = failingView.app.runWithContext(() => failingView.module.default.setup({}, { expose() {} }))
  await flush()
  failing.materialId.value = 'mat_a'
  await flush()
  await failing.generate()
  check(
    '失败可见：显示错误且不给追问',
    failing.error.value.includes('LLM 上游不可用') &&
      failing.questions.value.length === 0 &&
      failing.generated.value === false &&
      state.posts.length === 1,
    String(failing.error.value),
  )
  state.grillStatus = 200
  state.grillBody = questionsBody
  failing.retry()
  await flush()
  check(
    '重试成功后展示追问并清除错误',
    failing.questions.value.length === 2 && failing.error.value === '' && state.posts.length === 2,
    `posts=${state.posts.length}`,
  )

  // F. 未配置 LLM：错误文案要可操作（配置后重试），不暴露原始机器串。
  resetState()
  state.grillStatus = 503
  state.grillBody = { code: 'llm_unconfigured', message: '未配置 LLM（PREFLIGHT_LLM_BASE_URL/API_KEY/MODEL）', details: [] }
  globalThis.fetch = stubFetch()
  const unconfiguredView = await context()
  const unconfigured = unconfiguredView.app.runWithContext(() => unconfiguredView.module.default.setup({}, { expose() {} }))
  await flush()
  unconfigured.materialId.value = 'mat_a'
  await flush()
  await unconfigured.generate()
  check(
    '未配置 LLM 时给出可操作文案',
    unconfigured.error.value.includes('配置后重试') && unconfigured.questions.value.length === 0,
    String(unconfigured.error.value),
  )

  // G. 源码层：单一 POST 入口、单一材料下拉、措辞纪律、失败与重试、引用可点。
  check(
    'GrillView 只有一个材料下拉，选项来自材料列表',
    (viewSource.match(/<select/g) || []).length === 1 &&
      viewSource.includes('v-model="materialId"') &&
      viewSource.includes('<option v-for="item in materials"'),
  )
  check(
    'GrillView 只 POST /api/v1/grill',
    viewSource.includes("method: 'POST'") &&
      viewSource.includes("'/api/v1/grill'") &&
      !viewSource.includes('repair-suggestions') &&
      !viewSource.includes('comparisons'),
  )
  check('GrillView 明说不扫描整个材料库', viewSource.includes('不会自动扫描材料库'))
  // 措辞纪律：不是打分只做小字说明，不进标题；禁用词一个都不许出现（含全大写的 WORKBENCH 与 ChatGPT）。
  check(
    '「不是打分」只在小字说明里，不进页头标题',
    viewSource.includes('不是打分') &&
      Boolean(headerTitle) &&
      Boolean(headerSubtitle) &&
      heroTexts.every((text) => !text.includes('打分')),
    heroTexts.join(' | '),
  )
  const forbiddenWords = ['已满足', '已支撑', '覆盖率', '分数', '参赛', '提交前', 'ChatGPT']
  const forbiddenHits = forbiddenWords.filter((word) => viewSource.includes(word))
  check(
    'GrillView 源码不含禁用词（含 WORKBENCH/ChatGPT）',
    forbiddenHits.length === 0 && !viewSource.toLowerCase().includes('workbench'),
    forbiddenHits.join('、'),
  )
  check(
    '追问是编号卡片（01 起）：编号 + 追问点 + 依据',
    viewSource.includes("String(index + 1).padStart(2, '0')") &&
      viewSource.includes('依据') &&
      viewSource.includes('追问清单'),
  )
  // 共享件：空追问走 EmptyState；页面宽度与共享页头一致。
  check(
    '空追问消费共享 EmptyState（空结果不手搓段落）',
    viewSource.includes("import EmptyState from '../components/review/EmptyState.vue'") &&
      emptySource.includes('{{ title }}') &&
      /<EmptyState[^>]*title="当前范围没有可引用的追问/.test(viewSource),
  )
  check('页面宽度与共享页头一致（max-w-6xl，不用 4xl）', viewSource.includes('max-w-6xl') && !viewSource.includes('max-w-4xl'))
  // 依据纪律：依据 = 已复验的引用 + 位置；不加「为什么会问」字段。
  const questionInterface = viewSource.match(/interface GrillQuestion \{([^}]*)\}/)
  const questionFields = questionInterface
    ? questionInterface[1]
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '')
        .map((line) => line.split(':')[0].trim())
    : []
  check(
    '依据 = 引用 + 位置，注明针对已核对的原文（不新增「为什么会问」字段）',
    viewSource.includes('针对已核对的原文') &&
      viewSource.includes('{{ question.quote }}') &&
      viewSource.includes('rowLocation(question.block_id)') &&
      JSON.stringify(questionFields) === JSON.stringify(['prompt', 'quote', 'block_id', 'start', 'end']),
    questionFields.join(','),
  )
  check('引用纪律写在卡片说明里', viewSource.includes('引用必须能在原文里对上，对不上的已丢弃。'))
  check(
    '空态文案：当前范围没有可引用的追问',
    viewSource.includes('当前范围没有可引用的追问') && !viewSource.includes('空结果合法'),
  )
  check('失败可见 + 重试按钮在源码中', viewSource.includes('生成失败：') && viewSource.includes('重试'))
  check('追问引用行可点开 Drawer', viewSource.includes('v-for="(question, index) in questions"') && viewSource.includes('@click="openQuestion(question)"'))
  check('GrillView 不依赖路由参数（可用本地 /grill 路由挂载）', !viewSource.includes('useRoute'))
  check(
    '除 /api/v1/grill 外没有任何写请求（材料只读）',
    state.calls.every((call) => call.method === 'GET' || call.url.includes('/api/v1/grill')),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
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
