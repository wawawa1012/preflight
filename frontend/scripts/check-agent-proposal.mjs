// Iteration 5 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 未绑定禁用 AI 预检、busy 互斥、invalid 候选可见且不可接受、accept 物化、409/400 文案、措辞纪律。
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
check('未绑定时 guard 阻止发起预检', detailSource.includes('if (busy.value || !boundRubric.value) return'))
check('invalid 候选有醒目错误码徽章', detailSource.includes('无效：'))
check('接受按钮对非 passed 候选禁用', detailSource.includes("candidate.validation_status !== 'passed'"))
check('空预检主句不是「尚未关联引用」独占', detailSource.includes('预检完成 · 当前材料尚未发现候选引用'))
check('正交展示待审核与已确认关联', detailSource.includes('已发现') && detailSource.includes('已确认关联'))
check('标注 title 含手动圈一句', detailSource.includes('手动圈一句'))
check(
  '尚未关联引用仅用于尚未预检',
  detailSource.includes('!completedProposalFor(criterion.id)'),
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

function candidate(id, status, code = null) {
  return {
    id,
    proposal_id: 'ap_1',
    ordinal: id === 'apc_1' ? 0 : 1,
    block_id: 'blk_1',
    quote: status === 'invalid' ? '不存在的引用' : '准确率达到 95%',
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

function proposal(status = 'completed', candidates = [candidate('apc_1', 'passed'), candidate('apc_2', 'invalid', 'quote_not_found')]) {
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
  releasePropose: null,
  acceptStatus: 201,
  rejectStatus: 200,
  counts: { propose: 0, accept: 0, reject: 0 },
}

function resetState() {
  state.binding = BINDING
  state.proposals = []
  state.annotations = []
  state.links = []
  state.proposeStatus = 201
  state.proposeEmpty = false
  state.proposeDefer = false
  state.releasePropose = null
  state.acceptStatus = 201
  state.rejectStatus = 200
  state.counts = { propose: 0, accept: 0, reject: 0 }
}

globalThis.fetch = async (url, options = {}) => {
  const target = String(url)
  const method = options.method ?? 'GET'
  if (method === 'GET' && target === '/api/v1/rubrics') return jsonResponse([RUBRIC])
  if (method === 'GET' && target.endsWith('/rubric-binding')) return jsonResponse(state.binding)
  if (method === 'GET' && target.endsWith('/evidence-annotations')) return jsonResponse(state.annotations)
  if (method === 'GET' && target.endsWith('/criterion-evidence-links')) return jsonResponse(state.links)
  if (method === 'GET' && target.endsWith('/agent-proposals')) return jsonResponse(state.proposals)
  if (method === 'GET' && target.startsWith('/api/v1/materials/')) return jsonResponse(MATERIAL)
  if (method === 'POST' && target.endsWith('/agent-proposals')) {
    state.counts.propose += 1
    const send = () => {
      if (state.proposeStatus === 201) {
        const created = proposal('completed', state.proposeEmpty ? [] : undefined)
        state.proposals = [created, ...state.proposals]
        return jsonResponse(created, 201)
      }
      const code = state.proposeStatus === 503 ? 'llm_unconfigured' : 'llm_timeout'
      return jsonResponse({ code, message: '预检失败示例', details: [] }, state.proposeStatus)
    }
    if (state.proposeDefer) {
      return new Promise((resolve) => {
        state.releasePropose = () => resolve(send())
      })
    }
    return send()
  }
  if (method === 'POST' && target.includes('/proposal-candidates/') && target.endsWith('/accept')) {
    state.counts.accept += 1
    if (state.acceptStatus !== 201) {
      const code =
        state.acceptStatus === 409 ? 'duplicate_link' : state.acceptStatus === 400 ? 'invalid_candidate' : 'span_mismatch'
      return jsonResponse({ code, message: '接受失败示例', details: [] }, state.acceptStatus)
    }
    const annotation = {
      id: 'ev_agent_1',
      material_id: 'mat_x',
      block_id: 'blk_1',
      source: { block_id: 'blk_1', start: 5, end: 14, quote: '准确率达到 95%' },
      note: null,
      proposed_by: 'agent',
      created_at: '2026-09-16T00:00:00+00:00',
    }
    const link = {
      id: 'cel_agent_1',
      material_id: 'mat_x',
      annotation_id: 'ev_agent_1',
      rubric_id: 'rubric_syn',
      rubric_revision: 1,
      criterion_id: 'c_syn_1',
      rationale: 'synthetic：可能相关',
      proposed_by: 'agent',
      created_at: '2026-09-16T00:00:00+00:00',
    }
    state.annotations = [...state.annotations, annotation]
    state.links = [...state.links, link]
    state.proposals = state.proposals.map((item) => ({
      ...item,
      candidates: item.candidates.map((itemCandidate) =>
        itemCandidate.id === 'apc_1'
          ? {
              ...itemCandidate,
              review_status: 'accepted',
              created_annotation_id: annotation.id,
              created_link_id: link.id,
            }
          : itemCandidate,
      ),
    }))
    return jsonResponse({ annotation, link }, 201)
  }
  if (method === 'POST' && target.includes('/proposal-candidates/') && target.endsWith('/reject')) {
    state.counts.reject += 1
    const reason = JSON.parse(options.body).reason
    state.proposals = state.proposals.map((item) => ({
      ...item,
      candidates: item.candidates.map((itemCandidate) =>
        itemCandidate.id === 'apc_1'
          ? { ...itemCandidate, review_status: 'rejected', reject_reason: reason }
          : itemCandidate,
      ),
    }))
    return jsonResponse(state.proposals[0].candidates[0], state.rejectStatus)
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

  // busy 互斥：预检进行中不能重复发起/接受。
  resetState()
  {
    const bindings = await mount()
    state.proposeDefer = true
    const pending = bindings.runPreflight(RUBRIC.criteria[0])
    check('预检中 busy=true', bindings.busy.value === true)
    const before = state.counts.propose
    await bindings.runPreflight(RUBRIC.criteria[1])
    await bindings.acceptCandidate(candidate('apc_1', 'passed'))
    check(
      '预检中重复发起与接受都被拦截',
      state.counts.propose === before && state.counts.accept === 0 && bindings.rejectFormId.value === '',
    )
    state.releasePropose()
    await pending
    check('预检完成后 busy=false', bindings.busy.value === false)
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

  // 409/400 文案：duplicate_link / invalid_candidate / span_mismatch。
  for (const [status, expected] of [
    [409, 'duplicate_link'],
    [400, 'invalid_candidate'],
  ]) {
    resetState()
    state.acceptStatus = status
    const bindings = await mount()
    await bindings.runPreflight(RUBRIC.criteria[0])
    const passed = bindings.latestProposalFor('c_syn_1').candidates[0]
    await bindings.acceptCandidate(passed)
    check(
      `accept ${status} 文案含 ${expected}`,
      bindings.proposalError.value.includes(expected) && bindings.annotations.value.length === 0,
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
