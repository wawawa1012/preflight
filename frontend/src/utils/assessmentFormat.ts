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

// 比较：不可比较时说明哪一项变了；可比时逐条 Before → After。
export const COMPARISON_ASPECT_LABELS: Record<string, string> = {
  rubric: '标准版本',
  method: '评估方法',
  materials: '材料范围',
}

export const RANGE_OVERLAP_NOTE = '两次评估区间有重叠'
export const NEWLY_ASSESSABLE_NOTE = '本次已有足够依据进行评估'

// 页面级诚实声明（页脚常量）。
export const ASSESSMENT_TRUTH_NOTE =
  '评估结果按当前标准与已确认的材料依据得出，不是对作品真实质量的客观评分。'

// 卡片分节标签（与模拟评审卡的「触发依据 / 你需要准备什么」同族）。
export const SOURCES_SECTION_LABEL = '依据'
export const MISSING_SECTION_LABEL = '还缺什么'
