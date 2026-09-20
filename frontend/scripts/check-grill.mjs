// Review 质询检查（SSR 载入 + setup 行为级，不引入测试框架）：
// ReviewGrillView 对本次审查里选中的一份材料生成可回到原文的针对性追问：
// 打开只读材料库、零 POST（绝不自动生成追问）；
// 选中一份材料后点「开始质询」才 POST /api/v1/grill（body 只含该 material_id）；
// 空追问是合法结果；结果是一副编号问题卡（01 起）：问题正文最醒目，
// 「触发依据」只是卡片版式标签，依据 = 可点击引用 + 位置 + 查看原文（点开 Drawer，按需 GET 该材料 blocks，位置按 locatorLabel）；
// 失败可见 + 重试：主文案说人话可操作，机器码只做低权重技术细节；措辞纪律。
// 换材料后旧追问作废；选择与追问写入会话快照。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-grill.mjs
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

const viewSource = readFileSync(new URL('../src/views/review/ReviewGrillView.vue', import.meta.url), 'utf8')
const templateSource = viewSource.slice(viewSource.indexOf('<template>'))
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
const workspaceSource = readFileSync(new URL('../src/views/review/ReviewWorkspaceView.vue', import.meta.url), 'utf8')

const membersFixture = [
  { id: 'mat_a', filename: 'alpha.md', created_at: '2026-09-19T06:00:00+00:00', block_count: 2 },
  { id: 'mat_b', filename: 'beta.md', created_at: '2026-09-19T05:00:00+00:00', block_count: 1 },
]
const reviewFixture = {
  id: 'rev_1',
  title: '春季申报',
  rubric_id: 'rub_x',
  rubric_revision: 1,
  created_at: '2026-09-19T06:00:00+00:00',
  updated_at: '2026-09-19T07:00:00+00:00',
  materials: [
    { material_id: 'mat_a', label: 'Alpha', position: 0 },
    { material_id: 'mat_b', label: 'Beta', position: 1 },
  ],
}
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
    if (url.endsWith('/api/v1/materials')) return jsonResponse(membersFixture)
    return jsonResponse([], 200)
  }
}
const detailCalls = () => state.calls.filter((call) => /\/api\/v1\/materials\/mat_a$/.test(call.url))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const piniaModule = await server.ssrLoadModule('pinia')
  const contextModule = await server.ssrLoadModule('/src/views/review/reviewContext.ts')
  const reviewContextKey = contextModule.reviewContextKey
  const routes = [
    { path: '/reviews/:reviewId/grill', component: { template: '<div />' } },
    { path: '/materials', component: { template: '<div />' } },
    { path: '/', component: { template: '<div />' } },
  ]
  async function context() {
    const module = await server.ssrLoadModule('/src/views/review/ReviewGrillView.vue')
    const router = createRouter({ history: createMemoryHistory(), routes })
    await router.push('/reviews/rev_1/grill')
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

  // A. 打开页面：SSR 只画页面骨架；零 POST、零 grill 请求、零原文 GET。
  resetState()
  globalThis.fetch = stubFetch()
  const initial = await context()
  const initialHtml = await renderToString(initial.app)
  check(
    'SSR 画出质询正式名称与成员入口',
    initialHtml.includes('质询') && initialHtml.includes('针对已暴露的薄弱点'),
  )
  check(
    '打开页面零 POST（绝不自动生成追问）',
    state.posts.length === 0 && state.calls.every((call) => call.method === 'GET'),
    state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
  )
  check('打开页面从不请求 /api/v1/grill', state.calls.every((call) => !call.url.includes('/api/v1/grill')))
  check('打开页面不取任何材料原文', detailCalls().length === 0, detailCalls().map((call) => call.url).join(' | '))
  check(
    '材料下拉绑定单个 id ref，选项来自审查成员',
    viewSource.includes('v-model="materialId"') && viewSource.includes('<option v-for="member in members"'),
  )
  check(
    '下拉 aria-label 用 选择材料',
    viewSource.includes('aria-label="选择材料"'),
  )
  check('按钮文案 开始质询（加载中 正在质询…）', viewSource.includes('开始质询') && viewSource.includes('正在质询…'))

  // B. setup 行为：选中材料后点生成才 POST 一次，body 只含该 material_id。
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

  bindings.materialId.value = 'mat_a'
  await bindings.generate()
  check(
    '选中后只 POST 一次 /api/v1/grill',
    state.posts.length === 1 && state.posts[0].url.endsWith('/api/v1/grill'),
    state.posts.map((post) => post.url).join(' | '),
  )
  check(
    'POST body 只含选中的 material_id',
    state.posts.length === 1 && JSON.stringify(JSON.parse(state.posts[0].body)) === JSON.stringify({ material_id: 'mat_a' }),
    state.posts[0] ? state.posts[0].body : '无 POST',
  )
  check(
    '生成后追问入列且标记已生成',
    bindings.questions.value.length === 2 && bindings.generated.value === true && bindings.error.value === null,
  )
  check('质询全程只有这一个写请求（材料只读）', state.calls.filter((call) => call.method !== 'GET').length === 1)
  check(
    '选择与追问写入会话快照（切页返回可恢复）',
    view.pinia.state.value.session?.capabilitySnapshots?.['rev_1:grill']?.materialId === 'mat_a' &&
      view.pinia.state.value.session?.capabilitySnapshots?.['rev_1:grill']?.questions?.length === 2,
  )

  // C. 空追问是合法结果：不报错、给出空态说明。
  resetState()
  state.grillBody = []
  globalThis.fetch = stubFetch()
  const emptyView = await context()
  const emptyBindings = emptyView.app.runWithContext(() => emptyView.module.default.setup({}, { expose() {} }))
  await flush()
  emptyBindings.materialId.value = 'mat_a'
  await emptyBindings.generate()
  check(
    '空追问合法：标记已生成且不报错',
    emptyBindings.generated.value === true && emptyBindings.questions.value.length === 0 && emptyBindings.error.value === null,
  )
  check(
    '空结果走人话空态',
    emptyBindings.emptyResult.value === true &&
      viewSource.includes('当前材料没有生成可追溯的针对性追问') &&
      viewSource.includes('更换材料后再试'),
  )

  // D. 失败可见 + 重试：机器码只做低权重技术细节；换材料后旧追问作废。
  resetState()
  state.grillStatus = 500
  state.grillBody = { code: 'llm_timeout', message: 'LLM 超时', details: [] }
  globalThis.fetch = stubFetch()
  const failingView = await context()
  const failing = failingView.app.runWithContext(() => failingView.module.default.setup({}, { expose() {} }))
  await flush()
  failing.materialId.value = 'mat_a'
  await failing.generate()
  check(
    '失败可见：主文案说人话，机器码只进技术细节',
    failing.error.value?.message === '质询服务暂不可用，请稍后重试。' &&
      failing.error.value?.detail === 'llm_timeout' &&
      failing.questions.value.length === 0,
    JSON.stringify(failing.error.value),
  )
  check(
    '未配置时给出就绪态文案',
    failing.failureText('llm_unconfigured', '')?.message === '质询服务暂未就绪。',
  )
  state.grillStatus = 200
  state.grillBody = questionsBody
  failing.retry()
  await flush()
  check(
    '重试成功后展示追问并清除错误',
    failing.questions.value.length === 2 && failing.error.value === null && state.posts.length === 2,
    `posts=${state.posts.length}`,
  )
  failing.materialId.value = 'mat_b'
  await flush()
  check('换材料后旧追问与旧原文一并作废', failing.questions.value.length === 0 && failing.generated.value === false)

  // E. 引用点开 Drawer：按需取该材料原文；位置用 locatorLabel。
  resetState()
  globalThis.fetch = stubFetch()
  const drawerView = await context()
  const drawerBindings = drawerView.app.runWithContext(() => drawerView.module.default.setup({}, { expose() {} }))
  await flush()
  drawerBindings.materialId.value = 'mat_a'
  await drawerBindings.generate()
  await drawerBindings.openQuestion(drawerBindings.questions.value[0])
  check('点引用按需取该材料原文', detailCalls().length === 1, detailCalls().map((call) => call.url).join(' | '))
  check(
    'Drawer 打开并定位到该引用',
    drawerBindings.drawerOpen.value === true &&
      JSON.stringify(drawerBindings.highlight.value) === JSON.stringify({ line_number: 7, start: 4, end: 13 }),
  )
  check(
    'Drawer 取到引用所在 Block，位置按 locatorLabel 说',
    drawerBindings.drawerBlock.value?.id === 'blk_a1' &&
      drawerBindings.rowLocation('blk_a1') === locatorModule.locatorLabel({ kind: 'line', index: 7 }),
    drawerBindings.rowLocation('blk_a1'),
  )

  // F. 源码层：单一 POST 入口、路由、Workspace 入口、措辞纪律。
  check(
    'ReviewGrillView 只 POST /api/v1/grill',
    viewSource.includes("method: 'POST'") && viewSource.includes("'/api/v1/grill'") && !viewSource.includes('repair-suggestions'),
  )
  const bannedWords = ['已满足', '已支撑', '覆盖率', '分数', '参赛', '提交前', 'ChatGPT']
  check(
    'ReviewGrillView 源码不含禁用词',
    bannedWords.every((word) => !viewSource.includes(word)),
    bannedWords.filter((word) => viewSource.includes(word)).join('、'),
  )
  check(
    '结果是编号问题卡（01 起），问题正文最醒目',
    templateSource.includes("String(index + 1).padStart(2, '0')") && templateSource.includes('{{ question.prompt }}'),
  )
  check(
    '触发依据只是版式标签，依据可点回原文',
    templateSource.includes('触发依据') && templateSource.includes('查看原文 →') && templateSource.includes('在材料中打开'),
  )
  check(
    '可信度只低权重一句（仅展示能够回到原文的追问）',
    templateSource.includes('仅展示能够回到原文的追问'),
  )
  check(
    '路由挂载 Review 质询子视角，旧 /grill 重定向到 Home',
    routerSource.includes("path: 'grill'") &&
      routerSource.includes('review-grill') &&
      routerSource.includes("path: '/grill', redirect: '/'"),
  )
  check(
    'Workspace rail 有质询入口（同一次审查的视角）',
    workspaceSource.includes("key: 'grill'") && workspaceSource.includes('质询'),
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
