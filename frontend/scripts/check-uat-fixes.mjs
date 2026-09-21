// UAT fixes targeted check（SSR 载入 + setup 行为级，不引入测试框架）：
// 1) manual publish：由最终确认的标题/要求/所需依据生成非空 source_text 快照；外部来源原文不改写；
// 2) 删除中间项后新增不产生重复 order，发布前校验必填/数量/source_text 长度；
// 3) Review 创建成功即锁定 rubric_id/revision：部分成员失败重试只补加入，不重复建单、不换标准；
// 4) Repair：选中 ≠ 已生成；成功计数只来自成功结果；503 失败保留重试；迟到响应不贴到新 finding；
// 5) 用户错误映射：不暴露部署变量 / schema·Criterion 校验原文，保留可诊断 code；
// 6) JSON 高级导入示例满足 rubric_json 最小契约，普通路径不引入第二套 Builder。
// 运行：cd frontend && node scripts/check-uat-fixes.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp, h, reactive } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })
const flush = () => new Promise((resolve) => setTimeout(resolve, 0))
const jsonResponse = (data, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })

const reviewNewSource = readFileSync(new URL('../src/views/review/ReviewNewView.vue', import.meta.url), 'utf8')
const reportSource = readFileSync(new URL('../src/views/MaterialReportView.vue', import.meta.url), 'utf8')

