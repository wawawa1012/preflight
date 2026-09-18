// Iteration 7.1 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 未绑定禁用 AI 预检、busy 互斥、invalid 候选可见且不可接受、accept 物化、409/400 文案、措辞纪律。
// 7.1 增量：已关联候选（与后端 duplicate_link 同判定）、批量「接受本条全部原文有效」、
// 「证据」/全文 Block 默认折叠、空预检「未发现」只留徽章一处。
// 合成 rubric/提案只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-agent-proposal.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const detailSource = readFileSync(new URL('../src/views/MaterialDetailView.vue', import.meta.url), 'utf8')

check('详情页不含“已满足/已支撑”措辞', !detailSource.includes('已满足') && !detailSource.includes('已支撑'))
check('存在 AI 预检按钮', detailSource.includes('AI 预检') || detailSource.includes('重新预检'))
check('不再使用「通过验证」徽章文案', !detailSource.includes('通过验证'))
check('候选徽章写「原文引用有效」', detailSource.includes('原文引用有效'))
check(
  '预检 guard 只看绑定与同条重复（不吃全局 busy）',
  detailSource.includes('!boundRubric.value || proposingIds.value.includes(criterion.id)'),
)
check('invalid 候选有醒目错误码徽章', detailSource.includes('无效：'))
check('接受按钮对非 passed 候选禁用', detailSource.includes("candidate.validation_status !== 'passed'"))
check('空预检主句不是「尚未关联引用」独占', detailSource.includes('预检完成 · 当前材料尚未发现候选引用'))
check('正交展示待审核与已确认关联', detailSource.includes('已发现') && detailSource.includes('已确认关联'))
check('标注 title 含手动圈一句', detailSource.includes('手动圈一句'))
check(
  '尚未关联引用仅用于尚未预检',
  detailSource.includes('!completedProposalFor(criterion.id)'),
)
check('评分标准区有「预检全部」', detailSource.includes('预检全部'))
check('预检按钮带本地秒表', detailSource.includes('正在预检…') && detailSource.includes('preflightSeconds'))
check('前端不含 max_tokens（封顶只在后端）', !detailSource.includes('max_tokens'))
check('空预检且已有关联时文案为「本次未提出新候选」', detailSource.includes('本次未提出新候选'))
check(
  '失败文案说人话且带再试',
  detailSource.includes('预检没有返回内容，点「重新预检」再试。') &&
    detailSource.includes('预检结果不完整，点「重新预检」再试。'),
)
check('禁止原生 confirm/alert', !detailSource.includes('window.confirm') && !detailSource.includes('window.alert'))
check('全已预检时按钮为「再预检全部」', detailSource.includes('再预检全部'))
check('顶栏显示预检进度而非整钮死转', detailSource.includes('preflightAllLabel'))
check('批量接受按钮文案为「接受本条全部原文有效」', detailSource.includes('接受本条全部原文有效'))
check(
  '「证据」与全文 Block 列表默认折叠',
  detailSource.includes('const evidenceOpen = ref(false)') && detailSource.includes('const blocksOpen = ref(false)'),
)
check(
  '两个折叠标题都可展开（aria-expanded 绑定 state）',
  detailSource.includes(':aria-expanded="evidenceOpen"') && detailSource.includes(':aria-expanded="blocksOpen"'),
)
check(
  '空预检「未发现」只在徽章出现一处（不写第三处）',
  (detailSource.match(/尚未发现/g) ?? []).length === 1 && (detailSource.match(/未发现/g) ?? []).length === 1,
)
check(
  '新增文案不含「没有发现/暂无」类缺席陈述',
  !detailSource.includes('没有发现') && !detailSource.includes('暂无'),
)

