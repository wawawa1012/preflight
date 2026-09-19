// Iteration 6 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 报告页矩阵、缺失范围句、citation → Drawer 原文、409/404 导航不变量、措辞纪律。
// R0 增量：I7/I8 不依赖绑定（各自装、各自画，409 也显示）；待核对区块排在关键陈述之上；
// 顶栏「核验审查要求」才是唯一 POST 入口（进行中 I7/I8 不卸；material_too_large 只写在该行）；
// Drawer 标题统一走 locatorLabel（md 仍是「第 N 行」）。
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

// 请求记录 + 提案 POST 的可注入行为（核验评分要求）。
const state = {
  calls: [],
  proposals: 0,
  postedCriterionIds: [],
  defer: false,
  releases: [],
  failures: {},
}
const resetState = () => {
  state.calls = []
  state.proposals = 0
  state.postedCriterionIds = []
  state.defer = false
  state.releases = []
  state.failures = {}
}
const materialFetchCount = () => state.calls.filter((call) => /\/api\/v1\/materials\/[^/]+$/.test(call.url)).length

const proposalFixture = (criterionId) => ({
  id: `ap_${criterionId}`,
  material_id: 'mat_x',
  criterion_id: criterionId,
  rubric_id: 'rubric_syn',
  rubric_revision: 1,
  provider: 'test',
  model: 'test',
  prompt_version: 'p5-criterion-preflight-v2',
  status: 'completed',
  error: null,
  created_at: '2026-09-18T00:00:00+00:00',
  candidates: [],
})

function stubFetch(options = {}) {
  const {
    report: reportBody = null,
    reportStatus = 200,
    hangReport = false,
    proposals: proposalsBody = [],
    proposalsStatus = 200,
    signals: signalsBody = [],
    signalsStatus = 200,
    findings: findingsBody = [],
    findingsStatus = 200,
    material: materialBody = null,
  } = options
  return async (input, init = {}) => {
    const url = String(input)
    const method = (init && init.method) || 'GET'
    state.calls.push({ url, method })
    if (method === 'POST' && url.includes('/agent-proposals')) {
      state.proposals += 1
      const criterionId = init.body ? JSON.parse(init.body).criterion_id : ''
      state.postedCriterionIds.push(criterionId)
      const reply = () => {
        const failure = state.failures[criterionId]
        if (failure) return jsonResponse(failure.body, failure.status)
        return jsonResponse(proposalFixture(criterionId), 201)
      }
      if (state.defer) {
        return new Promise((resolve) => state.releases.push(() => resolve(reply())))
      }
      return reply()
    }
    if (url.includes('statement-signals')) return jsonResponse(signalsBody, signalsStatus)
    if (url.includes('consistency-findings')) return jsonResponse(findingsBody, findingsStatus)
    if (url.includes('agent-proposals')) return jsonResponse(proposalsBody, proposalsStatus)
    if (/\/api\/v1\/materials\/[^/]+$/.test(url)) return jsonResponse(materialBody ?? reportBody)
    if (hangReport) return new Promise(() => {})
    return jsonResponse(reportBody, reportStatus)
  }
}

// 旧签名包装：既有用例保持不动。
function reportFetch(reportBody, status = 200, proposalsBody = [], proposalStatus = 200, signalsBody = [], findingsBody = [], findingsStatus = 200) {
  return stubFetch({
    report: reportBody,
    reportStatus: status,
    proposals: proposalsBody,
    proposalsStatus: proposalStatus,
    signals: signalsBody,
    findings: findingsBody,
    findingsStatus,
  })
}

const reportSource = readFileSync(new URL('../src/views/MaterialReportView.vue', import.meta.url), 'utf8')
const drawerSource = readFileSync(new URL('../src/components/EvidenceDrawer.vue', import.meta.url), 'utf8')
const routerSource = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')