const findingA = {
  material_id: 'mat_x',
  kind: 'numeric_inconsistency',
  measure: '准确率',
  values: ['95%', '90%'],
  searched_block_count: 1,
  searched_statement_count: 2,
  explanation: '同一度量词「准确率」在本材料 2 处给出不同数值：95%、90%；请核对后决定以哪一处为准。',
  citations: [
    { block_id: 'blk_1', line_number: 7, quote: '95%', start: 5, end: 8, value: '95', unit: '%' },
    { block_id: 'blk_1', line_number: 7, quote: '90%', start: 12, end: 15, value: '90', unit: '%' },
  ],
}
const findingB = { ...findingA, measure: '召回率', values: ['80%', '70%'] }

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const criteriaModule = await server.ssrLoadModule('/src/services/criteriaSource.ts')
  const errorModule = await server.ssrLoadModule('/src/utils/userFacingError.ts')
  const editorModule = await server.ssrLoadModule('/src/components/review/RubricDraftEditor.vue')
  const panelModule = await server.ssrLoadModule('/src/components/RepairSuggestionPanel.vue')
  const reviewNewModule = await server.ssrLoadModule('/src/views/review/ReviewNewView.vue')
  const reportModule = await server.ssrLoadModule('/src/views/MaterialReportView.vue')

  // ——— 1. manual publish：快照与发布前校验 ———
  {
    const manual = criteriaModule.emptyManualDraft()
    manual.title = '手工标准'
    manual.criteria = [
      { id: 'm1', title: '要求一', requirement: '说明测试条件', required_evidence: ['测试环境'], order: 0 },
      { id: 'm2', title: '要求二', requirement: '给出统计口径', required_evidence: ['口径说明', '样本量'], order: 1 },
    ]
    const prepared = criteriaModule.preparePublish(manual)
    check('手工草稿发布前校验通过', prepared.ok === true, JSON.stringify(prepared.problems))
    const snapshot = prepared.payload?.source_text ?? ''
    check(
      '手工 source_text 快照非空且来自最终确认内容',
      snapshot !== '' &&
        snapshot.includes('手工标准') &&
        snapshot.includes('要求一') &&
        snapshot.includes('说明测试条件') &&
        snapshot.includes('测试环境'),
      snapshot,
    )
    check('手工发布 payload 显式 confirmed 且 provenance 为 manual', prepared.payload?.confirmed === true && prepared.payload?.source_type === 'manual')

    const gapped = {
      ...manual,
      criteria: [
        { id: 'g1', title: 'A', requirement: 'ra', required_evidence: [], order: 0 },
        { id: 'g2', title: 'B', requirement: 'rb', required_evidence: [], order: 7 },
      ],
    }
    const normalized = criteriaModule.preparePublish(gapped)
    check('发布 payload 按显示顺序重编号 order', normalized.payload?.criteria.map((item) => item.order).join(',') === '0,1')

    const external = {
      ...manual,
      source_type: 'plain_text',
      source_text: '这是用户粘贴的原始要求全文',
      criteria: [{ id: 'e1', title: 'A', requirement: 'ra', required_evidence: [], order: 0 }],
    }
    const externalPrepared = criteriaModule.preparePublish(external)
    check(
      '外部来源 source_text 原样保留（不自动改 manual 绕过 provenance）',
      externalPrepared.payload?.source_text === '这是用户粘贴的原始要求全文' && externalPrepared.payload?.source_type === 'plain_text',
    )

    const noTitle = criteriaModule.preparePublish({ ...manual, title: '   ' })
    check('缺标题被发布前校验拦下', noTitle.ok === false)
    const noCriteria = criteriaModule.preparePublish({ ...manual, criteria: [] })
    check('零条要求被拦下', noCriteria.problems.includes('至少需要一条审查要求。'), noCriteria.problems.join(' / '))
    const blankRequirement = criteriaModule.preparePublish({
      ...manual,
      criteria: [{ id: 'x', title: 'A', requirement: '  ', required_evidence: [], order: 0 }],
    })
    check('要求内容为空被拦下', blankRequirement.ok === false)
    const oversized = criteriaModule.preparePublish({
      ...manual,
      source_type: 'plain_text',
      source_text: 'x'.repeat(criteriaModule.MAX_SOURCE_TEXT_CHARS + 1),
    })
    check(
      'source_text 超长被拦下',
      oversized.problems.some((problem) => problem.includes('过长')),
      oversized.problems.join(' / '),
    )
  }

  // ——— 6. JSON 高级导入示例 ———
  {
    let parsed = null
    try {
      parsed = JSON.parse(criteriaModule.RUBRIC_JSON_EXAMPLE)
    } catch {
      parsed = null
    }
    const criteriaOk =
      parsed !== null &&
      typeof parsed.title === 'string' &&
      parsed.title.trim() !== '' &&
      Array.isArray(parsed.criteria) &&
      parsed.criteria.length > 0 &&
      parsed.criteria.length <= 50 &&
      parsed.criteria.every(
        (item) =>
          typeof item.title === 'string' &&
          item.title.trim() !== '' &&
          typeof item.requirement === 'string' &&
          item.requirement.trim() !== '' &&
          Array.isArray(item.required_evidence) &&
          item.required_evidence.every((entry) => typeof entry === 'string' && entry.trim() !== ''),
      )
    check('JSON 示例可解析且满足 title + criteria 最小契约', criteriaOk)
    check(
      'ReviewNew 把 JSON 标为高级导入并展示示例',
      reviewNewSource.includes('高级导入') && reviewNewSource.includes('RUBRIC_JSON_EXAMPLE') && reviewNewSource.includes('最小合法 JSON 示例'),
    )
  }

  // ——— 2. 草稿编辑器：删除/新增/移动后按显示顺序重编号 ———
  {
    const initial = {
      title: 'T',
      source_note: '手工创建',
      source_type: 'manual',
      source_text: '',
      model_assisted: false,
      criteria: [
        { id: 'c1', title: 'A', requirement: 'ra', required_evidence: ['e1'], order: 0 },
        { id: 'c2', title: 'B', requirement: 'rb', required_evidence: [], order: 1 },
        { id: 'c3', title: 'C', requirement: 'rc', required_evidence: ['e3'], order: 2 },
      ],
    }
    const props = { modelValue: initial, disabled: false }
    const emit = (event, value) => {
      if (event === 'update:modelValue') props.modelValue = value
    }
    const editorApp = createSSRApp(editorModule.default, props)
    editorApp.provide(ssrContextKey, { modules: new Set() })
    const bindings = editorApp.runWithContext(() => editorModule.default.setup(props, { expose() {}, emit }))

    bindings.removeCriterion(1)
    const afterRemove = props.modelValue.criteria
    check(
      '删除中间项后 order 连续且 identity 保留',
      afterRemove.map((item) => item.order).join(',') === '0,1' && afterRemove.map((item) => item.id).join(',') === 'c1,c3',
      afterRemove.map((item) => `${item.id}:${item.order}`).join(' '),
    )

    bindings.addCriterion()
    const afterAdd = props.modelValue.criteria
    const addedId = afterAdd[2].id
    const orders = afterAdd.map((item) => item.order)
    check(
      '删除中间项后新增不产生重复 order',
      afterAdd.length === 3 && new Set(orders).size === 3 && orders.join(',') === '0,1,2',
      afterAdd.map((item) => `${item.id}:${item.order}`).join(' '),
    )
    check(
      '新增项 identity 独立且保留既有 identity',
      afterAdd[0].id === 'c1' && afterAdd[1].id === 'c3' && addedId.startsWith('manual-'),
    )

    bindings.moveCriterion(2, -1)
    const afterMove = props.modelValue.criteria
    check(
      '移动后仍按显示顺序编号',
      afterMove.map((item) => item.id).join(',') === `c1,${addedId},c3` &&
        afterMove.map((item) => item.order).join(',') === '0,1,2',
      afterMove.map((item) => `${item.id}:${item.order}`).join(' '),
    )

    bindings.removeCriterion(0)
    bindings.removeCriterion(0)
    bindings.removeCriterion(0)
    const removedAll = criteriaModule.preparePublish(props.modelValue)
    check('删空后发布前校验拦住（不少于一条）', removedAll.ok === false && removedAll.problems.includes('至少需要一条审查要求。'))
  }

  // ——— 3. Review 创建后锁定标准，重试只补材料 ———
  const mountReviewNew = async (fetchImpl) => {
    globalThis.fetch = fetchImpl
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/reviews/new', component: reviewNewModule.default },
        { path: '/reviews/:reviewId', component: { template: '<div />' } },
        { path: '/', component: { template: '<div />' } },
      ],
    })
    await router.push('/reviews/new')
    await router.isReady()
    const app = createSSRApp(reviewNewModule.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    const bindings = app.runWithContext(() => reviewNewModule.default.setup({}, { expose() {} }))
    await flush()
    return { bindings, router }
  }

  {
    const state = { creates: [], puts: [], publishes: [], failMaterials: ['mat_b'] }
    const rubrics = [
      { id: 'rub_1', revision: 1, title: 'Standard One', source_note: 's', criteria: [] },
      { id: 'rub_2', revision: 2, title: 'Standard Two', source_note: 's', criteria: [] },
    ]
    const materials = [
      { id: 'mat_a', filename: 'a.md', created_at: '2026-09-20T00:00:00+00:00', block_count: 1 },
      { id: 'mat_b', filename: 'b.md', created_at: '2026-09-20T00:00:00+00:00', block_count: 1 },
    ]
    const fetchImpl = async (input, init = {}) => {
      const url = String(input)
      const method = init.method ?? 'GET'
      if (method === 'GET' && url === '/api/v1/rubrics') return jsonResponse(rubrics)
      if (method === 'GET' && url === '/api/v1/materials') return jsonResponse(materials)
      if (method === 'POST' && url === '/api/v1/reviews') {
        state.creates.push(JSON.parse(init.body))
        return jsonResponse(
          { id: 'rev_1', title: 'T', rubric_id: 'rub_1', rubric_revision: 1, created_at: '', updated_at: '' },
          201,
        )
      }
      if (method === 'POST' && url === '/api/v1/rubrics') {
        state.publishes.push(JSON.parse(init.body))
        return jsonResponse({}, 201)
      }
      const putMatch = method === 'PUT' && url.match(/^\/api\/v1\/reviews\/([^/]+)\/materials\/([^/]+)$/)
      if (putMatch) {
        state.puts.push({ reviewId: putMatch[1], materialId: putMatch[2] })
        if (state.failMaterials.includes(putMatch[2])) {
          return jsonResponse({ code: 'internal_error', message: '服务器内部错误', details: [] }, 500)
        }
        return jsonResponse({ material_id: putMatch[2], label: '', position: 0 }, 201)
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    }

    const { bindings, router } = await mountReviewNew(fetchImpl)
    bindings.criteriaKind.value = 'existing'
    bindings.rubricKey.value = 'rub_1:1'
    bindings.title.value = 'T'
    bindings.seats.value[0].checked = true
    bindings.seats.value[1].checked = true
    await bindings.submit()

    check(
      'Review 创建成功即锁定真实 rubric_id/revision',
      state.creates.length === 1 &&
        state.creates[0].rubric_id === 'rub_1' &&
        bindings.createdReviewId.value === 'rev_1' &&
        bindings.effectiveRubric.value?.id === 'rub_1',
      JSON.stringify(state.creates),
    )
    check(
      '部分成员失败：留在本页且失败可见',
      router.currentRoute.value.fullPath === '/reviews/new' && bindings.submitError.value !== '',
      bindings.submitError.value,
    )
    check(
      '部分成员失败：成功加入的材料已记录',
      state.puts.length === 2 && state.puts[0].materialId === 'mat_a' && state.puts[1].materialId === 'mat_b',
      JSON.stringify(state.puts),
    )

    // UI 改选另一个标准后重试：不新建 Review、不换标准、不重复加入已成功材料。
    bindings.rubricKey.value = 'rub_2:2'
    state.failMaterials = []
    await bindings.submit()
    await flush()
    check(
      '重试不重复建单、不换标准、不重复发布',
      state.creates.length === 1 && bindings.effectiveRubric.value?.id === 'rub_1' && state.publishes.length === 0,
      JSON.stringify({ creates: state.creates.length, rubric: bindings.effectiveRubric.value?.id }),
    )
    check(
      '重试只补未加入的材料（已成功的材料不再 PUT）',
      state.puts.length === 3 && state.puts[2].materialId === 'mat_b' && state.puts[2].reviewId === 'rev_1',
      JSON.stringify(state.puts),
    )
    check('重试成功后进入该 Review', router.currentRoute.value.fullPath === '/reviews/rev_1')
  }

  // ——— 1b. 无模型手工发布 → 直接进入 Review ———
  {
    const state = { creates: [], publishes: [] }
    const fetchImpl = async (input, init = {}) => {
      const url = String(input)
      const method = init.method ?? 'GET'
      if (method === 'GET' && url === '/api/v1/rubrics') return jsonResponse([])
      if (method === 'GET' && url === '/api/v1/materials') return jsonResponse([])
      if (method === 'POST' && url === '/api/v1/rubrics') {
        state.publishes.push(JSON.parse(init.body))
        return jsonResponse(
          { id: 'rub_manual', revision: 1, title: '手工标准', source_note: '手工创建', criteria: [], source_type: 'manual' },
          201,
        )
      }
      if (method === 'POST' && url === '/api/v1/reviews') {
        state.creates.push(JSON.parse(init.body))
        return jsonResponse(
          { id: 'rev_manual', title: '手工审查', rubric_id: 'rub_manual', rubric_revision: 1, created_at: '', updated_at: '' },
          201,
        )
      }
      throw new Error(`unexpected fetch: ${method} ${url}`)
    }

    const { bindings, router } = await mountReviewNew(fetchImpl)
    bindings.criteriaKind.value = 'manual'
    await bindings.generateDraft()
    check(
      '手工创建不调用模型：零发布请求且有可编辑草稿',
      state.publishes.length === 0 && bindings.draft.value?.source_type === 'manual',
      JSON.stringify(state.publishes),
    )
    bindings.draft.value.title = '手工标准'
    bindings.draft.value.criteria[0].title = '要求一'
    bindings.draft.value.criteria[0].requirement = '说明测试条件'
    bindings.draft.value.criteria[0].required_evidence = ['测试环境']
    await bindings.publish()
    const published = state.publishes[0]
    check(
      '手工发布 payload 带非空 source_text 快照',
      Boolean(published) &&
        published.confirmed === true &&
        published.source_text.includes('手工标准') &&
        published.source_text.includes('说明测试条件') &&
        published.source_text.includes('测试环境'),
      published ? published.source_text : '无发布请求',
    )
    bindings.title.value = '手工审查'
    await bindings.submit()
    await flush()
    check(
      '手工发布的标准可直接进入 Review',
      state.creates.length === 1 &&
        state.creates[0].rubric_id === 'rub_manual' &&
        router.currentRoute.value.fullPath === '/reviews/rev_manual',
      JSON.stringify({ creates: state.creates, route: router.currentRoute.value.fullPath }),
    )
  }

  // ——— 5. 用户错误映射 ———
  {
    const failure = errorModule.failureFromResponse
    const map = errorModule.toUserFacingError

    const unconfigured = map(
      failure(503, { code: 'llm_unconfigured', message: '未配置 LLM（PREFLIGHT_LLM_BASE_URL/API_KEY/MODEL）' }),
    )
    check(
      '未配置 LLM：安全文案、保留 code、不暴露部署变量',
      unconfigured.code === 'llm_unconfigured' &&
        unconfigured.message.includes('配置后重试') &&
        !unconfigured.message.includes('PREFLIGHT_') &&
        !unconfigured.message.includes('API_KEY'),
      unconfigured.message,
    )

    const rawSchema = map(failure(400, { code: 'weird_code', message: 'criteria[0] 不符合 Criterion 结构' }))
    check(
      '未知 code 的 schema/Criterion 原文被拦下',
      rawSchema.code === 'weird_code' && !rawSchema.message.includes('Criterion') && !rawSchema.message.includes('criteria['),
      rawSchema.message,
    )

    const invalidRequest = map(failure(400, { code: 'invalid_request', message: '请求体校验失败' }))
    check('请求体校验失败用普通用户措辞', invalidRequest.message === '提交内容不符合要求，请检查后重试', invalidRequest.message)

    const upstream = map(failure(502, { code: 'llm_unavailable', message: 'LLM 上游不可用' }))
    check('上游失败可见且保留 code', upstream.message.includes('LLM 上游不可用') && upstream.code === 'llm_unavailable')

    const conflict = map(failure(409, { code: 'binding_conflict', message: '该材料已绑定其他评分标准版本' }))
    check(
      '换绑冲突文案明确未改动且保留 code',
      conflict.code === 'binding_conflict' && conflict.message.includes('未做任何改动'),
      conflict.message,
    )

    const network = map(new TypeError('Failed to fetch'))
    check('网络失败给可重试文案', network.retryable === true && network.message.includes('网络'), network.message)

    check(
      'Builder/Repair 宿主已接入同一映射工具',
      reviewNewSource.includes("from '../../utils/userFacingError'") && reportSource.includes("from '../utils/userFacingError'"),
    )
  }

  // ——— 4. Repair：运行/失败/成功分开，迟到响应无效 ———
  const mountPanel = (props, fetchImpl) => {
    globalThis.fetch = fetchImpl
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/materials/:materialId/revise', component: { template: '<div />' } },
        { path: '/', component: { template: '<div />' } },
      ],
    })
    const pinia = createPinia()
    const app = createSSRApp(panelModule.default, props)
    app.use(router)
    app.use(pinia)
    setActivePinia(pinia)
    app.provide(ssrContextKey, { modules: new Set() })
    return app.runWithContext(() => panelModule.default.setup(props, { expose() {} }))
  }

  {
    const statuses = []
    const props = reactive({ materialId: 'mat_x', materialLabel: 'ev.md', finding: findingA, onStatus: (state) => statuses.push(state) })
    const bindings = mountPanel(props, async () =>
      jsonResponse({ code: 'llm_unconfigured', message: '未配置 LLM（PREFLIGHT_LLM_BASE_URL/API_KEY/MODEL）' }, 503),
    )
    await flush()
    check(
      'Repair 503：失败可见、无建议、不暴露部署变量',
      bindings.error.value.includes('配置后重试') &&
        bindings.suggestion.value === null &&
        !bindings.error.value.includes('PREFLIGHT_') &&
        !bindings.error.value.includes('API_KEY'),
      String(bindings.error.value),
    )
    check('Repair 503：状态序列为运行→失败', statuses.join(',') === 'running,failed', statuses.join(','))
  }

  {
    const statuses = []
    const props = reactive({ materialId: 'mat_x', materialLabel: 'ev.md', finding: findingA, onStatus: (state) => statuses.push(state) })
    let releaseFirst = null
    let calls = 0
    const fetchImpl = () => {
      calls += 1
      if (calls === 1) {
        return new Promise((resolve) => {
          releaseFirst = () => resolve(jsonResponse({ suggestion: 'A 建议', action: 'A' }))
        })
      }
      return jsonResponse({ suggestion: 'B 建议', action: 'B' })
    }
    const bindings = mountPanel(props, fetchImpl)
    await flush()
    check('首个请求进行中状态为 running', statuses.join(',') === 'running', statuses.join(','))
    props.finding = findingB
    await flush()
    check('切换 finding 后发出新请求', calls === 2, `calls=${calls}`)
    check('新 finding 的成功结果生效', bindings.suggestion.value?.suggestion === 'B 建议' && bindings.error.value === '')
    releaseFirst()
    await flush()
    check(
      '迟到旧响应不贴到新 finding、不追加成功计数',
      bindings.suggestion.value?.suggestion === 'B 建议' && statuses.join(',') === 'running,running,succeeded',
      statuses.join(','),
    )
  }

  {
    const statuses = []
    const props = reactive({ materialId: 'mat_x', finding: findingA, onStatus: (state) => statuses.push(state) })
    let calls = 0
    const fetchImpl = () => {
      calls += 1
      if (calls === 1) return jsonResponse({ code: 'llm_timeout', message: 'LLM 请求超时' }, 504)
      return jsonResponse({ suggestion: '重试成功', action: '重试' })
    }
    const bindings = mountPanel(props, fetchImpl)
    await flush()
    check('失败后保留重试入口且不伪造建议', bindings.error.value.includes('生成超时') && bindings.suggestion.value === null)
    bindings.retry()
    await flush()
    check(
      '重试成功后清错并展示建议',
      bindings.error.value === '' && bindings.suggestion.value?.suggestion === '重试成功' && calls === 2,
    )
    check(
      '重试状态序列 running,failed,running,succeeded',
      statuses.join(',') === 'running,failed,running,succeeded',
      statuses.join(','),
    )
  }

  // 宿主回调经 vnode props 传递（模板 :on-status 走同一 prop）。
  {
    const statuses = []
    globalThis.fetch = async () => jsonResponse({ suggestion: '回调建议', action: '回调' })
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await router.push('/')
    await router.isReady()
    const pinia = createPinia()
    const app = createSSRApp({
      render: () =>
        h(panelModule.default, { materialId: 'mat_x', finding: findingA, onStatus: (state) => statuses.push(state) }),
    })
    app.use(router)
    app.use(pinia)
    setActivePinia(pinia)
    app.provide(ssrContextKey, { modules: new Set() })
    await renderToString(app)
    await flush()
    check('宿主回调能收到运行→成功状态', statuses.join(',') === 'running,succeeded', statuses.join(','))
  }

  // 报告页：计数只来自成功结果；选中不等于已生成。
  {
    const materialsResponse = {
      id: 'mat_x',
      filename: 'ev.md',
      size_bytes: 1,
      sha256: 'a'.repeat(64),
      line_count: 1,
      created_at: '2026-09-20T00:00:00+00:00',
      blocks: [],
    }
    globalThis.fetch = async (input) => {
      const url = String(input)
      if (url.includes('consistency-findings')) return jsonResponse([findingA])
      if (url.includes('statement-signals')) return jsonResponse([])
      if (url.includes('agent-proposals')) return jsonResponse([])
      if (/\/api\/v1\/materials\/[^/]+$/.test(url)) return jsonResponse(materialsResponse)
      return jsonResponse({ code: 'rubric_not_bound', message: '该材料尚未绑定评分标准', details: [] }, 409)
    }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/materials/:materialId/report', component: reportModule.default },
        { path: '/materials/:materialId', component: { template: '<div />' } },
        { path: '/', component: { template: '<div />' } },
      ],
    })
    await router.push('/materials/mat_x/report')
    await router.isReady()
    const app = createSSRApp(reportModule.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    const bindings = app.runWithContext(() => reportModule.default.setup({}, { expose() {} }))
    await flush()

    bindings.openRepair(findingA)
    check(
      '仅选中 finding 时成功计数为 0',
      bindings.repairSucceededCount.value === 0 && bindings.repairRunningCount.value === 0 && bindings.repairFailedCount.value === 0,
    )
    bindings.onRepairStatus('succeeded')
    check('成功结果才计入已生成', bindings.repairSucceededCount.value === 1)
    bindings.onRepairStatus('failed')
    check(
      '失败后成功计数归零、失败单独可见',
      bindings.repairSucceededCount.value === 0 && bindings.repairFailedCount.value === 1 && bindings.repairRunningCount.value === 0,
    )
    bindings.onRepairStatus('running')
    check(
      '运行/失败/成功分开计数',
      bindings.repairRunningCount.value === 1 && bindings.repairSucceededCount.value === 0 && bindings.repairFailedCount.value === 0,
      `running=${bindings.repairRunningCount.value} succeeded=${bindings.repairSucceededCount.value} failed=${bindings.repairFailedCount.value}`,
    )
    check(
      '报告页计数取自成功结果而非选中项',
      reportSource.includes('repairSucceededCount') &&
        reportSource.includes(':on-status="onRepairStatus"') &&
        !reportSource.includes('已生成 1 条建议'),
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
