// Sprint 4 可解释评估 leaf 组件检查（真实 SSR 渲染 + 源码纪律，不引入测试框架）：
// 四个 leaf 组件（CriterionAssessmentCard / AssessmentSummary / AssessmentSnapshotMeta / AssessmentCompare）
// 按 VM 呈现：
//   - 区间保持 12–15 / 20，绝不压成中点；assessed+none 只说未定义量化评分；
//   - insufficient/abstain/failed 不显示分数，状态文案如实；
//   - total unavailable/not_scorable 中性呈现并列出缺依据条目；
//   - compare 不可比较说明变化项、newly assessable 不说「从 0 分」、重叠区间显示重叠说明。
// 合成数据只存在于本脚本（test-only）。
// 运行：cd frontend && node scripts/check-assessment.mjs
import { readFileSync } from 'node:fs'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const results = []
const check = (name, ok, detail = '') => results.push({ name, ok: Boolean(ok), detail })

const cardPath = '/src/components/review/assessment/CriterionAssessmentCard.vue'
const summaryPath = '/src/components/review/assessment/AssessmentSummary.vue'
const metaPath = '/src/components/review/assessment/AssessmentSnapshotMeta.vue'
const comparePath = '/src/components/review/assessment/AssessmentCompare.vue'

const sourceFiles = {
  card: readFileSync(new URL('../src/components/review/assessment/CriterionAssessmentCard.vue', import.meta.url), 'utf8'),
  summary: readFileSync(new URL('../src/components/review/assessment/AssessmentSummary.vue', import.meta.url), 'utf8'),
  meta: readFileSync(new URL('../src/components/review/assessment/AssessmentSnapshotMeta.vue', import.meta.url), 'utf8'),
  compare: readFileSync(new URL('../src/components/review/assessment/AssessmentCompare.vue', import.meta.url), 'utf8'),
}

const RANGE_TEXT = '12–15 / 20'
const NOT_SCORABLE = '该标准未定义量化评分'
const NEWLY_NOTE = '本次已有足够依据进行评估'
const OVERLAP_NOTE = '两次评估区间有重叠'

function source(overrides = {}) {
  return {
    materialId: 'mat_a',
    materialLabel: 'Alpha.md',
    blockId: 'blk_a1',
    start: 4,
    end: 12,
    quote: '准确率达到 95%',
    locator: { kind: 'line', index: 7 },
    ...overrides,
  }
}

