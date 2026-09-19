// Leaf A 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 「生成修复建议」入口（每条待核对问题一个）、点击才 POST、打开页面不发请求、
// 失败可见且可重试、原文引用保持可点、不写材料、措辞纪律。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-repair-suggestion.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp, toRaw } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const reportSource = readFileSync(new URL('../src/views/MaterialReportView.vue', import.meta.url), 'utf8')
const panelSource = readFileSync(new URL('../src/components/RepairSuggestionPanel.vue', import.meta.url), 'utf8')

// 请求记录 + 修复建议 POST 的可注入响应（成功/失败由用例切换）。
const SUCCESS_BODY = {
  suggestion: '先核对两次实验的统计口径，再把两处「准确率」统一为同一个数值。',
  action: '统一数值',
}
const state = {
  calls: [],
  repairPosts: 0,
  repairBodies: [],
  repairStatus: 200,
  repairBody: SUCCESS_BODY,
}
const resetState = () => {
  state.calls = []
  state.repairPosts = 0
  state.repairBodies = []
  state.repairStatus = 200
  state.repairBody = SUCCESS_BODY
}

function stubFetch(options = {}) {
  const { report = null, reportStatus = 200, findings = [], findingsStatus = 200 } = options
  return async (input, init = {}) => {
    const url = String(input)
    const method = (init && init.method) || 'GET'
    state.calls.push({ url, method })
    if (method === 'POST' && url.includes('/repair-suggestions')) {
      state.repairPosts += 1
      state.repairBodies.push(init.body)
      return jsonResponse(state.repairBody, state.repairStatus)
    }
    if (url.includes('consistency-findings')) return jsonResponse(findings, findingsStatus)
    if (url.includes('statement-signals')) return jsonResponse([], 200)
    if (url.includes('agent-proposals')) return jsonResponse([], 200)
    return jsonResponse(report, reportStatus)
  }
}

// —— 源码层：入口、面板接线、引用可点、材料只读、措辞纪律 ——
check(
  '报告页每条待核对问题有「生成修复建议」按钮（点击选中该条）',
  reportSource.includes('生成修复建议') &&
    reportSource.includes('@click="openRepair(finding)"') &&
    reportSource.includes('v-for="finding in findings"'),
)
check(
  '报告页挂载修复建议面板并把引用点击转发给同一 Drawer',
  reportSource.includes('RepairSuggestionPanel') &&
    reportSource.includes(':finding="repairFinding"') &&
    reportSource.includes('@open-citation="openHighlight"'),
)
check(
  'LLM 逻辑不在报告页（POST 只写在面板组件里）',
  !reportSource.includes('/repair-suggestions') && panelSource.includes('/repair-suggestions'),
)
check('报告页原始引用保持可点（原按钮未动）', reportSource.includes('@click="openHighlight(citation)"'))
check(
  '面板只 POST repair-suggestions，不碰材料写入端点',
  panelSource.includes('method: \'POST\'') &&
    !panelSource.includes('evidence-annotations') &&
    !panelSource.includes('criterion-evidence-links') &&
    !panelSource.includes('method: \'PUT\'') &&
    !panelSource.includes('method: \'PATCH\'') &&
    !panelSource.includes('method: \'DELETE\''),
)
check('面板展示建议文本与动作', panelSource.includes('{{ suggestion.suggestion }}') && panelSource.includes('{{ suggestion.action }}'))
check('失败可见 + 重试按钮在面板源码中', panelSource.includes('生成失败：') && panelSource.includes('重试'))
check('面板说明不改材料', panelSource.includes('不会改动材料原文'))
check('面板引用行点回原文（emit open-citation）', panelSource.includes("emit('open-citation', citation)"))
const FORBIDDEN = ['已满足', '已支撑', '覆盖率', 'Trust Layer', '准备答辩', '矛盾', '分数']
check(
  '报告页与面板不含禁用措辞',
  FORBIDDEN.every((word) => !reportSource.includes(word) && !panelSource.includes(word)),
  FORBIDDEN.filter((word) => reportSource.includes(word) || panelSource.includes(word)).join('、'),
)
check(
  '修复建议不出现结论判词（已满足/已支撑）',
  !reportSource.includes('已满足') && !reportSource.includes('已支撑') && !panelSource.includes('已满足') && !panelSource.includes('已支撑'),
)

