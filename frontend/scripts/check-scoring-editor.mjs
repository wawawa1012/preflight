// Sprint 4 minimal scoring editor 纯函数级检查（vite ssrLoadModule 加载 criteriaSource.ts，不渲染组件）：
//   - preparePublish 预检与 backend Criterion.executable_scoring 对齐：
//       exact 与 range 同时填 / range 超 max_score / 档位只有 1 条 / max_score 缺失 均被拦下；
//       合法两档（一档 exact、一档 range）被接受；
//   - manualSourceSnapshot 诚实序列化用户定义的评分档位；发布 source_text 非空且含档位名称；
//   - draft 级 scoring_aggregation 联动。
// 运行：cd frontend && node scripts/check-scoring-editor.mjs
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

function criterion(overrides = {}) {
  return {
    id: 'c1',
    title: '性能数字',
    requirement: '给出测试条件',
    required_evidence: [],
    order: 0,
    scoring_definition_version: 'anchors-v1',
    max_score: 20,
    rubric_levels: [
      { label: '优秀', description: '条件充分', anchor_id: 'a1', score: 18 },
      { label: '合格', description: '条件基本满足', anchor_id: 'a2', min_score: 10, max_score: 15 },
    ],
    ...overrides,
  }
}

function manualDraft(criteria) {
  return {
    title: '量化标准',
    source_note: '手工创建',
    source_type: 'manual',
    source_text: '',
    model_assisted: false,
    criteria,
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const criteriaModule = await server.ssrLoadModule('/src/services/criteriaSource.ts')

  // 1. 合法两档（exact + range）被接受，并联动 scoring_aggregation。
  const valid = criteriaModule.preparePublish(manualDraft([criterion()]))
  check('合法两档（一档固定分值、一档区间）被接受', valid.ok === true, JSON.stringify(valid.problems))
  check('任一 criterion 量化时 payload 带 scoring_aggregation=sum_points_v1', valid.payload?.scoring_aggregation === 'sum_points_v1')

  // 2. exact 与 range 同时填被拦下。
  const both = criteriaModule.preparePublish(
    manualDraft([
      criterion({
        rubric_levels: [
          { label: 'A', description: 'da', anchor_id: 'a1', score: 5, min_score: 1, max_score: 3 },
          { label: 'B', description: 'db', anchor_id: 'a2', score: 2 },
        ],
      }),
    ]),
  )
  check(
    'exact 与 range 同时填被拦下',
    both.ok === false && both.problems.some((problem) => problem.includes('不能同时填写')),
    both.problems.join(' / '),
  )

  // 3. 区间超 max_score 被拦下。
  const over = criteriaModule.preparePublish(
    manualDraft([
      criterion({
        max_score: 20,
        rubric_levels: [
          { label: 'A', description: 'da', anchor_id: 'a1', min_score: 10, max_score: 25 },
          { label: 'B', description: 'db', anchor_id: 'a2', score: 2 },
        ],
      }),
    ]),
  )
  check(
    'range 超 max_score 被拦下',
    over.ok === false && over.problems.some((problem) => problem.includes('区间必须满足')),
    over.problems.join(' / '),
  )

  // 4. 档位只有 1 条被拦下。
  const single = criteriaModule.preparePublish(
    manualDraft([criterion({ rubric_levels: [{ label: 'A', description: 'da', anchor_id: 'a1', score: 5 }] })]),
  )
  check(
    '档位只有 1 条被拦下',
    single.ok === false && single.problems.some((problem) => problem.includes('至少需要两个评分档位')),
    single.problems.join(' / '),
  )

  // 5. max_score 缺失被拦下。
  const noMax = criteriaModule.preparePublish(
    manualDraft([
      criterion({
        max_score: null,
        rubric_levels: [
          { label: '优秀', description: '条件充分', anchor_id: 'a1', score: 18 },
          { label: '合格', description: '条件基本满足', anchor_id: 'a2', min_score: 10, max_score: 15 },
        ],
      }),
    ]),
  )
  check(
    'max_score 缺失被拦下',
    noMax.ok === false && noMax.problems.some((problem) => problem.includes('满分必须填写')),
    noMax.problems.join(' / '),
  )

  // 6. 区间只填一侧（未同时给上下限）被拦下。
  const halfRange = criteriaModule.preparePublish(
    manualDraft([
      criterion({
        rubric_levels: [
          { label: 'A', description: 'da', anchor_id: 'a1', min_score: 10 },
          { label: 'B', description: 'db', anchor_id: 'a2', score: 2 },
        ],
      }),
    ]),
  )
  check(
    '区间只填一侧被拦下',
    halfRange.ok === false && halfRange.problems.some((problem) => problem.includes('必须同时填写下限与上限')),
    halfRange.problems.join(' / '),
  )

  // 7. manualSourceSnapshot 诚实序列化评分档位。
  const snapshot = criteriaModule.manualSourceSnapshot(manualDraft([criterion()]))
  check(
    'manualSourceSnapshot 含满分、档位名称与分值/区间',
    snapshot.includes('满分 20') &&
      snapshot.includes('优秀') &&
      snapshot.includes('18 分') &&
      snapshot.includes('合格') &&
      snapshot.includes('10–15 分'),
    snapshot,
  )

  // 8. 发布快照非空且包含档位名称。
  const publishedText = valid.payload?.source_text ?? ''
  check(
    '发布 source_text 非空且包含档位名称',
    publishedText.trim() !== '' && publishedText.includes('优秀') && publishedText.includes('合格') && publishedText.includes('评分档位'),
    publishedText,
  )

  // 9. 全部不量化：payload 不出现 scoring_aggregation。
  const plain = criteriaModule.preparePublish(
    manualDraft([{ id: 'c1', title: 't', requirement: 'r', required_evidence: [], order: 0 }]),
  )
  check('全部不量化时被接受', plain.ok === true, JSON.stringify(plain.problems))
  check(
    '全部不量化时 payload 不含 scoring_aggregation',
    !JSON.stringify(plain.payload ?? {}).includes('scoring_aggregation'),
  )

  // 10. 部分量化、部分不量化被接受（总分交由 backend 判定）。
  const partial = criteriaModule.preparePublish(
    manualDraft([
      criterion(),
      { id: 'c2', title: '叙述清晰度', requirement: '表达清楚', required_evidence: [], order: 1 },
    ]),
  )
  check('允许部分 criterion 量化、部分不量化', partial.ok === true, JSON.stringify(partial.problems))
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
