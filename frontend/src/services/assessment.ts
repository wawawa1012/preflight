import type {
  AssessmentComparisonVM,
  AssessmentListItemVM,
  AssessmentSnapshotVM,
} from '../types/assessment'

// Assessment 适配边界（唯一）：页面与组件只消费 types/assessment.ts 的展示 VM，
// wire truth 永远是 types/contracts.ts 的 generated 类型，映射只发生在本文件。
//
// Endpoints（backend wave4/assessment-core @ f38d4ca 已定稿）：
//   POST /api/v1/reviews/{reviewId}/assessments        → 201 AssessmentSnapshot
//   GET  /api/v1/reviews/{reviewId}/assessments        → AssessmentSummary[]（newest-first）
//   GET  /api/v1/assessments/{id}                      → AssessmentSnapshot
//   GET  /api/v1/assessments/{beforeId}/compare/{afterId} → AssessmentComparison
//
// 映射契约（DS 按此实现，不得发明字段、不得在前端重算 backend 结论）：
//
// listAssessments → AssessmentListItemVM[]：id 原样；createdAt 用现有时间格式化惯例。
//
// getAssessment / generateAssessment → AssessmentSnapshotVM：
//   rubricTitle/rubricRevision ← scope.rubric.title / scope.rubric.revision
//   materialScope ← scope.materials.length，人话如「3 份材料」
//   methodNote ← scope.assessment_method_version（次级详情原样呈现，不翻译）
//   total ← aggregation：
//     status 'available' 且 score 存在 → kind exact→'score'(value=minimum) / range→'range'(min,max)；
//       outOf = scope.rubric.criteria 的 max_score 之和（唯一允许的展示推导，不是重算总分）。
//     status 'unavailable' → pendingCriteria = missing_criterion_ids 映射 scope.rubric.criteria 的 title；
//       若 scorable_criterion_count === 0 → kind 'not_scorable'。
//   criteria[] ← results[] 逐条（criterion 元数据从 scope.rubric.criteria 按 criterion_id 取）：
//     status 映射：assessed→'assessed'，insufficient_evidence→'insufficient'，
//       abstain→'abstain'，execution_failed→'failed'，not_scorable→'not_scorable'。
//     scoring：result.score 存在 → exact→{kind:'score',value:minimum} / range→{kind:'range',min,max}，
//       outOf = 该 criterion 的 max_score；无 score → {kind:'none'}。
//       levelLabel ← selected_anchor_id 在 criterion.rubric_levels 中查 label，查不到为 null。
//     why ← rationale；missing ← missing_conditions ?? []；caveats ← caveats ?? []。
//     sources ← result.source_ids（= accepted link id）在 scope.sources 中查 AssessmentSource：
//       materialId/materialLabel ← link.material_id 对应 scope.materials 的 label；
//       blockId/start/end/quote ← source.source（SourceRef）；
//       locator ← scope.blocks 中按 block_id 查 block.locator，查不到为 null（不伪造）。
//
// compareAssessments(beforeId, afterId) → AssessmentComparisonVM：
//   status 'comparable' → entries ← criteria[]：before/after 各按上面的条目映射（复用同一函数），
//     observation 原样透传，scoreChanged/anchorChanged/reasonChanged ← 同名布尔，互不覆盖。
//   status 'not_comparable' → { kind:'not_comparable', reasonCodes: reason_codes 原样 }。
//
// 禁止：复制 wire DTO 出去、前端推断 comparable、前端汇总总分、伪造 locator。

import type {
  AssessmentComparison,
  AssessmentSnapshot,
  AssessmentSummary,
} from '../types/contracts'
import { ApiFailure } from './reviews'

// 与 criteriaSource 同族的本地 request：ApiFailure 携带 code/message 供页面呈现。
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
  }
  return body as T
}

// HTTP plumbing 是确定的，先接好；映射函数由实现 worker 按上方契约补全。

export async function listAssessments(reviewId: string): Promise<AssessmentListItemVM[]> {
  const summaries = await request<AssessmentSummary[]>(`/api/v1/reviews/${reviewId}/assessments`)
  return summaries.map((summary) => ({
    id: summary.id,
    createdAt: summary.created_at,
  }))
}

export async function getAssessment(id: string): Promise<AssessmentSnapshotVM> {
  return toSnapshotVM(await request<AssessmentSnapshot>(`/api/v1/assessments/${id}`))
}

export async function generateAssessment(reviewId: string): Promise<AssessmentSnapshotVM> {
  const snapshot = await request<AssessmentSnapshot>(`/api/v1/reviews/${reviewId}/assessments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return toSnapshotVM(snapshot)
}

export async function compareAssessments(
  beforeId: string,
  afterId: string,
): Promise<AssessmentComparisonVM> {
  const comparison = await request<AssessmentComparison>(
    `/api/v1/assessments/${beforeId}/compare/${afterId}`,
  )
  return toComparisonVM(comparison)
}

// ---- 映射实现（worker 补全；签名与返回 VM 已冻结） ----

function toSnapshotVM(_snapshot: AssessmentSnapshot): AssessmentSnapshotVM {
  throw new Error('assessment adapter: toSnapshotVM pending')
}

function toComparisonVM(_comparison: AssessmentComparison): AssessmentComparisonVM {
  throw new Error('assessment adapter: toComparisonVM pending')
}