function item(overrides = {}) {
  return {
    criterionId: 'c1',
    title: '方法可复现性',
    state: 'assessed',
    scoring: { kind: 'range', min: 12, max: 15, outOf: 20 },
    levelLabel: '良好',
    why: '两次实验都给出了完整操作步骤与随机种子。',
    sources: [source()],
    missing: [],
    ...overrides,
  }
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' })

try {
  const mod = {}
  for (const [key, path] of Object.entries({ card: cardPath, summary: summaryPath, meta: metaPath, compare: comparePath })) {
    mod[key] = (await server.ssrLoadModule(path)).default
  }

  async function render(component, props) {
    const app = createSSRApp(component, props)
    return renderToString(app)
  }

  // 1. assessed + range：区间原样显示，绝不压成中点。
  const rangeHtml = await render(mod.card, { item: item() })
  check(
    '卡片 assessed+range 显示区间 12–15 / 20',
    rangeHtml.includes(RANGE_TEXT),
    rangeHtml.slice(0, 200),
  )
  check(
    '区间不压成中点单值',
    !rangeHtml.includes('13.5') && !rangeHtml.includes('13 / 20'),
  )
  check(
    '依据 chip 显示 quote + 位置 + 材料',
    rangeHtml.includes('准确率达到 95%') && rangeHtml.includes('第 7 行') && rangeHtml.includes('Alpha.md'),
  )
  check('卡片提供 open-source 动作入口', sourceFiles.card.includes("emit('open-source', source)"))

  // 2. assessed + scoring none：不显示分数位，只说未定义量化评分。
  const noneHtml = await render(mod.card, { item: item({ scoring: { kind: 'none' }, levelLabel: null }) })
  check('卡片 assessed+none 显示「该标准未定义量化评分」', noneHtml.includes(NOT_SCORABLE), noneHtml.slice(0, 200))
  check('卡片 assessed+none 不出现分数位', !noneHtml.includes('/ 20') && !noneHtml.includes(RANGE_TEXT))

  // 3. insufficient：状态文案如实，且不显示数字分数（即便 VM 带 scoring）。
  const insufficientHtml = await render(mod.card, {
    item: item({ state: 'insufficient', scoring: { kind: 'range', min: 5, max: 9, outOf: 20 }, missing: ['缺少对照组说明'] }),
  })
  check('卡片 insufficient 显示「依据不足」', insufficientHtml.includes('依据不足'))
  check('卡片 insufficient 不出现数字分数', !insufficientHtml.includes('/ 20') && !insufficientHtml.includes('5–9'))
  check('卡片 insufficient 呈现 missing 缺口', insufficientHtml.includes('缺少对照组说明'))

  // 4. abstain / failed 状态文案。
  const abstainHtml = await render(mod.card, { item: item({ state: 'abstain' }) })
  check('卡片 abstain 显示「本次无法判断」', abstainHtml.includes('本次无法判断'))
  const failedHtml = await render(mod.card, { item: item({ state: 'failed' }) })
  check('卡片 failed 显示「评估执行失败」', failedHtml.includes('评估执行失败'))

  // 5. 总分：unavailable 中性呈现且列出缺依据条目；not_scorable 中性。
  const unavailableHtml = await render(mod.summary, {
    total: { kind: 'unavailable', pendingCriteria: ['方法可复现性', '结果一致性'] },
  })
  check('总分 unavailable 显示「总分暂不可计算」', unavailableHtml.includes('总分暂不可计算'))
  check(
    '总分 unavailable 列出缺依据条目名',
    unavailableHtml.includes('方法可复现性') && unavailableHtml.includes('结果一致性'),
  )
  const notScorableHtml = await render(mod.summary, { total: { kind: 'not_scorable' } })
  check('总分 not_scorable 显示「该标准未定义量化评分」', notScorableHtml.includes(NOT_SCORABLE))
  check('总分不可计算不用红色警报', !sourceFiles.summary.includes('text-red'))

  // 6. Snapshot 元信息：主行三要素 + 方法进 details。
  const metaHtml = await render(mod.meta, {
    snapshot: {
      id: 'snap_1',
      createdAt: '2026-09-21T10:00:00.000Z',
      rubricTitle: '科研申报标准',
      rubricRevision: 3,
      materialScope: '3 份材料',
      methodNote: '评估方法 v2：逐条对照标准档位。',
      total: { kind: 'not_scorable' },
      criteria: [],
    },
  })
  check(
    '元信息主行含标准版本与材料范围',
    metaHtml.includes('科研申报标准') && metaHtml.includes('v3') && metaHtml.includes('3 份材料'),
  )
  check('元信息方法收进 details', metaHtml.includes('<details') && metaHtml.includes('评估方法 v2：逐条对照标准档位。'))

  // 7. compare：不可比较说明变化项。
  const notComparableHtml = await render(mod.compare, {
    comparison: { kind: 'not_comparable', changedAspects: ['rubric', 'materials'] },
  })
  check(
    'compare not_comparable 说明变化项',
    notComparableHtml.includes('两次评估不可直接比较') &&
      notComparableHtml.includes('标准版本') &&
      notComparableHtml.includes('材料范围') &&
      notComparableHtml.includes('已变化'),
  )

  const entryTitle = '方法可复现性'
  // before=null → newly assessable，不是「从 0 分」。
  const newlyHtml = await render(mod.compare, {
    comparison: {
      kind: 'comparable',
      entries: [
        { criterionId: 'c1', title: entryTitle, before: null, after: item(), changeNote: '补充了实验步骤。' },
      ],
    },
  })
  check('compare before=null 显示「本次已有足够依据进行评估」', newlyHtml.includes(NEWLY_NOTE))
  check('compare before=null 不出现「从 0 分」', !newlyHtml.includes('从 0 分') && !newlyHtml.includes('从0分'))

  // 每条 criterion：before → after 的分数/区间展示 + changeNote。
  const scoreHtml = await render(mod.compare, {
    comparison: {
      kind: 'comparable',
      entries: [
        {
          criterionId: 'c2',
          title: entryTitle,
          before: item({ scoring: { kind: 'score', value: 10, outOf: 20 } }),
          after: item({ scoring: { kind: 'range', min: 12, max: 15, outOf: 20 } }),
          changeNote: '依据补充后区间上移。',
        },
      ],
    },
  })
  check('compare 显示 before 分数 / after 区间', scoreHtml.includes('10 / 20') && scoreHtml.includes(RANGE_TEXT))
  check('compare 显示 changeNote', scoreHtml.includes('依据补充后区间上移。'))

  // 重叠区间 → RANGE_OVERLAP_NOTE（纯几何事实）。
  const overlapHtml = await render(mod.compare, {
    comparison: {
      kind: 'comparable',
      entries: [
        {
          criterionId: 'c3',
          title: entryTitle,
          before: item({ scoring: { kind: 'range', min: 10, max: 15, outOf: 20 } }),
          after: item({ scoring: { kind: 'range', min: 12, max: 15, outOf: 20 } }),
          changeNote: '补充依据后区间收窄。',
        },
      ],
    },
  })
  check('compare 重叠区间显示「两次评估区间有重叠」', overlapHtml.includes(OVERLAP_NOTE))
  check('compare 提供 open-source 动作入口', sourceFiles.compare.includes("emit('open-source', source)"))

  // 8. 措辞纪律：四个组件源码不含禁用词、不出现「提升 N 分」。
  const banned = ['AI 评分', '真实得分', '最终得分', 'confidence', '置信度']
  const allSource = Object.values(sourceFiles).join('\n')
  check(
    '组件源码不含禁用词',
    banned.every((word) => !allSource.includes(word)),
    banned.filter((word) => allSource.includes(word)).join('、'),
  )
  check('组件源码不含 AI评分（无空格变体）', !allSource.includes('AI评分'))
  const boostPattern = /提升\s*\d+(?:\.\d+)?\s*分/
  check('组件源码不含「提升 N 分」表述', !boostPattern.test(allSource))

  // 9. 边界纪律：组件不发请求、不读 store、不解释 locator.kind。
  check(
    '组件不发请求、不读 store',
    Object.values(sourceFiles).every((text) => !/\bfetch\s*\(/.test(text) && !text.includes('useSessionStore')),
  )
  check(
    '来源位置一律经 locatorLabel',
    sourceFiles.card.includes('locatorLabel(source.locator)') &&
      sourceFiles.compare.includes('locatorLabel(source.locator)') &&
      !allSource.includes('locator.kind'),
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
