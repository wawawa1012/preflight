// 可解释评估（Assessment）的展示 VM：只解决反复出现的展示 concern，不是第二套 DTO。
// wire truth 永远是 generated contracts（types/contracts.ts）；
// services/assessment.ts 是唯一适配边界，负责把真实契约映射到这里。
// 在 DS-B 的 Assessment contract checkpoint 落地前，本 VM 字段即冻结的展示需求清单；
// 契约字段名不同时由 adapter 适配，页面与组件不直接读 wire 类型。
import type { Locator } from './contracts'

// 评估条目状态：四种结果状态严格区分，绝不互相折叠，也绝不折叠成分数 0。
export type CriterionAssessmentState =
  | 'assessed' // 已评估（可能有分数/区间/档位，也可能标准未定义量化评分）
  | 'insufficient' // 依据不足
  | 'abstain' // 无法判断
  | 'failed' // 执行失败

// 量化呈现：有真实 scoring anchors 才存在 range/score/level；否则 kind='none'。
// range 必须保持区间呈现，不得压扁成中点。
export type ScoringVM =
  | { kind: 'range'; min: number; max: number; outOf: number }
  | { kind: 'score'; value: number; outOf: number }
  | { kind: 'level'; label: string; outOf: number | null }
  | { kind: 'none' }

// 来源 chip：与 Reader target 同构（material + block + span + quote），
// locator 只做展示（一律经 locatorLabel），Assessment 页面不理解 locator.kind。
export interface AssessmentSourceVM {
  materialId: string
  materialLabel: string
  blockId: string
  start: number
  end: number
  quote: string
  locator: Locator | null
}

export interface CriterionAssessmentVM {
  criterionId: string
  title: string
  state: CriterionAssessmentState
  scoring: ScoringVM
  // 档位/anchor 的人话（如「良好」），无则为 null。
  levelLabel: string | null
  // 为什么：解释性判断，依据不足/无法判断时说明原因。
  why: string
  sources: AssessmentSourceVM[]
  // 还缺什么：缺失条件/证据的人话列表。
  missing: string[]
}

// 总分规则（前端不计算，只呈现 backend 结论）：
// - range/score：所有必要、可评分 Criterion 都有有效评估。
// - unavailable：存在依据不足/无法判断/执行失败导致无法完整计算，pendingCriteria 列出缺依据的条目名。
// - not_scorable：该标准整体未定义量化评分。
export type AssessmentTotalVM =
  | { kind: 'range'; min: number; max: number; outOf: number }
  | { kind: 'score'; value: number; outOf: number }
  | { kind: 'unavailable'; pendingCriteria: string[] }
  | { kind: 'not_scorable' }

// Snapshot：一次在固定标准、材料范围和方法下的评估结果。不可原地编辑，重新评估生成新 Snapshot。
export interface AssessmentSnapshotVM {
  id: string
  createdAt: string
  rubricTitle: string
  rubricRevision: number
  // 人话材料范围，如「3 份材料」；方法版本放次级详情。
  materialScope: string
  methodNote: string
  total: AssessmentTotalVM
  criteria: CriterionAssessmentVM[]
}

export interface CriterionComparisonVM {
  criterionId: string
  title: string
  // before 为 null = newly assessable：「本次已有足够依据进行评估」，不是「从 0 分提升」。
  before: CriterionAssessmentVM | null
  after: CriterionAssessmentVM
  // 为什么发生变化（backend 给出的解释）。
  changeNote: string
}

// 可比性只能由 backend 判定；前端不按标题/时间自己猜。
export type AssessmentComparisonVM =
  | { kind: 'comparable'; entries: CriterionComparisonVM[] }
  // 不可比较时说明哪一项变了：标准版本 / 评估方法 / 材料范围。
  | { kind: 'not_comparable'; changedAspects: string[] }
