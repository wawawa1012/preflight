// Iteration 6 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 报告页矩阵、缺失范围句、citation → Drawer 原文、409/404 导航不变量、措辞纪律。
// 运行：cd frontend && node scripts/check-preflight-report.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp, h } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

function reportFetch(reportBody, status = 200, proposalsBody = [], proposalStatus = 200, signalsBody = [], findingsBody = [], findingsStatus = 200) {
  return async (input) => {
    const url = String(input)
    if (url.includes('statement-signals')) return jsonResponse(signalsBody)
    if (url.includes('consistency-findings')) return jsonResponse(findingsBody, findingsStatus)
    if (url.includes('agent-proposals')) return jsonResponse(proposalsBody, proposalStatus)
    return jsonResponse(reportBody, status)
  }
}

const reportSource = readFileSync(new URL('../src/views/MaterialReportView.vue', import.meta.url), 'utf8')
const drawerSource = readFileSync(new URL('../src/components/EvidenceDrawer.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')

const FORBIDDEN = ['已满足', '已支撑', '覆盖率', 'Trust Layer', '准备答辩', '矛盾', '分数']
check(
  '报告页源码不含禁用措辞',
  FORBIDDEN.every((word) => !reportSource.includes(word)),
  FORBIDDEN.filter((word) => reportSource.includes(word)).join('、'),
)
check('Drawer 使用 USlideover', drawerSource.includes('USlideover'))
check('报告页标签为「已确认关联」且不再用「已核证」', reportSource.includes('已确认关联') && !reportSource.includes('已核证'))
check('空预检文案在报告源码中', reportSource.includes('预检完成 · 当前材料尚未发现候选引用'))
check('有确认关联的空预检文案在报告源码中', reportSource.includes('本次未提出新候选'))
check('报告组合 agent-proposals', reportSource.includes('agent-proposals'))
check('正交：待审核与已确认可同时出现在模板', reportSource.includes('已发现') && reportSource.includes('已确认关联'))
check('引用行标注「原文已校验」', reportSource.includes('原文已校验'))
check('报告页含关键陈述栏目', reportSource.includes('关键陈述'))
check('报告页请求 statement-signals', reportSource.includes('statement-signals'))
check('报告页请求 consistency-findings', reportSource.includes('consistency-findings'))
check('报告页含待核对问题栏目', reportSource.includes('待核对问题'))
check(
  '待核对问题只给事实标签（数值不一致 / 待人工判断）',
  reportSource.includes('数值不一致') && reportSource.includes('待人工判断'),
)
check('待核对引用点回同一 Drawer', reportSource.includes('openHighlight(citation)'))
check('扫描逻辑不在 Vue（报告页无数字扫描正则）', !reportSource.includes('\\d'))
check('Drawer 标题为「原文 · 第 N 行」', drawerSource.includes('原文 · 第'))
check('Drawer 渲染上下块并删掉 quote 重复行', drawerSource.includes('previousBlock') && drawerSource.includes('nextBlock') && !drawerSource.includes('quote：'))
check('路由登记 /materials/:materialId/report', routerSource.includes("'/materials/:materialId/report'"))
check('citation 展示 human/agent 溯源徽章', reportSource.includes('proposed_by'))
check(
  '报告页提供返回材料出口（非 history.back）',
  reportSource.includes('返回材料') && reportSource.includes('`/materials/${materialId}`') && !reportSource.includes('history.back'),
)
check(
  '未绑定/失败卡片各有独立 Workbench 出口',
  (reportSource.match(/to="\/"/g) ?? []).length >= 3,
  `to="/" 出现 ${(reportSource.match(/to="\/"/g) ?? []).length} 次`,
)

const block = {
  id: 'blk_1',
  document_id: 'mat_x',
  ordinal: 0,
  text: '中文语料：准确率达到 95%，整体稳定。',
  locator: { kind: 'line', index: 7, end_index: null, block_index: 1 },
}
const citation = {
  link_id: 'cel_1',
  annotation_id: 'ev_1',
  criterion_id: 'c_syn_1',
  block_id: 'blk_1',
  line_number: 7,
  quote: '准确率达到 95%',
  rationale: '人工判断相关',
  proposed_by: 'human',
  start: 5,
  end: 14,
}
const missingExplanation =
  '当前范围尚未发现引用：已核对材料「ev.md」的 1 个 Block 上全部已确认关联，本评分要求已关联 0 条。这不是证明材料外不存在证据。'
const report = {
  material_id: 'mat_x',
  filename: 'ev.md',
  block_count: 1,
  rubric_id: 'rubric_syn',
  rubric_revision: 1,
  rubric_title: 'Synthetic rubric (test-only)',
  criteria: [
    {
      criterion_id: 'c_syn_1',
      title: 'Criterion A',
      requirement: 'requirement A',
      verified_citation_count: 1,
      status: 'has_verified_citations',
      citations: [citation],
      missing: null,
    },
    {
      criterion_id: 'c_syn_2',
      title: 'Criterion B',
      requirement: 'requirement B',
      verified_citation_count: 0,
      status: 'no_verified_citations_in_scope',
      citations: [],
      missing: { searched_block_count: 1, searched_filename: 'ev.md', explanation: missingExplanation },
    },
  ],
  blocks: [block],
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/MaterialReportView.vue')
  const drawerModule = await server.ssrLoadModule('/src/components/EvidenceDrawer.vue')

  async function mount(fetchImpl) {
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
    return { app }
  }

  // 正常态：一行有引用，一行带范围句。
  {
    const { app } = await mount(reportFetch(report))
    const html = await renderToString(app)
    check('正常态 SSR 含 Workbench 出口', html.includes('href="/"') && html.includes('Workbench'))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    const byId = Object.fromEntries(bindings.report.value.criteria.map((row) => [row.criterion_id, row]))
    check(
      '行状态：一行为 has_verified_citations、一行为 no_verified_citations_in_scope',
      byId.c_syn_1.status === 'has_verified_citations' && byId.c_syn_2.status === 'no_verified_citations_in_scope',
    )
    check('有引用行计数为 1 且 quote/line 正确', byId.c_syn_1.verified_citation_count === 1 && byId.c_syn_1.citations[0].line_number === 7 && byId.c_syn_1.citations[0].quote === '准确率达到 95%')
    check('零引用行 missing 说明含文件名与 Block 数', byId.c_syn_2.missing.explanation.includes('ev.md') && byId.c_syn_2.missing.explanation.includes('1 个 Block'))
    check(
      '零引用行源码用正交预检文案而非灰徽章独占',
      reportSource.includes('预检完成 · 当前材料尚未发现候选引用') && reportSource.includes('emptyPreflight'),
    )

    bindings.openCitation(byId.c_syn_1.citations[0])
    check(
      '点击 citation 后 Drawer 打开且带上高亮范围',
      bindings.drawerOpen.value === true &&
        bindings.highlight.value.start === 5 &&
        bindings.highlight.value.end === 14 &&
        bindings.drawerBlock.value.id === 'blk_1',
    )
    // reka-ui 的 Teleport 仅在挂载后或 forceMount 时渲染；SSR 检视时用 fallthrough props 强制内联渲染。
    const drawerContext = {}
    const drawerRouter = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await drawerRouter.push('/')
    await drawerRouter.isReady()
    const drawerApp = createSSRApp({
      render: () =>
        h(drawerModule.default, {
          open: true,
          highlight: { line_number: 7, start: 5, end: 14 },
          block,
          previousBlock: { ...block, id: 'blk_0', text: '上一行：项目简介。' },
          nextBlock: { ...block, id: 'blk_2', text: '下一行：结论。' },
          filename: 'ev.md',
          portal: false,
          unmountOnHide: false,
        }),
    })
    drawerApp.use(drawerRouter)
    const drawerHtml = await renderToString(drawerApp, drawerContext)
    // USlideover 走 Teleport：SSR 内容在 teleports 桶里，不在主 HTML。
    const teleported = Object.values(drawerContext.teleports ?? {}).join('')
    const drawerText = drawerHtml + teleported
    check(
      'Drawer 标题为「原文 · 第 7 行」并含高亮 quote',
      drawerText.includes('原文 · 第 7 行') && drawerText.includes('准确率达到 95%'),
      (teleported || drawerHtml).slice(0, 200),
    )
    check(
      'Drawer 含上下块原文且不再重复 quote：行',
      drawerText.includes('上一行：项目简介。') && drawerText.includes('下一行：结论。') && !drawerText.includes('quote：'),
    )
  }

  // 关键陈述：报告只渲染 statement-signals，点击开 Drawer。
  {
    const signal = {
      block_id: 'blk_1',
      line_number: 7,
      quote: '准确率达到 95%',
      start: 5,
      end: 14,
      signal: 'percentage',
    }
    const { app } = await mount(reportFetch(report, 200, [], 200, [signal]))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '关键陈述来自 statement-signals 且带 kind',
      bindings.signals.value.length === 1 && bindings.signals.value[0].signal === 'percentage',
    )
    check('关键陈述文案映射为中文 kind', bindings.signalLabel('percentage') === '比例')
    bindings.openHighlight(bindings.signals.value[0])
    check(
      '点击关键陈述打开同一 Drawer',
      bindings.drawerOpen.value === true && bindings.highlight.value.quote === undefined && bindings.drawerBlock.value.id === 'blk_1',
    )
  }

  // I8 待核对问题：只渲染后端结论（前端不扫描），引用点回同一 Drawer。
  {
    const finding = {
      material_id: 'mat_x',
      kind: 'numeric_inconsistency',
      measure: '准确率',
      values: ['95%', '90%'],
      searched_block_count: 1,
      searched_statement_count: 2,
      explanation:
        '同一度量词「准确率」在本材料 2 处给出不同数值：95%、90%；已扫描 1 个 Block 的 2 条关键陈述，请核对后决定以哪一处为准。',
      citations: [
        { block_id: 'blk_1', line_number: 7, quote: '95%', start: 5, end: 8, value: '95', unit: '%' },
        { block_id: 'blk_1', line_number: 7, quote: '90%', start: 12, end: 15, value: '90', unit: '%' },
      ],
    }
    const { app } = await mount(reportFetch(report, 200, [], 200, [], [finding]))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '待核对问题来自 consistency-findings 且带度量词',
      bindings.findings.value.length === 1 &&
        bindings.findings.value[0].measure === '准确率' &&
        bindings.findings.value[0].values.join(',') === '95%,90%',
    )
    check(
      '待核对问题标签映射为「数值不一致 / 待人工判断」',
      bindings.findingLabel('numeric_inconsistency') === '数值不一致' && bindings.findingLabel('needs_review') === '待人工判断',
    )
    bindings.openHighlight(bindings.findings.value[0].citations[1])
    check(
      '点待核对引用打开 Drawer 并带该引用高亮',
      bindings.drawerOpen.value === true &&
        bindings.highlight.value.start === 12 &&
        bindings.highlight.value.end === 15 &&
        bindings.drawerBlockId.value === 'blk_1',
    )
  }

  // I8 端点不可用：栏目降级为「不可用」，不炸页面、不伪造结论。
  {
    const { app } = await mount(reportFetch(report, 200, [], 200, [], [], 502))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '待核对问题不可用时标记 unavailable 且不渲染条目',
      bindings.findingsUnavailable.value === true && bindings.findings.value.length === 0 && bindings.report.value !== null,
    )
  }

  const emptyProposal = {
    id: 'ap_empty',
    material_id: 'mat_x',
    criterion_id: 'c_syn_2',
    rubric_id: 'rubric_syn',
    rubric_revision: 1,
    provider: 'test',
    model: 'test',
    prompt_version: 'p5-criterion-preflight-v2',
    status: 'completed',
    error: null,
    created_at: '2026-09-18T00:00:00+00:00',
    candidates: [],
  }
  const pendingCandidate = (id) => ({
    id,
    proposal_id: 'ap_mix',
    ordinal: 0,
    block_id: 'blk_1',
    quote: '准确率达到 95%',
    rationale: '相关',
    risk_note: null,
    validation_status: 'passed',
    validation_code: null,
    review_status: 'unreviewed',
    reject_reason: null,
    created_annotation_id: null,
    created_link_id: null,
    created_at: '2026-09-18T00:00:00+00:00',
  })

  {
    const emptyReport = { ...report, criteria: [report.criteria[1]] }
    const { app } = await mount(reportFetch(emptyReport, 200, [emptyProposal]))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '空预检：completed 且无 passed 候选',
      bindings.emptyPreflight('c_syn_2') === true && bindings.neverPreflighted('c_syn_2') === false,
    )
    check(
      '空预检范围来自报告 filename 与 block_count',
      bindings.report.value.filename === 'ev.md' && bindings.report.value.block_count === 1,
    )
  }

  {
    // 已有确认关联的同一行再次空预检：状态并存，模板改写为「本次未提出新候选」。
    const confirmedReport = { ...report, criteria: [report.criteria[0]] }
    const confirmedEmpty = { ...emptyProposal, criterion_id: 'c_syn_1' }
    const { app } = await mount(reportFetch(confirmedReport, 200, [confirmedEmpty]))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '有确认关联的空预检：confirmed>0 且 emptyPreflight 为真',
      bindings.emptyPreflight('c_syn_1') === true && bindings.report.value.criteria[0].verified_citation_count === 1,
    )
  }

  {
    const mixProposal = {
      ...emptyProposal,
      id: 'ap_mix',
      criterion_id: 'c_syn_1',
      candidates: [pendingCandidate('apc_1'), pendingCandidate('apc_2')],
    }
    const { app } = await mount(reportFetch(report, 200, [mixProposal]))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '已确认关联与待审核正交共存',
      bindings.report.value.criteria[0].verified_citation_count === 1 && bindings.pendingFor('c_syn_1') === 2,
    )
  }

  // 409 未绑定：不画矩阵，仍有 Workbench 出口。
  {
    const { app } = await mount(async () =>
      jsonResponse({ code: 'rubric_not_bound', message: '该材料尚未绑定评分标准', details: [] }, 409),
    )
    const html = await renderToString(app)
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('409 进入未绑定态且不渲染矩阵', bindings.unbound.value === true && bindings.report.value === null)
    check('409 SSR 仍有 Workbench 出口', html.includes('href="/"') && html.includes('Workbench'))
    check('409 提供去材料详情绑定的入口', reportSource.includes('尚未绑定评分标准') && reportSource.includes('`/materials/${materialId}`'))
  }

  // 404：与详情页一致的 notFound，保留 Workbench 出口。
  {
    const { app } = await mount(async () =>
      jsonResponse({ code: 'material_not_found', message: '找不到该材料', details: [] }, 404),
    )
    const html = await renderToString(app)
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('404 进入 notFound 且不渲染矩阵', bindings.notFound.value === true && bindings.report.value === null)
    check('404 SSR 仍有 Workbench 出口', html.includes('href="/"') && html.includes('Workbench'))
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