const block = {
  id: 'blk_1',
  document_id: 'mat_x',
  ordinal: 0,
  text: '中文语料：准确率达到 95%，复现实验为 90%。',
  locator: { kind: 'line', index: 7, end_index: null, block_index: 1 },
}
const finding = {
  material_id: 'mat_x',
  kind: 'numeric_inconsistency',
  measure: '准确率',
  values: ['95%', '90%'],
  searched_block_count: 1,
  searched_statement_count: 2,
  explanation: '同一度量词「准确率」在本材料 2 处给出不同数值：95%、90%；请核对后决定以哪一处为准。',
  citations: [
    { block_id: 'blk_1', line_number: 7, quote: '95%', start: 11, end: 14, value: '95', unit: '%' },
    { block_id: 'blk_1', line_number: 7, quote: '90%', start: 21, end: 24, value: '90', unit: '%' },
  ],
}
const reportFixture = {
  material_id: 'mat_x',
  filename: 'ev.md',
  block_count: 1,
  rubric_id: 'rubric_syn',
  rubric_revision: 1,
  rubric_title: 'Synthetic rubric (test-only)',
  criteria: [],
  blocks: [block],
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/MaterialReportView.vue')
  const panelModule = await server.ssrLoadModule('/src/components/RepairSuggestionPanel.vue')

  async function mountView(fetchImpl) {
    globalThis.fetch = fetchImpl
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/materials/:materialId/report', component: module.default }],
    })
    await router.push('/materials/mat_x/report')
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return app
  }

  function mountPanel(fetchImpl, props) {
    globalThis.fetch = fetchImpl
    const app = createSSRApp(panelModule.default, props)
    app.provide(ssrContextKey, { modules: new Set() })
    return app.runWithContext(() => panelModule.default.setup(props, { expose() {} }))
  }

  async function renderPanel(fetchImpl, props) {
    globalThis.fetch = fetchImpl
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await router.push('/')
    await router.isReady()
    const app = createSSRApp(panelModule.default, props)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    return renderToString(app)
  }

  // 打开报告页：不发任何 POST；点按钮只选中该条问题（面板由它驱动）。
  {
    resetState()
    const app = await mountView(stubFetch({ report: reportFixture, findings: [finding] }))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('打开报告页不自动生成修复建议（零 POST）', state.repairPosts === 0, `repairPosts=${state.repairPosts}`)
    check('初始未选中任何待核对问题（面板不渲染）', bindings.repairFinding.value === null)
    bindings.openRepair(finding)
    check('点「生成修复建议」选中该条待核对问题', bindings.repairFinding.value !== null && toRaw(bindings.repairFinding.value) === finding)
  }

  // 面板挂载（= 点击后的实际效果）：POST 一次，body 为该条问题原文。
  {
    resetState()
    const panelBindings = mountPanel(stubFetch({}), { materialId: 'mat_x', finding })
    await flush()
    check('点击后面板发一次 repair-suggestions POST', state.repairPosts === 1, `repairPosts=${state.repairPosts}`)
    const repairCall = state.calls.find((call) => call.method === 'POST' && call.url.includes('/repair-suggestions'))
    check(
      'POST 指向该材料的 repair-suggestions',
      Boolean(repairCall) && repairCall.url.endsWith('/api/v1/materials/mat_x/repair-suggestions'),
      repairCall ? repairCall.url : '无 POST',
    )
    check(
      'POST body 是该条待核对问题原文',
      state.repairBodies.length === 1 && JSON.stringify(JSON.parse(state.repairBodies[0])) === JSON.stringify(finding),
    )
    check(
      '成功后展示建议与动作',
      panelBindings.suggestion.value?.suggestion === SUCCESS_BODY.suggestion &&
        panelBindings.suggestion.value?.action === '统一数值' &&
        panelBindings.error.value === '',
    )
    check(
      '除 repair-suggestions 外没有任何写请求（材料只读）',
      state.calls.every((call) => call.method === 'GET' || call.url.includes('/repair-suggestions')),
      state.calls.map((call) => `${call.method} ${call.url}`).join(' | '),
    )
  }

  // 面板未选中问题（页面初始态）：不发请求。
  {
    resetState()
    const idle = mountPanel(stubFetch({}), { materialId: 'mat_x', finding: null })
    await flush()
    check('未选中问题时面板不发请求', state.repairPosts === 0 && idle.suggestion.value === null && idle.error.value === '')
  }

  // 失败可见 + 重试：502 上游不可用 → 显示错误且不伪造建议；重试成功 → 展示建议并清错。
  {
    resetState()
    state.repairStatus = 502
    state.repairBody = { code: 'llm_unavailable', message: 'LLM 上游不可用', details: [] }
    const failing = mountPanel(stubFetch({}), { materialId: 'mat_x', finding })
    await flush()
    check(
      '失败可见：显示错误且不给建议',
      failing.error.value.includes('LLM 上游不可用') && failing.suggestion.value === null && state.repairPosts === 1,
      String(failing.error.value),
    )
    state.repairStatus = 200
    state.repairBody = SUCCESS_BODY
    failing.retry()
    await flush()
    check(
      '重试成功后展示建议并清除错误',
      failing.suggestion.value?.action === '统一数值' && failing.error.value === '' && state.repairPosts === 2,
      `repairPosts=${state.repairPosts}`,
    )
  }

  // 未配置 LLM：错误文案要可操作（配置后重试），不暴露原始机器串。
  {
    resetState()
    state.repairStatus = 503
    state.repairBody = { code: 'llm_unconfigured', message: '未配置 LLM（PREFLIGHT_LLM_BASE_URL/API_KEY/MODEL）', details: [] }
    const unconfigured = mountPanel(stubFetch({}), { materialId: 'mat_x', finding })
    await flush()
    check(
      '未配置 LLM 时给出可操作文案',
      unconfigured.error.value.includes('配置后重试') && unconfigured.suggestion.value === null,
      String(unconfigured.error.value),
    )
  }

  // 原文引用仍可点：面板 SSR 渲染两条引用；引用按钮 emit 已在源码层断言。
  {
    resetState()
    const html = await renderPanel(stubFetch({}), { materialId: 'mat_x', finding })
    check('面板渲染两条原文引用', html.includes('95%') && html.includes('90%'), html.slice(0, 120))
    check('面板渲染生成中状态（不伪造结果）', html.includes('正在生成修复建议'))
  }
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