const FORBIDDEN = ['已满足', '已支撑', '覆盖率', 'Trust Layer', '准备答辩', '矛盾', '分数', '打分']
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
check('首屏主区标题为可见的「待处理问题」', reportSource.includes('>待处理问题</h2>'))
check(
  '待核对问题只给事实标签（数值不一致 / 待人工判断）',
  reportSource.includes('数值不一致') && reportSource.includes('待人工判断'),
)
check('待核对引用点回同一 Drawer', reportSource.includes('openHighlight(citation)'))
check('扫描逻辑不在 Vue（报告页无数字扫描正则）', !reportSource.includes('\\d'))
check('Drawer 位置标题统一走 locatorLabel（md 仍是「第 N 行」）', drawerSource.includes('原文 ·') && drawerSource.includes('locatorLabel'))
check('Drawer 渲染上下块并删掉 quote 重复行', drawerSource.includes('previousBlock') && drawerSource.includes('nextBlock') && !drawerSource.includes('quote：'))
check('路由登记 /materials/:materialId/report', routerSource.includes("'/materials/:materialId/report'"))
check('citation 展示 human/agent 溯源徽章', reportSource.includes('proposed_by'))
check(
  '报告页提供返回材料出口（非 history.back）',
  reportSource.includes('返回材料') && reportSource.includes('`/materials/${materialId}`') && !reportSource.includes('history.back'),
)
check(
  '未绑定/失败卡片各有独立回审查首页出口（to="/"，按钮文案「审查」）',
  (reportSource.match(/to="\/"/g) ?? []).length >= 3 && reportSource.includes('>审查</UButton>'),
  `to="/" 出现 ${(reportSource.match(/to="\/"/g) ?? []).length} 次`,
)
// 顶栏入口文案现为「核验审查要求」（旧「开始核验」退役；旧检索词「核验评分要求」仅存于视图注释）。
check('顶栏提供「核验审查要求」入口', reportSource.includes("{{ verifying ? '核验中…' : '核验审查要求' }}"))
// 审查团队条：头部之下、待处理问题之上；三个角色各报各自的事实来源（两条程序扫描、一条调用模型）。
// 核验中的依据核验行改口「正在按审查标准查找依据」，不与已确认计数同时出现。
check(
  '审查团队条：三个角色齐备且排在待处理问题之上（依据核验 / 一致性审查 / 关键陈述审查）',
  reportSource.includes('审查团队') &&
    reportSource.includes('依据核验') &&
    reportSource.includes('一致性审查') &&
    reportSource.includes('关键陈述审查') &&
    reportSource.includes('正在按审查标准查找依据') &&
    reportSource.indexOf('>审查团队</h2>') > reportSource.indexOf('>本次核验</p>') &&
    reportSource.indexOf('>审查团队</h2>') < reportSource.indexOf('>待处理问题</h2>'),
  `团队@${reportSource.indexOf('>审查团队</h2>')} 待处理@${reportSource.indexOf('>待处理问题</h2>')}`,
)
check(
  '报告页提供「与另一份材料对照」出口（to="/compare"，已从顶栏移入待处理问题区块）',
  reportSource.includes('与另一份材料对照') && reportSource.includes('to="/compare"'),
)
check(
  '报告页不做 accept（无候选物化端点）',
  !reportSource.includes('proposal-candidates') && !reportSource.includes('/accept'),
)
// 注：审查团队条含「关键陈述审查」字样，锚点用关键陈述 h2，避免被条上文案抢先命中。
check(
  '待核对区块排在关键陈述之上',
  reportSource.includes('待核对问题') &&
    reportSource.includes('>关键陈述</h2>') &&
    reportSource.indexOf('待核对问题') < reportSource.indexOf('>关键陈述</h2>'),
  `待核对@${reportSource.indexOf('待核对问题')} 关键陈述h2@${reportSource.indexOf('>关键陈述</h2>')}`,
)
check(
  '评分要求矩阵排在关键陈述之上（v-for="row in report.criteria" 先于关键陈述 h2）',
  reportSource.indexOf('v-for="row in report.criteria"') > -1 &&
    reportSource.indexOf('v-for="row in report.criteria"') < reportSource.indexOf('>关键陈述</h2>'),
  `criteria@${reportSource.indexOf('v-for="row in report.criteria"')} 关键陈述h2@${reportSource.indexOf('>关键陈述</h2>')}`,
)
// 首屏 IA（finding-first）：待处理问题区块恒显（不再按条数门控），关键陈述保留自身 v-if；二者都不挂 loading。
const findingsBlock = reportSource.slice(
  reportSource.indexOf('<!-- I8 待核对问题'),
  reportSource.indexOf('<!-- 修复建议'),
)
const signalsBlock = reportSource.slice(
  reportSource.indexOf('<!-- 关键陈述'),
  reportSource.indexOf('</section>', reportSource.indexOf('<!-- 关键陈述')),
)
check(
  '材料级区块不再按条数门控（findings 恒显、signals 只看自己，二者都不挂 loading）',
  findingsBlock.length > 0 &&
    !findingsBlock.includes('findings.length > 0') &&
    !findingsBlock.includes('v-if="loading"') &&
    signalsBlock.includes('v-if="(signalsUnavailable || signals.length > 0) && !notFound"') &&
    !signalsBlock.includes('v-if="loading"'),
)
// Phase 2：修复建议面板不再悬在列表下方，而是挂在被选中的那条问题卡片内部。
// 注：'RepairSuggestionPanel' 首次出现是顶部 import，故断言用模板标签 '<RepairSuggestionPanel'；
// 上界取关键陈述 h2 —— 源码里「关键陈述」字样在更早的区块注释中也出现过。
check(
  '修复建议面板嵌在待核对条目内部（v-for 之后、关键陈述区块之前）',
  reportSource.indexOf('v-for="finding in findings"') > -1 &&
    reportSource.indexOf('<RepairSuggestionPanel') > reportSource.indexOf('v-for="finding in findings"') &&
    reportSource.indexOf('<RepairSuggestionPanel') < reportSource.indexOf('>关键陈述</h2>'),
  `v-for@${reportSource.indexOf('v-for="finding in findings"')} 面板@${reportSource.indexOf('<RepairSuggestionPanel')} 关键陈述@${reportSource.indexOf('>关键陈述</h2>')}`,
)
check(
  '装配中只留一行状态（v-if="loading" 不再是整卡 UCard，材料级区块先画）',
  reportSource.includes('v-if="loading"') &&
    reportSource.includes('正在读取审查要求…') &&
    !reportSource.includes('<UCard v-if="loading"'),
)
check('核验失败只落在该行（行级 rowError）', reportSource.includes('rowError'))
// Phase 3：逐条核验的行内状态 + 报告分支小标题；待处理问题区块仍不随核验/装载卸下。
check(
  '每条评分要求行显示本条核验状态（verifyingIds.includes → 本条核验中…）',
  reportSource.includes('verifyingIds.includes(row.criterion_id)') && reportSource.includes('本条核验中…'),
)
check(
  '报告分支含「审查要求进度」小标题且排在 criteria 矩阵之上',
  reportSource.includes('>审查要求进度</h2>') &&
    reportSource.indexOf('>审查要求进度</h2>') < reportSource.indexOf('v-for="row in report.criteria"'),
  `进度h2@${reportSource.indexOf('>审查要求进度</h2>')} criteria@${reportSource.indexOf('v-for="row in report.criteria"')}`,
)
check(
  '待处理问题区块不随核验/装载卸下（区块内无 verifying 门控）',
  findingsBlock.length > 0 && !findingsBlock.includes('verifying'),
)
// P1：待核对空态是单一文案块 —— 两句话同段，findings.length === 0 只出现一次。
const emptyFindingsCopy =
  '当前范围尚未发现待核对问题（同一材料内同一度量词的不同数字）。跨材料的数字对照在「与另一份材料对照」。'