const blockOne = {
  id: 'blk_1',
  document_id: 'mat_x',
  ordinal: 0,
  text: '中文语料：准确率达到 95%，整体稳定。',
  locator: { kind: 'line', index: 7, end_index: null, block_index: 1 },
}
const MATERIAL = {
  id: 'mat_x',
  filename: 'ev.md',
  size_bytes: 42,
  sha256: 'a'.repeat(64),
  line_count: 1,
  created_at: '2026-09-16T00:00:00+00:00',
  blocks: [blockOne],
}
const RUBRIC = {
  id: 'rubric_syn',
  revision: 1,
  title: 'Synthetic rubric (test-only)',
  source_note: 'test-only synthetic',
  criteria: [
    { id: 'c_syn_1', title: 'Criterion A', requirement: 'requirement A', required_evidence: ['x'] },
    { id: 'c_syn_2', title: 'Criterion B', requirement: 'requirement B', required_evidence: ['y'] },
  ],
}
const BINDING = { material_id: 'mat_x', rubric_id: 'rubric_syn', rubric_revision: 1, created_at: '2026-09-16T00:00:00+00:00' }

function candidate(id, status, code = null, quote = '准确率达到 95%') {
  return {
    id,
    proposal_id: 'ap_1',
    ordinal: id === 'apc_1' ? 0 : 1,
    block_id: 'blk_1',
    quote,
    rationale: 'synthetic：可能相关',
    risk_note: null,
    validation_status: status,
    validation_code: code,
    review_status: 'unreviewed',
    reject_reason: null,
    created_annotation_id: null,
    created_link_id: null,
    created_at: '2026-09-16T00:00:00+00:00',
  }
}

// 已关联候选的判定基准：人工先关联的同一句原文（block_id + quote 与候选一致）。
const LINKED_ANNOTATION = {
  id: 'ev_manual_1',
  material_id: 'mat_x',
  block_id: 'blk_1',
  source: { block_id: 'blk_1', start: 5, end: 14, quote: '准确率达到 95%' },
  note: null,
  proposed_by: 'human',
  created_at: '2026-09-16T00:00:00+00:00',
}
const LINKED_LINK = {
  id: 'cel_manual_1',
  material_id: 'mat_x',
  annotation_id: 'ev_manual_1',
  rubric_id: 'rubric_syn',
  rubric_revision: 1,
  criterion_id: 'c_syn_1',
  rationale: 'synthetic：人工已关联',
  proposed_by: 'human',
  created_at: '2026-09-16T00:00:00+00:00',
}

function proposal(status = 'completed', candidates = [candidate('apc_1', 'passed'), candidate('apc_2', 'invalid', 'quote_not_found', '不存在的引用')]) {
  return {
    id: 'ap_1',
    material_id: 'mat_x',
    criterion_id: 'c_syn_1',
    rubric_id: 'rubric_syn',
    rubric_revision: 1,
    provider: 'stub',
    model: 'stub-model',
    prompt_version: 'p5-criterion-preflight-v1',
    status,
    error: status === 'failed' ? 'llm_timeout: LLM 请求超时' : null,
    created_at: '2026-09-16T00:00:00+00:00',
    candidates,
  }
}

const state = {
  binding: BINDING,
  proposals: [],
  annotations: [],
  links: [],
  proposeStatus: 201,
  proposeEmpty: false,
  proposeDefer: false,
  proposeReleases: [],
  proposeFailure: null,
  failCriterion: '',
  acceptStatus: 201,
  acceptDuplicateFor: '',
  acceptDefer: false,
  acceptReleases: [],
  rejectStatus: 200,
  counts: { propose: 0, accept: 0, reject: 0, linksGet: 0 },
}

function resetState() {
  state.binding = BINDING
  state.proposals = []
  state.annotations = []
  state.links = []
  state.proposeStatus = 201
  state.proposeEmpty = false
  state.proposeDefer = false
  state.proposeReleases = []
  state.proposeFailure = null
  state.failCriterion = ''
  state.acceptStatus = 201
  state.acceptDuplicateFor = ''
  state.acceptDefer = false
  state.acceptReleases = []
  state.rejectStatus = 200
  state.counts = { propose: 0, accept: 0, reject: 0, linksGet: 0 }
}

