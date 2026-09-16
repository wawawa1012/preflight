// Iteration 3 证据层检查（真实 SSR 渲染 + setup 行为级，不引入测试框架）：
// 证明详情页 quote 预填、保存互斥、失败不落列表、BlockList cite 槽只在提供时渲染。
// 运行：cd frontend && node scripts/check-evidence-annotation.mjs
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

const TEXT = '中文语料：准确率达到 95%，整体稳定。'
const QUOTE = '准确率达到 95%'
const blockOne = {
  id: 'blk_1',
  document_id: 'mat_x',
  ordinal: 0,
  text: TEXT,
  locator: { kind: 'line', index: 7, end_index: null, block_index: 1 },
}
const blockTwo = {
  id: 'blk_2',
  document_id: 'mat_x',
  ordinal: 1,
  text: '第二行：无风险。',
  locator: { kind: 'line', index: 9, end_index: null, block_index: 1 },
}
const material = {
  id: 'mat_x',
  filename: 'ev.md',
  size_bytes: 42,
  sha256: 'a'.repeat(64),
  line_count: 2,
  created_at: '2026-09-16T00:00:00+00:00',
  blocks: [blockOne, blockTwo],
}
const savedAnnotation = {
  id: 'ev_1',
  material_id: 'mat_x',
  block_id: 'blk_1',
  source: { block_id: 'blk_1', start: 5, end: 14, quote: QUOTE },
  note: '高风险引用',
  proposed_by: 'human',
  created_at: '2026-09-16T00:00:00+00:00',
}

const detailSource = readFileSync(new URL('../src/views/MaterialDetailView.vue', import.meta.url), 'utf8')
const blockListSource = readFileSync(new URL('../src/components/BlockList.vue', import.meta.url), 'utf8')
const newViewSource = readFileSync(new URL('../src/views/MaterialNewView.vue', import.meta.url), 'utf8')

check('BlockList 提供 cite 槽', blockListSource.includes('<slot name="cite" :block="block"'))
check('BlockList 行支持换行（表单可整行展开）', blockListSource.includes('flex flex-wrap items-start'))
check('preview 流没有 cite 内容（行为不变）', !newViewSource.includes('#cite') && !newViewSource.includes('cite '))

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  // 渲染层：cite 槽有/无内容的差异。
  const blockListModule = await server.ssrLoadModule('/src/components/BlockList.vue')
  const withSlot = {
    render: () =>
      h(blockListModule.default, { blocks: [blockOne] }, { cite: ({ block }) => h('span', { class: 'cite-probe' }, `cite-${block.id}`) }),
  }
  const withSlotHtml = await renderToString(createSSRApp(withSlot))
  check('提供 cite 槽时渲染槽内容', withSlotHtml.includes('cite-probe') && withSlotHtml.includes('cite-blk_1'))
  const withoutSlotHtml = await renderToString(createSSRApp({ render: () => h(blockListModule.default, { blocks: [blockOne] }) }))
  check('不提供 cite 槽时无额外渲染', !withoutSlotHtml.includes('cite-probe'))

  // 行为层：详情页 setup + 真实路由参数 + fetch stub。
  const module = await server.ssrLoadModule('/src/views/MaterialDetailView.vue')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/materials/:materialId', component: module.default }],
  })
  await router.push('/materials/mat_x')
  await router.isReady()
  const app = createSSRApp(module.default)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })

  let postCount = 0
  let releasePost = null
  let postMode = 'success'
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    const method = options.method ?? 'GET'
    if (method === 'POST' && target.includes('/evidence-annotations')) {
      postCount += 1
      const send = () =>
        postMode === 'success'
          ? jsonResponse(savedAnnotation, 201)
          : jsonResponse({ code: 'quote_not_found', message: 'quote 不在该 Block 原文中', details: [] }, 400)
      if (postMode === 'deferred') {
        return new Promise((resolve) => {
          releasePost = () => resolve(send())
        })
      }
      return send()
    }
    if (target.includes('/evidence-annotations')) return jsonResponse([])
    if (target.startsWith('/api/v1/materials/')) return jsonResponse(material)
    throw new Error(`unexpected fetch: ${method} ${target}`)
  }

  const bindings = app.runWithContext(() => module.default.setup({}, { expose() {} }))
  await flush()
  check('材料与标注列表装载完成', bindings.material.value?.id === 'mat_x' && bindings.annotations.value.length === 0)

  bindings.selectBlock(blockOne)
  check('选择 Block 时 quote 预填整块', bindings.quoteInput.value === TEXT && bindings.selectedBlock.value?.id === 'blk_1')

  await bindings.saveAnnotation()
  check('保存成功后标注进入列表', bindings.annotations.value.length === 1 && bindings.annotations.value[0].id === 'ev_1')
  check('保存成功后收起表单并提示', bindings.selectedBlock.value === null && bindings.annotationNotice.value.length > 0)
  check('quote/line 展示数据正确', bindings.lineFor(bindings.annotations.value[0]) === 7)

  // 保存进行中：不能重复提交、不能改选 Block。
  bindings.selectBlock(blockTwo)
  postMode = 'deferred'
  const pendingSave = bindings.saveAnnotation()
  check('保存中 busy=true', bindings.savingAnnotation.value === true)
  const countDuringSave = postCount
  await bindings.saveAnnotation()
  bindings.selectBlock(blockOne)
  check('保存中重复提交/改选被拦截', postCount === countDuringSave && bindings.selectedBlock.value?.id === 'blk_2')
  releasePost()
  await pendingSave
  check('保存完成后控件恢复', bindings.savingAnnotation.value === false)

  // 失败路径：quote 不在原文 → 400，不进入列表。
  postMode = 'failure'
  bindings.selectBlock(blockOne)
  bindings.quoteInput.value = '不存在的引用'
  const before = bindings.annotations.value.length
  await bindings.saveAnnotation()
  check(
    'quote_not_found 明确报错且不落列表',
    bindings.annotationError.value.includes('quote_not_found') && bindings.annotations.value.length === before,
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
