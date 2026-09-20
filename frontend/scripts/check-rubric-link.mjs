// Iteration 4 检查（SSR 载入 + setup 行为级，不引入测试框架）：
// 空标准仓文案、绑定、关联成功与 409/400 文案、busy 互斥、删除、锚点定位与找不到提示、措辞纪律。
// 合成 rubric 只存在于本脚本（test-only），不写入 data/、文档或 fixture。
// 运行：cd frontend && node scripts/check-rubric-link.mjs
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
const blockListSource = readFileSync(new URL('../src/components/BlockList.vue', import.meta.url), 'utf8')

// 措辞纪律：不能把“相关”写成“已满足/已支撑”。
check('详情页不含“已满足/已支撑”措辞', !detailSource.includes('已满足') && !detailSource.includes('已支撑'))
check('BlockList 支持 annotatedCounts 与 highlight', blockListSource.includes('annotatedCounts') && blockListSource.includes('highlightBlockId'))
check('详情页传入 annotated-counts 与锚点 id', detailSource.includes(':annotated-counts=') && blockListSource.includes('block-'))

const blockOne = {
  id: 'blk_1',
  document_id: 'mat_x',
  ordinal: 0,
  text: '中文语料：准确率达到 95%，整体稳定。',
  locator: { kind: 'line', index: 7, end_index: null, block_index: 1 },
}
const blockTwo = {
  id: 'blk_2',
  document_id: 'mat_x',
  ordinal: 1,
  text: '第二行：无风险。',
  locator: { kind: 'line', index: 9, end_index: null, block_index: 1 },
}
const MATERIAL = {
  id: 'mat_x',
  filename: 'ev.md',
  size_bytes: 42,
  sha256: 'a'.repeat(64),
  line_count: 2,
  created_at: '2026-09-16T00:00:00+00:00',
  blocks: [blockOne, blockTwo],
}
const ANNOTATION = {
  id: 'ev_1',
  material_id: 'mat_x',
  block_id: 'blk_1',
  source: { block_id: 'blk_1', start: 5, end: 14, quote: '准确率达到 95%' },
  note: '高风险引用',
  proposed_by: 'human',
  created_at: '2026-09-16T00:00:00+00:00',
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
const LINK = {
  id: 'cel_1',
  material_id: 'mat_x',
  annotation_id: 'ev_1',
  rubric_id: 'rubric_syn',
  rubric_revision: 1,
  criterion_id: 'c_syn_1',
  rationale: '人工判断：该引用与 Criterion A 相关',
  proposed_by: 'human',
  created_at: '2026-09-16T00:00:00+00:00',
}

const state = {
  rubrics: [RUBRIC],
  binding: null,
  annotations: [ANNOTATION],
  links: [],
  putStatus: 201,
  postStatus: 201,
  deleteStatus: 204,
  puts: 0,
  posts: 0,
  deletes: 0,
  putBody: null,
  postBody: null,
  deferPost: false,
  releasePost: null,
}

function resetState() {
  state.rubrics = [RUBRIC]
  state.binding = null
  state.annotations = [ANNOTATION]
  state.links = []
  state.putStatus = 201
  state.postStatus = 201
  state.deleteStatus = 204
  state.puts = 0
  state.posts = 0
  state.deletes = 0
  state.putBody = null
  state.postBody = null
  state.deferPost = false
  state.releasePost = null
}

globalThis.fetch = async (url, options = {}) => {
  const target = String(url)
  const method = options.method ?? 'GET'
  if (method === 'GET' && target === '/api/v1/rubrics') return jsonResponse(state.rubrics)
  if (method === 'GET' && target.endsWith('/rubric-binding')) return jsonResponse(state.binding)
  if (method === 'GET' && target.endsWith('/evidence-annotations')) return jsonResponse(state.annotations)
  if (method === 'GET' && target.endsWith('/criterion-evidence-links')) return jsonResponse(state.links)
  if (method === 'GET' && target.endsWith('/agent-proposals')) return jsonResponse([])
  if (method === 'GET' && target.startsWith('/api/v1/materials/')) return jsonResponse(MATERIAL)
  if (method === 'PUT' && target.endsWith('/rubric-binding')) {
    state.puts += 1
    state.putBody = JSON.parse(options.body)
    if (state.putStatus === 201) {
      state.binding = BINDING
      return jsonResponse(BINDING, 201)
    }
    return jsonResponse({ code: 'binding_conflict', message: '该材料已绑定其他评分标准版本', details: [] }, state.putStatus)
  }
  if (method === 'POST' && target.endsWith('/criterion-evidence-links')) {
    state.posts += 1
    state.postBody = JSON.parse(options.body)
    const send = () => {
      if (state.postStatus === 201) {
        state.links = [...state.links, LINK]
        return jsonResponse(LINK, 201)
      }
      const code = state.postStatus === 409 ? 'duplicate_link' : 'span_mismatch'
      const message = state.postStatus === 409 ? '该引用已关联此评分要求' : 'annotation span 与原文不一致'
      return jsonResponse({ code, message, details: [] }, state.postStatus)
    }
    if (state.deferPost) {
      return new Promise((resolve) => {
        state.releasePost = () => resolve(send())
      })
    }
    return send()
  }
  if (method === 'DELETE') {
    state.deletes += 1
    if (state.deleteStatus === 204) {
      if (target.includes('/criterion-evidence-links/')) {
        state.links = state.links.filter((item) => item.id !== LINK.id)
      } else {
        state.annotations = state.annotations.filter((item) => item.id !== ANNOTATION.id)
        state.links = state.links.filter((item) => item.annotation_id !== ANNOTATION.id)
      }
      return new Response(null, { status: 204 })
    }
    return jsonResponse({ code: 'link_not_found', message: '找不到该关联', details: [] }, 404)
  }
  throw new Error(`unexpected fetch: ${method} ${target}`)
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const module = await server.ssrLoadModule('/src/views/MaterialDetailView.vue')

  async function mount(routePath = '/materials/mat_x') {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/materials/:materialId', component: module.default }],
    })
    await router.push(routePath)
    await router.isReady()
    const app = createSSRApp(module.default)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
    await flush()
    await flush()
    return bindings
  }

  // 空标准仓：空列表、无绑定、模板含明确文案。
  resetState()
  state.rubrics = []
  {
    const bindings = await mount()
    check('空标准仓：rubrics 为空且无绑定', bindings.rubrics.value.length === 0 && bindings.binding.value === null)
    check('空仓有明确文案（不伪装标准）', detailSource.includes('尚未配置审查标准'))
  }

  // 绑定成功与冲突文案。
  resetState()
  {
    const bindings = await mount()
    await bindings.bindRubric(RUBRIC)
    check(
      '绑定成功：binding 写入且 PUT body 正确',
      bindings.binding.value?.rubric_id === 'rubric_syn' && state.putBody.rubric_revision === 1,
      JSON.stringify(state.putBody),
    )
    check('绑定成功提示', bindings.bindingNotice.value.includes('已绑定'))
    check('绑定后 Criterion 列表来自绑定版本', bindings.boundRubric.value?.criteria.length === 2)
  }
  resetState()
  state.putStatus = 409
  {
    const bindings = await mount()
    await bindings.bindRubric(RUBRIC)
    check(
      '换绑冲突 409 明确文案',
      bindings.bindingError.value.includes('binding_conflict') && bindings.binding.value === null,
      bindings.bindingError.value,
    )
  }

  // 关联成功、重复 409、span 400。
  resetState()
  {
    state.binding = BINDING
    const bindings = await mount()
    bindings.selectAnnotationToLink(bindings.annotations.value[0])
    check('关联表单预选第一个 Criterion', bindings.linkCriterionId.value === 'c_syn_1')
    bindings.linkRationale.value = '人工判断：该引用与 Criterion A 相关'
    await bindings.saveLink()
    check(
      '关联成功：进入列表且 body 只有身份字段',
      bindings.links.value.length === 1 && state.postBody.annotation_id === 'ev_1' && state.postBody.criterion_id === 'c_syn_1',
    )
    check('关联成功后表单收起', bindings.linkAnnotation.value === null && bindings.linkNotice.value.includes('已建立关联'))
  }
  resetState()
  state.binding = BINDING
  state.postStatus = 409
  {
    const bindings = await mount()
    bindings.selectAnnotationToLink(bindings.annotations.value[0])
    bindings.linkRationale.value = '理由'
    const before = bindings.links.value.length
    await bindings.saveLink()
    check(
      '重复关联 409 不落列表且文案明确',
      bindings.linkError.value.includes('duplicate_link') && bindings.links.value.length === before,
      bindings.linkError.value,
    )
  }
  resetState()
  state.binding = BINDING
  state.postStatus = 400
  {
    const bindings = await mount()
    bindings.selectAnnotationToLink(bindings.annotations.value[0])
    bindings.linkRationale.value = '理由'
    await bindings.saveLink()
    check('span 失效 400 不落列表', bindings.linkError.value.includes('span_mismatch'), bindings.linkError.value)
  }

  // busy 互斥：保存中不能重复提交、不能改选。
  resetState()
  state.binding = BINDING
  state.deferPost = true
  {
    const bindings = await mount()
    bindings.selectAnnotationToLink(bindings.annotations.value[0])
    bindings.linkRationale.value = '理由'
    const pending = bindings.saveLink()
    check('关联保存中 busy 为 true', bindings.busy.value === true)
    const postsDuring = state.posts
    await bindings.saveLink()
    const switched = bindings.linkAnnotation.value
    bindings.selectAnnotationToLink(bindings.annotations.value[0])
    check('保存中重复提交/改选被拦截', state.posts === postsDuring && switched === bindings.linkAnnotation.value)
    state.releasePost()
    await pending
    check('保存完成后 busy 恢复', bindings.busy.value === false)
  }

  // 删除标注（级联清关联）与移除关联。
  resetState()
  state.binding = BINDING
  state.links = [LINK]
  {
    const bindings = await mount()
    check('初始状态：1 条标注 1 条关联', bindings.annotations.value.length === 1 && bindings.links.value.length === 1)
    await bindings.deleteAnnotation(bindings.annotations.value[0])
    check(
      '删除标注后列表与关联同步清空',
      bindings.annotations.value.length === 0 && bindings.links.value.length === 0 && state.deletes === 1,
    )
    check('Block 数据未被删除（材料完整性）', bindings.material.value.blocks.length === 2)
  }
  resetState()
  state.binding = BINDING
  state.links = [LINK]
  {
    const bindings = await mount()
    await bindings.deleteLink(bindings.links.value[0])
    check('移除关联后引用仍在列表', bindings.links.value.length === 0 && bindings.annotations.value.length === 1)
  }
  resetState()
  state.binding = BINDING
  state.links = [LINK]
  state.deleteStatus = 404
  {
    const bindings = await mount()
    await bindings.deleteLink(bindings.links.value[0])
    check('删除失败明确报错且不误删', bindings.linkError.value.includes('link_not_found') && bindings.links.value.length === 1)
  }

  // 锚点：点击定位与带 hash 刷新；找不到明确提示。
  resetState()
  {
    let scrolled = false
    globalThis.document = {
      getElementById: (id) => (id === 'block-blk_1' ? { scrollIntoView: () => { scrolled = true } } : null),
    }
    const bindings = await mount('/materials/mat_x#block-blk_1')
    check('带 #block-* 打开时定位并高亮', scrolled === true && bindings.highlightedBlockId.value === 'blk_1')
    check('带 #block-* 打开时自动展开全文 Block 列表', bindings.blocksOpen.value === true)
    // goToBlock 现在先展开折叠的 Block 列表再定位（async），这里显式等待完成。
    await bindings.goToBlock('blk_missing')
    check('目标 Block 不存在时明确提示', bindings.anchorNotice.value.includes('找不到'))
    delete globalThis.document
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
