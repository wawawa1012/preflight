import type { AssessmentTotalVM, CriterionAssessmentState, ScoringVM } from '../types/assessment'

// 可解释评估的全部用户文案冻结于此：组件只引用，不各自造句。
// 总原则：这是「按当前标准和材料依据得到的评估」，不是真实质量的客观分数；
// 依据不足/无法判断/执行失败/未定义量化评分严格区分，绝不折叠成 0 分。

export function criterionStateLabel(state: CriterionAssessmentState): string {
  switch (state) {
    case 'assessed':
      return '已评估'
    case 'insufficient':
      return '依据不足'
    case 'abstain':
      return '本次无法判断'
    case 'failed':
      return '评估执行失败'
    case 'not_scorable':
      return '该标准未定义量化评分'
  }
}

// 区间保持区间：12–15 / 20 绝不压扁成中点；未定义量化评分返回 null，由卡片展示说明。
export function scoringText(scoring: ScoringVM): string | null {
  switch (scoring.kind) {
    case 'range':
      return `${scoring.min}–${scoring.max} / ${scoring.outOf}`
    case 'score':
      return `${scoring.value} / ${scoring.outOf}`
    case 'level':
      return scoring.label
    case 'none':
      return null
  }
}

export const NOT_SCORABLE_NOTE = '该标准未定义量化评分'
export const NOT_SCORABLE_HINT = '仍可参考下方的解释、依据与缺口；如需打分，请在标准中为该条补充评分档位。'

// 总分：只有 backend 判定完整可计算才出现数字；否则如实说明哪几项缺依据。
export function totalText(total: AssessmentTotalVM): { headline: string; detail: string | null } {
  switch (total.kind) {
    case 'range':
      return { headline: `${total.min}–${total.max} / ${total.outOf}`, detail: null }
    case 'score':
      return { headline: `${total.value} / ${total.outOf}`, detail: null }
    case 'unavailable':
      return {
        headline: '总分暂不可计算',
        detail: `还有 ${total.pendingCriteria.length} 项没有足够评估依据：${total.pendingCriteria.join('、')}`,
      }
    case 'not_scorable':
      return { headline: '该标准未定义量化评分', detail: '各条目仍提供解释、依据与缺口。' }
  }
}

// 比较：不可比较时按 backend reason code 如实说明；prompt/model 差异用普通用户语言，
// 内部配置名（provider/model 标识）不进主路径。
export const NOT_COMPARABLE_NOTES: Record<string, string> = {
  review_mismatch: '两次评估不属于同一个审查，不能直接比较。',
  rubric_mismatch: '使用的标准不同，两次结果不能直接比较。',
  method_mismatch: '评估方法版本发生变化，两次结果不能直接比较。',
  prompt_version_mismatch: '评估方法的执行条件发生变化，因此不能把两次结果直接归因于材料修改。',
  model_identifier_mismatch: '本次使用的评估模型与上次不同，两次结果暂不直接比较。',
  scoring_definition_mismatch: '标准的评分档位定义发生变化，两次结果不能直接比较。',
  source_policy_mismatch: '评估使用的来源范围规则发生变化，两次结果不能直接比较。',
  criterion_scope_mismatch: '两次评估覆盖的标准条目不同，不能直接比较。',
  material_scope_mismatch: '材料范围发生变化，两次结果不能直接比较。',
  invalid_snapshot: '其中一次评估快照无效，无法比较。',
}

// 比较观察（observation）的用户文案：逐条解释「为什么列为这种变化」。
export const COMPARISON_OBSERVATION_NOTES: Record<string, string> = {
  identical: '本次评估结果未见变化',
  anchor_changed: '评分档位发生变化',
  reason_changed: '评估原因发生变化',
  status_changed: '评估状态发生变化',
  newly_assessable: '本次已有足够依据进行评估',
  became_insufficient: '本次评估依据不足',
  range_overlaps: '两次评估区间有重叠',
  // range_shifted_upward / downward 无独立文案：before → after 的区间本身已说明方向。
}

// 三个变化维度独立为真、并列展示，互不覆盖。
export const COMPARISON_FLAG_NOTES = {
  score: '评分/区间发生变化',
  anchor: '评分档位发生变化',
  reason: '评估原因发生变化',
} as const

// 因果边界：同口径观察 ≠ 修改效果的因果证明。
export const COMPARISON_TRUTH_NOTE =
  '以下对比是同口径下观察到的评估变化，不构成修改效果的因果证明。'

// 页面级诚实声明（页脚常量）。
export const ASSESSMENT_TRUTH_NOTE =
  '评估结果按当前标准与已确认的材料依据得出，不是对作品真实质量的客观评分。'

// 卡片分节标签（与模拟评审卡的「触发依据 / 你需要准备什么」同族）。
export const SOURCES_SECTION_LABEL = '依据'
export const MISSING_SECTION_LABEL = '还缺什么'