globalThis.fetch = async (url, options = {}) => {
  const target = String(url)
  const method = options.method ?? 'GET'
  if (method === 'GET' && target === '/api/v1/rubrics') return jsonResponse([RUBRIC])
  if (method === 'GET' && target.endsWith('/rubric-binding')) return jsonResponse(state.binding)
  if (method === 'GET' && target.endsWith('/evidence-annotations')) return jsonResponse(state.annotations)
  if (method === 'GET' && target.endsWith('/criterion-evidence-links')) {
    state.counts.linksGet += 1
    return jsonResponse(state.links)
  }
  if (method === 'GET' && target.endsWith('/agent-proposals')) return jsonResponse(state.proposals)
  if (method === 'GET' && target.startsWith('/api/v1/materials/')) return jsonResponse(MATERIAL)
  if (method === 'POST' && target.endsWith('/agent-proposals')) {
    state.counts.propose += 1
    const requested = options.body ? JSON.parse(options.body).criterion_id : ''
    const send = () => {
      if (state.proposeFailure) {
        return jsonResponse(
          { code: state.proposeFailure.code, message: state.proposeFailure.message, details: [] },
          state.proposeFailure.status,
        )
      }
      if (state.failCriterion === requested) {
        return jsonResponse({ code: 'llm_unavailable', message: '预检失败示例', details: [] }, 502)
      }
      if (state.proposeStatus === 201) {
        const created = {
          ...proposal('completed', state.proposeEmpty ? [] : undefined),
          id: `ap_${requested}`,
          criterion_id: requested,
        }
        state.proposals = [created, ...state.proposals]
        return jsonResponse(created, 201)
      }
      const code = state.proposeStatus === 503 ? 'llm_unconfigured' : 'llm_timeout'
      return jsonResponse({ code, message: '预检失败示例', details: [] }, state.proposeStatus)
    }
    if (state.proposeDefer) {
      return new Promise((resolve) => {
        state.proposeReleases.push(() => resolve(send()))
      })
    }
    return send()
  }
  if (method === 'POST' && target.includes('/proposal-candidates/') && target.endsWith('/accept')) {
    state.counts.accept += 1
    const candidateId = decodeURIComponent(target.split('/proposal-candidates/')[1].replace('/accept', ''))
    const send = () => {
      if (state.acceptDuplicateFor === candidateId) {
        return jsonResponse({ code: 'duplicate_link', message: '该原文已关联此评分要求', details: [] }, 409)
      }
      if (state.acceptStatus !== 201) {
        const code = state.acceptStatus === 400 ? 'invalid_candidate' : 'span_mismatch'
        return jsonResponse({ code, message: '接受失败示例', details: [] }, state.acceptStatus)
      }
      const owner = state.proposals.find((item) => item.candidates.some((entry) => entry.id === candidateId))
      const source = owner.candidates.find((entry) => entry.id === candidateId)
      const annotation = {
        id: `ev_${candidateId}`,
        material_id: 'mat_x',
        block_id: source.block_id,
        source: { block_id: source.block_id, start: 5, end: 14, quote: source.quote },
        note: null,
        proposed_by: 'agent',
        created_at: '2026-09-16T00:00:00+00:00',
      }
      const link = {
        id: `cel_${candidateId}`,
        material_id: 'mat_x',
        annotation_id: annotation.id,
        rubric_id: owner.rubric_id,
        rubric_revision: owner.rubric_revision,
        criterion_id: owner.criterion_id,
        rationale: source.rationale,
        proposed_by: 'agent',
        created_at: '2026-09-16T00:00:00+00:00',
      }
      state.annotations = [...state.annotations, annotation]
      state.links = [...state.links, link]
      state.proposals = state.proposals.map((item) => ({
        ...item,
        candidates: item.candidates.map((entry) =>
          entry.id === candidateId
            ? {
                ...entry,
                review_status: 'accepted',
                created_annotation_id: annotation.id,
                created_link_id: link.id,
              }
            : entry,
        ),
      }))
      return jsonResponse({ annotation, link }, 201)
    }
    if (state.acceptDefer) {
      return new Promise((resolve) => {
        state.acceptReleases.push(() => resolve(send()))
      })
    }
    return send()
  }
  if (method === 'POST' && target.includes('/proposal-candidates/') && target.endsWith('/reject')) {
    state.counts.reject += 1
    const candidateId = decodeURIComponent(target.split('/proposal-candidates/')[1].replace('/reject', ''))
    const reason = JSON.parse(options.body).reason
    state.proposals = state.proposals.map((item) => ({
      ...item,
      candidates: item.candidates.map((entry) =>
        entry.id === candidateId ? { ...entry, review_status: 'rejected', reject_reason: reason } : entry,
      ),
    }))
    const owner = state.proposals.find((item) => item.candidates.some((entry) => entry.id === candidateId))
    return jsonResponse(owner.candidates.find((entry) => entry.id === candidateId), state.rejectStatus)
  }
  throw new Error(`unexpected fetch: ${method} ${target}`)
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/MaterialDetailView.vue')

  async function mount() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/materials/:materialId', component: module.default }],
    })
    await router.push('/materials/mat_x')
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    await flush()
    return bindings
  }

  // 未绑定：runPreflight 不发请求。
  resetState()
  state.binding = null
  {
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    check('未绑定时 AI 预检被 guard 阻止（无请求）', state.counts.propose === 0)
    check('未绑定且无提案时面板为空', bindings.proposals.value.length === 0)
  }

  // 预检成功：候选包括 passed 与 invalid（含错误码）。
  resetState()
  {
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    check('预检成功后提案进入列表', bindings.proposals.value.length === 1 && state.counts.propose === 1)
    check(
      '预检成功提示含有效/无效计数',
      bindings.proposalNotice.value === '预检完成：原文引用有效 1 条，无效 1 条，待你判断是否关联',
      bindings.proposalNotice.value,
    )
    const candidates = bindings.latestProposalFor('c_syn_1').candidates
    check(
      'invalid 候选带机器码',
      candidates[1].validation_status === 'invalid' && candidates[1].validation_code === 'quote_not_found',
    )
  }

  // 空候选：正式文案（空结果正常），不是失败。
  resetState()
  {
    state.proposeEmpty = true
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    check(
      '空候选提示为「没有提出候选（空结果正常）」',
      bindings.proposalNotice.value === '预检完成：没有提出候选（空结果正常）',
      bindings.proposalNotice.value,
    )
  }

  // 已有 completed 历史：默认只展示，未点「重新预检」不发请求。
  resetState()
  {
    state.proposals = [proposal()]
    const bindings = await mount()
    check(
      '有历史时展示候选且不自动 POST',
      state.counts.propose === 0 && bindings.latestProposalFor('c_syn_1').status === 'completed',
    )
    check('有 completed 历史时按钮为「重新预检」', bindings.preflightButtonLabel('c_syn_1') === '重新预检')
    check('无历史时按钮为「AI 预检」', bindings.preflightButtonLabel('c_syn_2') === 'AI 预检')
  }

  // 互斥收窄：同一条重复点被忽略；不同 criterion 并行；accept 仍互斥。
  resetState()
  {
    const bindings = await mount()
    state.proposeDefer = true
    const first = bindings.runPreflight(RUBRIC.criteria[0])
    check('预检中 busy=true', bindings.busy.value === true)
    check('顶栏进度为「预检中 1/2」', bindings.preflightAllLabel() === '预检中 1/2', bindings.preflightAllLabel())
    check('秒表：预检中该条显示秒数', bindings.preflightSeconds('c_syn_1') >= 1)
    await bindings.runPreflight(RUBRIC.criteria[0])
    check('同一条 criterion 重复点击被忽略', state.proposeReleases.length === 1)
    const second = bindings.runPreflight(RUBRIC.criteria[1])
    check('另一条 criterion 可同时发起预检', state.proposeReleases.length === 2)
    await bindings.acceptCandidate(candidate('apc_1', 'passed'))
    check('预检进行中 accept 仍被拦截', state.counts.accept === 0, `accept=${state.counts.accept}`)
    state.proposeReleases.splice(0).forEach((release) => release())
    await Promise.all([first, second])
    check('并行两条各自入库', bindings.proposals.value.length === 2 && state.counts.propose === 2)
    check('预检完成后 busy=false', bindings.busy.value === false)
    check('预检完成后秒表清除', bindings.preflightSeconds('c_syn_1') === null)
  }

  // 预检全部：有界并行；失败一条不影响另一条。
  resetState()
  {
    const bindings = await mount()
    state.failCriterion = 'c_syn_2'
    await bindings.runPreflightAll()
    check('预检全部并发提交未预检的 2 条', state.counts.propose === 2, `propose=${state.counts.propose}`)
    check(
      '预检全部：失败一条不影响另一条',
      bindings.latestProposalFor('c_syn_1')?.status === 'completed' &&
        bindings.proposalError.value === '预检服务暂时不可用，点「重新预检」再试。',
      bindings.proposalError.value,
    )
  }

  // 全已预检：直接重跑，不再原生确认；按钮显示「再预检全部」。
  resetState()
  {
    state.proposals = [proposal(), { ...proposal(), id: 'ap_c_syn_2', criterion_id: 'c_syn_2' }]
    const bindings = await mount()
    check('全已预检时按钮为「再预检全部」', bindings.preflightAllLabel() === '再预检全部')
    await bindings.runPreflightAll()
    check('全已预检时直接重跑 2 条（无 confirm）', state.counts.propose === 2, `propose=${state.counts.propose}`)
  }

  // 失败人话：机器码不当主句。
  for (const [message, expected] of [
    ['响应内容为空', '预检没有返回内容，点「重新预检」再试。'],
    ['响应不是合法 JSON（Unterminated string）', '预检结果不完整，点「重新预检」再试。'],
  ]) {
    resetState()
    state.proposeFailure = { status: 502, code: 'llm_invalid_response', message }
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    check(`失败人话：${expected}`, bindings.proposalError.value === expected, bindings.proposalError.value)
  }

  // invalid 候选本地禁止接受；accept 成功物化并刷新提案。
  resetState()
  {
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    const invalid = bindings.latestProposalFor('c_syn_1').candidates[1]
    await bindings.acceptCandidate(invalid)
    check(
      'invalid 候选不可接受且不发请求',
      state.counts.accept === 0 && bindings.proposalError.value.includes('原文引用无效'),
      bindings.proposalError.value,
    )

    const passed = bindings.latestProposalFor('c_syn_1').candidates[0]
    await bindings.acceptCandidate(passed)
    check(
      'accept 物化 annotation 与 link（provenance=agent）',
      bindings.annotations.value.length === 1 &&
        bindings.annotations.value[0].proposed_by === 'agent' &&
        bindings.links.value.length === 1 &&
        bindings.links.value[0].proposed_by === 'agent',
    )
    check('accept 后候选状态刷新为 accepted', bindings.latestProposalFor('c_syn_1').candidates[0].review_status === 'accepted')
  }

  // 已与该 criterion 关联过的候选：显示「已关联」，禁止接受/拒绝，不写 duplicate_link 红字主句。
  resetState()
  {
    state.proposals = [
      proposal('completed', [
        candidate('apc_1', 'passed'),
        candidate('apc_2', 'passed', null, '整体稳定'),
        candidate('apc_3', 'invalid', 'quote_not_found', '不存在的引用'),
      ]),
    ]
    state.annotations = [LINKED_ANNOTATION]
    state.links = [LINKED_LINK]
    const bindings = await mount()
    const linked = bindings.latestProposalFor('c_syn_1').candidates[0]
    const fresh = bindings.latestProposalFor('c_syn_1').candidates[1]
    check('已关联候选被识别（与后端 duplicate_link 同判定）', bindings.candidateLinkedFor('c_syn_1', linked) === true)
    check('未关联候选不被误判为已关联', bindings.candidateLinkedFor('c_syn_1', fresh) === false)
    check('待审核徽章不计已关联候选', bindings.criterionPending('c_syn_1') === 1)
    check('已关联候选不在可接受集合内', bindings.acceptableCandidatesFor('c_syn_1').length === 1)

    await bindings.acceptCandidate(linked)
    check('已关联候选点接受不发请求', state.counts.accept === 0 && state.counts.linksGet === 1)
    check(
      '已关联候选点接受不写红字主句',
      bindings.proposalError.value === '' && bindings.proposalNotice.value.includes('已关联'),
      bindings.proposalNotice.value,
    )

    await bindings.acceptPassedFor('c_syn_1')
    check(
      '批量接受跳过已关联候选，只接受剩下的',
      state.counts.accept === 1 && bindings.annotations.value.length === 2 && bindings.links.value.length === 2,
      `accept=${state.counts.accept}`,
    )
    check(
      '批量接受提示按实际接受条数',
      bindings.proposalNotice.value === '已接受 1 条候选并物化为引用（agent）',
      bindings.proposalNotice.value,
    )
    check('已关联候选的 pending 不随批量消失（仍显示已关联）', bindings.candidateLinkedFor('c_syn_1', linked) === true)
  }

  // 批量接受：逐一接受 passed+unreviewed，invalid 跳过；完成后候选刷新且入口消失。
  resetState()
  {
    state.proposals = [
      proposal('completed', [
        candidate('apc_1', 'passed'),
        candidate('apc_2', 'passed', null, '整体稳定'),
        candidate('apc_3', 'invalid', 'quote_not_found', '不存在的引用'),
      ]),
    ]
    const bindings = await mount()
    check('批量入口只数 passed+unreviewed', bindings.acceptableCandidatesFor('c_syn_1').length === 2)
    await bindings.acceptPassedFor('c_syn_1')
    check(
      '批量接受逐一物化 annotation 与 link',
      state.counts.accept === 2 &&
        bindings.annotations.value.length === 2 &&
        bindings.links.value.length === 2 &&
        bindings.links.value[0].proposed_by === 'agent',
    )
    check(
      '批量接受提示',
      bindings.proposalNotice.value === '已接受 2 条候选并物化为引用（agent）' && bindings.proposalError.value === '',
      bindings.proposalNotice.value,
    )
    check(
      '批量接受后候选刷新为 accepted 且入口消失',
      bindings.latestProposalFor('c_syn_1').candidates.filter((item) => item.review_status === 'accepted').length === 2 &&
        bindings.acceptableCandidatesFor('c_syn_1').length === 0,
    )
  }

  // 批量进行中：互斥（重复点击/单条接受都被拦截），完成后恢复。
  resetState()
  {
    state.proposals = [
      proposal('completed', [candidate('apc_1', 'passed'), candidate('apc_2', 'passed', null, '整体稳定')]),
    ]
    state.acceptDefer = true
    const bindings = await mount()
    const pending = bindings.acceptPassedFor('c_syn_1')
    await flush()
    check('批量接受中 busy=true', bindings.busy.value === true)
    await bindings.acceptPassedFor('c_syn_1')
    await bindings.acceptCandidate(bindings.latestProposalFor('c_syn_1').candidates[0])
    check('批量进行中重复入口被拦截', state.counts.accept === 1, `accept=${state.counts.accept}`)
    state.acceptDefer = false
    state.acceptReleases.splice(0).forEach((release) => release())
    await pending
    check('批量完成后恢复且全部接受', bindings.busy.value === false && state.counts.accept === 2, `accept=${state.counts.accept}`)
  }

  // 服务端 duplicate_link（客户端镜像滞后）：不写红字主句，刷新关联让候选收敛到「已关联」。
  resetState()
  {
    state.proposals = [proposal()]
    state.acceptDuplicateFor = 'apc_1'
    const bindings = await mount()
    const before = state.counts.linksGet
    await bindings.acceptCandidate(bindings.latestProposalFor('c_syn_1').candidates[0])
    check('accept 409 duplicate_link 不写红字主句', bindings.proposalError.value === '', bindings.proposalError.value)
    check(
      'accept 409 duplicate_link 刷新关联并提示已关联',
      state.counts.linksGet > before && bindings.proposalNotice.value.includes('已关联'),
      bindings.proposalNotice.value,
    )
  }

  // 批量里出现 duplicate_link：记为跳过，不写红字主句、不重复建关联。
  resetState()
  {
    state.proposals = [
      proposal('completed', [candidate('apc_1', 'passed'), candidate('apc_2', 'passed', null, '整体稳定')]),
    ]
    state.acceptDuplicateFor = 'apc_2'
    const bindings = await mount()
    await bindings.acceptPassedFor('c_syn_1')
    check(
      '批量中 duplicate_link 记为跳过',
      bindings.proposalNotice.value.includes('已接受 1 条') && bindings.proposalNotice.value.includes('已跳过'),
      bindings.proposalNotice.value,
    )
    check(
      '批量跳过不写红字主句且不重复建关联',
      bindings.proposalError.value === '' && bindings.links.value.length === 1 && state.counts.accept === 2,
      `${bindings.proposalError.value} | links=${bindings.links.value.length}`,
    )
  }

  // 折叠：「证据」与全文 Block 默认收起，标题可展开；「查看原文」自动展开 Block。
  resetState()
  {
    state.proposals = [proposal()]
    const bindings = await mount()
    check('「证据」默认折叠', bindings.evidenceOpen.value === false)
    check('全文 Block 列表默认折叠', bindings.blocksOpen.value === false)
    bindings.toggleEvidence()
    check('「证据」标题可展开', bindings.evidenceOpen.value === true)
    bindings.toggleEvidence()
    check('「证据」标题可再次收起', bindings.evidenceOpen.value === false)
    bindings.toggleBlocks()
    check('全文 Block 标题可展开', bindings.blocksOpen.value === true)
    bindings.toggleBlocks()
    check('全文 Block 标题可再次收起', bindings.blocksOpen.value === false)
    await bindings.goToBlock('blk_1')
    check('「查看原文」自动展开全文 Block 列表', bindings.blocksOpen.value === true)
  }

  // 其他 accept 失败码仍按机器码报错（只有 duplicate_link 改走「已关联」人话）。
  resetState()
  state.acceptStatus = 400
  {
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    const passed = bindings.latestProposalFor('c_syn_1').candidates[0]
    await bindings.acceptCandidate(passed)
    check(
      'accept 400 文案含 invalid_candidate',
      bindings.proposalError.value.includes('invalid_candidate') && bindings.annotations.value.length === 0,
      bindings.proposalError.value,
    )
  }

  // 拒绝流程：可选原因，状态刷新为 rejected。
  resetState()
  {
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    const passed = bindings.latestProposalFor('c_syn_1').candidates[0]
    bindings.askReject(passed)
    bindings.rejectReasonInput.value = '人工不采纳'
    await bindings.rejectCandidate(passed)
    check(
      '拒绝后候选状态为 rejected 且记录原因',
      state.counts.reject === 1 &&
        bindings.latestProposalFor('c_syn_1').candidates[0].review_status === 'rejected' &&
        bindings.latestProposalFor('c_syn_1').candidates[0].reject_reason === '人工不采纳',
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