check(
  '待核对空态为单一块（两句话同段、findings.length === 0 仅一次）',
  reportSource.includes(emptyFindingsCopy) && (reportSource.match(/findings\.length === 0/g) ?? []).length === 1,
  `空态 v-else-if 数=${(reportSource.match(/findings\.length === 0/g) ?? []).length}`,
)
// Phase 4：cockpit 文案去术语 —— 候选入口说人话、未绑定卡片不提 Block、rubric/范围行改「段原文」。
check(
  '候选入口文案为「去确认这些依据」且仍指回材料页',
  reportSource.includes('>去确认这些依据</RouterLink>') &&
    reportSource.includes('<RouterLink :to="`/materials/${materialId}`"') &&
    !reportSource.includes('去材料页审核候选'),
)
check(
  '未绑定卡片：待处理问题来自材料原文，不需要先懂标注',
  reportSource.includes('上面的待处理问题来自材料原文，不需要先懂标注。绑定评分标准后才能按条核验。'),
)
check(
  '报告页对用户不再说「个 Block」（rubric/范围行均为「段原文」）',
  reportSource.includes('段原文') && !reportSource.includes('个 Block'),
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
  '当前范围尚未发现引用：已核对材料「ev.md」的 1 段原文上全部已确认关联，本评分要求已关联 0 条。这不是证明材料外不存在证据。'
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
    check(
      '正常态 SSR 含回审查首页出口（按钮文案「审查」）',
      html.includes('href="/"') && html.includes('审查</'),
      html.slice(Math.max(0, html.indexOf('href="/"') - 40), html.indexOf('href="/"') + 60),
    )
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    const byId = Object.fromEntries(bindings.report.value.criteria.map((row) => [row.criterion_id, row]))
    check(
      '行状态：一行为 has_verified_citations、一行为 no_verified_citations_in_scope',
      byId.c_syn_1.status === 'has_verified_citations' && byId.c_syn_2.status === 'no_verified_citations_in_scope',
    )
    check('有引用行计数为 1 且 quote/line 正确', byId.c_syn_1.verified_citation_count === 1 && byId.c_syn_1.citations[0].line_number === 7 && byId.c_syn_1.citations[0].quote === '准确率达到 95%')
    check('零引用行 missing 说明含文件名与段原文数', byId.c_syn_2.missing.explanation.includes('ev.md') && byId.c_syn_2.missing.explanation.includes('1 段原文'))
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
        '同一度量词「准确率」在本材料 2 处给出不同数值：95%、90%；已扫描 1 段原文的 2 条关键陈述，请核对后决定以哪一处为准。',
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

  // 409 未绑定：不画矩阵，仍有回审查首页的出口。
  {
    const { app } = await mount(async () =>
      jsonResponse({ code: 'rubric_not_bound', message: '该材料尚未绑定评分标准', details: [] }, 409),
    )
    const html = await renderToString(app)
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('409 进入未绑定态且不渲染矩阵', bindings.unbound.value === true && bindings.report.value === null)
    check('409 SSR 仍有回审查首页出口（按钮文案「审查」）', html.includes('href="/"') && html.includes('审查</'))
    check('409 提供去材料详情绑定的入口', reportSource.includes('尚未绑定评分标准') && reportSource.includes('`/materials/${materialId}`'))
  }

  // 404：与详情页一致的 notFound，保留回审查首页的出口。
  {
    const { app } = await mount(async () =>
      jsonResponse({ code: 'material_not_found', message: '找不到该材料', details: [] }, 404),
    )
    const html = await renderToString(app)
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('404 进入 notFound 且不渲染矩阵', bindings.notFound.value === true && bindings.report.value === null)
    check('404 SSR 仍有回审查首页出口（按钮文案「审查」）', html.includes('href="/"') && html.includes('审查</'))
  }
  // ——— R0：材料级 GET 不依赖绑定 ———
  // 共用数据：一条关键陈述、一条待核对问题、材料本体（供绑定前补取 blocks）。
  const r0Signal = {
    block_id: 'blk_1',
    line_number: 7,
    quote: '准确率达到 95%',
    start: 5,
    end: 14,
    signal: 'percentage',
  }
  const r0Finding = {
    material_id: 'mat_x',
    kind: 'numeric_inconsistency',
    measure: '准确率',
    values: ['95%', '90%'],
    searched_block_count: 1,
    searched_statement_count: 2,
    explanation:
      '同一度量词「准确率」在本材料 2 处给出不同数值：95%、90%；已扫描 1 段原文的 2 条关键陈述，请核对后决定以哪一处为准。',
    citations: [
      { block_id: 'blk_1', line_number: 7, quote: '95%', start: 5, end: 8, value: '95', unit: '%' },
      { block_id: 'blk_1', line_number: 7, quote: '90%', start: 12, end: 15, value: '90', unit: '%' },
    ],
  }
  const materialPayload = {
    id: 'mat_x',
    filename: 'ev.md',
    size_bytes: 42,
    sha256: 'a'.repeat(64),
    line_count: 1,
    created_at: '2026-09-16T00:00:00+00:00',
    blocks: [block],
  }

  // 报告还在装配：I7/I8 已经到手并可直接渲染，且首次进入不发 POST。
  {
    resetState()
    const { app } = await mount(stubFetch({ hangReport: true, signals: [r0Signal], findings: [r0Finding] }))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '报告装配中：signals + findings 已到手（不等 4 个请求）',
      bindings.signals.value.length === 1 &&
        bindings.findings.value.length === 1 &&
        bindings.report.value === null &&
        bindings.loading.value === true,
    )
    check('首次进入不发任何 POST', state.proposals === 0, `proposals=${state.proposals}`)
  }

  // 409 未绑定：I7/I8 照常显示 +「去绑定」出口；点击仍能开 Drawer（blocks 由材料端点补取）。
  {
    resetState()
    const { app } = await mount(
      stubFetch({
        report: { code: 'rubric_not_bound', message: '该材料尚未绑定评分标准', details: [] },
        reportStatus: 409,
        signals: [r0Signal],
        findings: [r0Finding],
        material: materialPayload,
      }),
    )
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      '409 仍显示 signals + findings 且进入未绑定态',
      bindings.unbound.value === true &&
        bindings.signals.value.length === 1 &&
        bindings.findings.value.length === 1 &&
        bindings.report.value === null,
    )
    await bindings.openHighlight(bindings.signals.value[0])
    await flush()
    check(
      '409 点击关键陈述仍能开 Drawer（补取材料 blocks，只取一次）',
      bindings.drawerOpen.value === true &&
        bindings.drawerBlock.value?.id === 'blk_1' &&
        materialFetchCount() === 1,
      `material=${materialFetchCount()}`,
    )
  }

  // 顶栏「核验审查要求」= 唯一 POST 入口；进行中 I7/I8 不卸。
  {
    resetState()
    const { app } = await mount(stubFetch({ report, signals: [r0Signal], findings: [r0Finding] }))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check('装配完成后仍未 POST（核验要人点）', state.proposals === 0, `proposals=${state.proposals}`)

    state.defer = true
    const running = bindings.verifyCriteria()
    await flush()
    check(
      '核验进行中：verifying=true 且 I7/I8 数据不卸',
      bindings.verifying.value === true &&
        bindings.signals.value.length === 1 &&
        bindings.findings.value.length === 1 &&
        bindings.report.value !== null,
    )
    check(
      '核验进行中：每条在跑的 criterion 都在 verifyingIds（行内「本条核验中…」有据可依）',
      bindings.verifyingIds.value.includes('c_syn_1') && bindings.verifyingIds.value.includes('c_syn_2'),
      bindings.verifyingIds.value.join(','),
    )
    state.defer = false
    state.releases.splice(0).forEach((release) => release())
    await running
    check(
      '核验按每条 criterion 各 POST 一次（body 带 criterion_id）',
      state.proposals === report.criteria.length && state.postedCriterionIds.slice().sort().join(',') === 'c_syn_1,c_syn_2',
      state.postedCriterionIds.join(','),
    )
    check(
      '核验完成后恢复且无行级错误',
      bindings.verifying.value === false && Object.keys(bindings.rowError.value).length === 0,
    )
  }

  // material_too_large：只写在该行，不升级为整页错误。
  {
    resetState()
    state.failures = {
      c_syn_1: {
        status: 400,
        body: { code: 'material_too_large', message: '材料内容超出单次核验上限', details: ['上限 24000 字符'] },
      },
    }
    const { app } = await mount(stubFetch({ report }))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    await bindings.verifyCriteria()
    check(
      'material_too_large 只落在该行',
      String(bindings.rowError.value.c_syn_1 ?? '').includes('材料超出单次核验上限') &&
        bindings.rowError.value.c_syn_2 === undefined &&
        bindings.error.value === '' &&
        state.proposals === report.criteria.length,
      JSON.stringify(bindings.rowError.value),
    )
  }

  // 未绑定：核验入口不发请求。
  {
    resetState()
    const { app } = await mount(
      stubFetch({ report: { code: 'rubric_not_bound', message: '该材料尚未绑定评分标准', details: [] }, reportStatus: 409 }),
    )
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    await bindings.verifyCriteria()
    check('未绑定时核验入口不发请求', state.proposals === 0 && bindings.verifying.value === false)
  }

  // locatorLabel：四种 Locator kind + 兜底；Drawer 标题按 kind 走（md 仍是「第 N 行」）。
  {
    const locatorModule = await server.ssrLoadModule('/src/utils/locatorLabel.ts')
    const label = locatorModule.locatorLabel
    check(
      'locatorLabel：line/slide/page/paragraph 各自成句',
      label({ kind: 'line', index: 3 }) === '第 3 行' &&
        label({ kind: 'slide', index: 3 }) === '第 3 张幻灯片' &&
        label({ kind: 'page', index: 3 }) === '第 3 页' &&
        label({ kind: 'paragraph', index: 3 }) === '第 3 段',
      [label({ kind: 'line', index: 3 }), label({ kind: 'slide', index: 3 })].join(' / '),
    )
    check(
      'locatorLabel：缺 Locator 时给兜底文案',
      typeof label(null) === 'string' && label(null).length > 0 && !label(null).includes('第 '),
      label(null),
    )

    const slideBlock = { ...block, locator: { kind: 'slide', index: 4, end_index: null, block_index: 2 } }
    const slideContext = {}
    const slideRouter = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await slideRouter.push('/')
    await slideRouter.isReady()
    const slideApp = createSSRApp({
      render: () =>
        h(drawerModule.default, {
          open: true,
          highlight: { line_number: 4, start: 0, end: 4 },
          block: slideBlock,
          filename: 'deck.md',
          portal: false,
          unmountOnHide: false,
        }),
    })
    slideApp.use(slideRouter)
    const slideHtml = await renderToString(slideApp, slideContext)
    const slideText = slideHtml + Object.values(slideContext.teleports ?? {}).join('')
    check('Drawer 标题按 locator 类型变化（slide → 第 4 张幻灯片）', slideText.includes('原文 · 第 4 张幻灯片'))
  }

  // 引用/信号行的位置文案：待核对引用 / 关键陈述 / 矩阵引用三类行不再写死「line N」，
  // 位置说法由该 Block 的 Locator 决定（md 仍读行号，slide/page/paragraph 各自成句）。
  {
    check(
      '引用/信号行不再写死 line N',
      !reportSource.includes('line {{') && !reportSource.includes('· line '),
      reportSource.includes('line {{') || reportSource.includes('· line ') ? '仍有 line {{…}} / · line' : '无',
    )
    check(
      '报告页引入 locatorLabel 决定行位置说法',
      reportSource.includes("from '../utils/locatorLabel'") && reportSource.includes('locatorLabel('),
    )
    check(
      '三类引用行共用同一位置助手（待核对 2 处 + 关键陈述 1 处）',
      (reportSource.match(/rowLocation\(citation\.block_id, citation\.line_number\)/g) ?? []).length === 2 &&
        reportSource.includes('rowLocation(signal.block_id, signal.line_number)'),
      `citation 行=${(reportSource.match(/rowLocation\(citation\.block_id, citation\.line_number\)/g) ?? []).length}`,
    )
    check(
      '视图源码不写死位置字面（第 N … 一律走 locatorLabel）',
      !/第\s*(\d|N|\{\{|\$\{)/.test(reportSource),
      (reportSource.match(/第\s*(\d|N|\{\{|\$\{)/) ?? ['无'])[0],
    )

    resetState()
    const { app } = await mount(stubFetch({ report }))
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      'md 引用行位置 = 第 7 行（按 Block.locator，而非写死行号）',
      bindings.rowLocation?.('blk_1', 7) === '第 7 行',
      String(bindings.rowLocation?.('blk_1', 7)),
    )
    check(
      'Block 未到手时退回行号（line_number 即 locator.index，位置不丢）',
      bindings.rowLocation?.('blk_missing', 7) === '第 7 行',
      String(bindings.rowLocation?.('blk_missing', 7)),
    )

    const slideRowBlock = { ...block, id: 'blk_slide', locator: { kind: 'slide', index: 4, end_index: null, block_index: 2 } }
    const slideRowMount = await mount(stubFetch({ report: { ...report, blocks: [slideRowBlock] } }))
    const slideRowBindings = slideRowMount.app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    check(
      'slide 材料的引用行位置 = 第 4 张幻灯片（不进「行」分支）',
      slideRowBindings.rowLocation?.('blk_slide', 4) === '第 4 张幻灯片',
      String(slideRowBindings.rowLocation?.('blk_slide', 4)),
    )
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
