// Sprint 4 assessment adapter 检查：用真实 backend 垂直切片落盘的 wire JSON
// （C:/Users/A/AppData/Local/Temp/preflight_slice_wire，由 preflight_slice.py 生成）
//  stub 全局 fetch 后验证 services/assessment.ts 的 generated→VM 映射。
// 运行：cd frontend && node scripts/check-assessment-adapter.mjs
import { readFileSync } from 'node:fs'
import { createServer } from 'vite'

const WIRE = 'C:/Users/A/AppData/Local/Temp/preflight_slice_wire'
const read = (name) => JSON.parse(readFileSync(`${WIRE}/${name}`, 'utf8'))

const snap1 = read('snapshot_scorable.json')
const snap2 = read('snapshot_scorable_2.json')
const snap3 = read('snapshot_not_scorable.json')
const list = read('summary_list.json')
const comparison = read('comparison_comparable.json')

// contract 形状的合成 not_comparable 响应（backend 语义已由 backend 单测覆盖，这里只验映射）。
const notComparable = {
  before_id: snap1.id,
  after_id: snap2.id,
  status: 'not_comparable',
  reason_codes: ['prompt_version_mismatch'],
  evidence_scope_changed: false,
  criteria: [],
  aggregation_before: comparison.aggregation_before,
  aggregation_after: comparison.aggregation_after,
}

const routes = new Map([
  [`/api/v1/reviews/${snap1.scope.review_id}/assessments`, list],
  [`/api/v1/assessments/${snap1.id}`, snap1],
  [`/api/v1/assessments/${snap2.id}`, snap2],
  [`/api/v1/assessments/${snap3.id}`, snap3],
  [`/api/v1/assessments/${snap1.id}/compare/${snap2.id}`, comparison],
  [`/api/v1/assessments/${snap1.id}/compare/notcomparable`, notComparable],
])

globalThis.fetch = async (path) => {
  const body = routes.get(path)
  if (body === undefined) {
    return { ok: false, status: 404, json: async () => ({ code: 'not_found', message: `unstubbed ${path}` }) }
  }
  return { ok: true, status: 200, json: async () => body }
}

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })
try {
  const adapter = await server.ssrLoadModule('/src/services/assessment.ts')

  // list：summary → list item（id + createdAt 原样）。
  const items = await adapter.listAssessments(snap1.scope.review_id)
  check('listAssessments 返回全部 summary', items.length === list.length)
  check('list item 保持 id/createdAt', items[0]?.id === list[0].id && items[0]?.createdAt === list[0].created_at)

  // SCORABLE 快照映射。
  const vm1 = await adapter.getAssessment(snap1.id)
  check('rubric 版本透传', vm1.rubricTitle === '切片标准-量化' && vm1.rubricRevision === 1)
  check('materialScope 人话', vm1.materialScope === '1 份材料', vm1.materialScope)
  const c1 = vm1.criteria[0]
  check('criterion assessed', c1?.state === 'assessed', c1?.state)
  check('区间保持 16–20 / 20', c1?.scoring?.kind === 'range' && c1.scoring.min === 16 && c1.scoring.max === 20 && c1.scoring.outOf === 20, JSON.stringify(c1?.scoring))
  check('anchor label 映射为「充分」', c1?.levelLabel === '充分', c1?.levelLabel)
  check('caveats 透传', Array.isArray(c1?.caveats) && c1.caveats.length === 1 && c1.caveats[0].includes('样本量'))
  check('why ← rationale', typeof c1?.why === 'string' && c1.why.length > 0)
  const s1 = c1?.sources?.[0]
  check('source 映射 material/block/span/quote', Boolean(s1?.materialId && s1?.blockId && typeof s1?.start === 'number' && typeof s1?.end === 'number' && s1?.quote))
  check('source materialLabel 来自 scope.materials', s1?.materialLabel === 'slice.md', s1?.materialLabel)
  check('source locator 来自 scope.blocks（locator 对象或 null，不伪造）', s1?.locator === null || typeof s1?.locator?.kind === 'string')
  check('total 为 range 16–20 / 20', vm1.total?.kind === 'range' && vm1.total.min === 16 && vm1.total.max === 20 && vm1.total.outOf === 20, JSON.stringify(vm1.total))

  // NOT_SCORABLE 快照映射。
  const vm3 = await adapter.getAssessment(snap3.id)
  const c3 = vm3.criteria[0]
  check('not_scorable 状态映射', c3?.state === 'not_scorable', c3?.state)
  check('not_scorable 无分数位', c3?.scoring?.kind === 'none' && c3?.levelLabel === null)
  check('not_scorable total 为 not_scorable（非 unavailable 列表）', vm3.total?.kind === 'not_scorable', JSON.stringify(vm3.total))

  // COMPARISON 映射。
  const cmp = await adapter.compareAssessments(snap1.id, snap2.id)
  check('comparable 映射', cmp?.kind === 'comparable', JSON.stringify(cmp).slice(0, 120))
  const entry = cmp?.entries?.[0]
  check('observation 透传 range_shifted_downward', entry?.observation === 'range_shifted_downward', entry?.observation)
  check('三布尔独立为真', entry?.scoreChanged === true && entry?.anchorChanged === true && entry?.reasonChanged === true)
  check('before 区间 16–20', entry?.before?.scoring?.kind === 'range' && entry.before.scoring.min === 16)
  check('after exact 5 / 20', entry?.after?.scoring?.kind === 'score' && entry.after.scoring.value === 5 && entry.after.scoring.outOf === 20, JSON.stringify(entry?.after?.scoring))
  check('entry title 来自 after 快照 rubric', entry?.title === '性能声明要有测试条件', entry?.title)

  // not_comparable 映射。
  globalThis.fetch = async (path) => {
    if (path === `/api/v1/assessments/${snap1.id}/compare/${snap2.id}`) {
      return { ok: true, status: 200, json: async () => notComparable }
    }
    if (path === `/api/v1/assessments/${snap2.id}`) {
      return { ok: true, status: 200, json: async () => snap2 }
    }
    return { ok: false, status: 404, json: async () => ({ code: 'not_found', message: 'unstubbed' }) }
  }
  const ncmp = await adapter.compareAssessments(snap1.id, snap2.id)
  check('not_comparable 映射 reasonCodes', ncmp?.kind === 'not_comparable' && ncmp.reasonCodes?.[0] === 'prompt_version_mismatch', JSON.stringify(ncmp))
} finally {
  await server.close()
}

let failed = 0
for (const r of results) {
  if (!r.ok) failed += 1
  console.log(`${r.ok ? 'PASS' : 'FAIL'} ${r.name}${r.detail ? ' | ' + r.detail : ''}`)
}
console.log(`SUMMARY: ${results.length - failed}/${results.length} passed`)
process.exit(failed > 0 ? 1 : 0)
