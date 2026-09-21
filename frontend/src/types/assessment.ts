// 可解释评估（Assessment）的展示 VM：只解决反复出现的展示 concern，不是第二套 DTO。
// wire truth 永远是 generated contracts（types/contracts.ts）；
// services/assessment.ts 是唯一适配边界，负责把真实契约映射到这里。
// 在 DS-B 的 Assessment contract checkpoint 落地前，本 VM 字段即冻结的展示需求清单；
// 契约字段名不同时由 adapter 适配，页面与组件不直接读 wire 类型。
import type { Locator } from './contracts'

// 评估条目状态：五种结果状态严格区分，绝不互相折叠，也绝不折叠成分数 0。
// 与 generated contract 的 AssessmentResult.status 一一对应（adapter 负责映射）。
export type CriterionAssessmentState =
  | 'assessed' // 已评估（标准定义了量化评分时有分数/区间/档位）
  | 'insufficient' // 依据不足（无 accepted 来源，或评估方报告依据不足；永不是 0 分）
  | 'abstain' // 无法判断
  | 'failed' // 执行失败（来源校验/响应/执行失败；兄弟条目保留）
  | 'not_scorable' // 该条目未定义量化评分；来源仍可查看，解释确定性生成

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
  // 注意事项（caveats）：评估方对本次判断的保留说明，低权重呈现。
  caveats: string[]
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

// 快照列表项：GET .../assessments 返回 summary（无 criteria/materials 明细），
// 只够渲染选择器；选中后由 getAssessment 拉完整 Snapshot。
export interface AssessmentListItemVM {
  id: string
  createdAt: string
}

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

// 比较条目：before/after 都是真实评估结果（newly_assessable 时 before 也存在，状态为不足/无法判断）。
// observation 与三个布尔都来自 backend，互不覆盖：score/anchor/reason 任一维度独立为真。
export interface CriterionComparisonVM {
  criterionId: string
  title: string
  before: CriterionAssessmentVM
  after: CriterionAssessmentVM
  // generated contract 的 observation 枚举原样透传（identical/anchor_changed/reason_changed/
  // status_changed/newly_assessable/became_insufficient/range_overlaps/range_shifted_upward/downward）。
  observation: string
  scoreChanged: boolean
  anchorChanged: boolean
  reasonChanged: boolean
}

// 可比性只能由 backend 判定；前端不按标题/时间自己猜。
export type AssessmentComparisonVM =
  | { kind: 'comparable'; entries: CriterionComparisonVM[] }
  // 不可比较时携带 backend reason codes，文案映射冻结在 assessmentFormat。
  | { kind: 'not_comparable'; reasonCodes: string[] }
