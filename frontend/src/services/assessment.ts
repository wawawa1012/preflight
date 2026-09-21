import type {
  AssessmentComparisonVM,
  AssessmentListItemVM,
  AssessmentSnapshotVM,
  AssessmentSourceVM,
  AssessmentTotalVM,
  CriterionAssessmentState,
  CriterionAssessmentVM,
  CriterionComparisonVM,
  ScoringVM,
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
//   先取 after 快照（comparison 响应不含 scope）；toComparisonVM 用 after 快照的 criteria/sources/
//   blocks/materials 做条目映射与标题回退（取不到 criterion 用 criterion_id）。
//   status 'comparable' → entries ← criteria[]：before/after 各按上面的条目映射（复用同一函数），
//     observation 原样透传，scoreChanged/anchorChanged/reasonChanged ← 同名布尔，互不覆盖。
//   status 'not_comparable' → { kind:'not_comparable', reasonCodes: reason_codes 原样 }。
//
// 禁止：复制 wire DTO 出去、前端推断 comparable、前端汇总总分、伪造 locator。

import type {
  AssessmentAggregation,
  AssessmentComparison,
  AssessmentResult,
  AssessmentSnapshot,
  AssessmentSource,
  AssessmentSummary,
  Block,
  Criterion,
  EvaluationScope,
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
  const [comparison, afterSnapshot] = await Promise.all([
    request<AssessmentComparison>(`/api/v1/assessments/${beforeId}/compare/${afterId}`),
    request<AssessmentSnapshot>(`/api/v1/assessments/${afterId}`),
  ])
  return toComparisonVM(comparison, afterSnapshot)
}

// ---- 映射实现（worker 补全；签名与返回 VM 已冻结） ----

// 一次评估快照的只读索引：wire 身份 → VM 所需元数据。只在适配层构造，不泄漏 wire 类型。
interface ScopeIndex {
  scope: EvaluationScope
  criteriaById: Map<string, Criterion>
  criteriaOrder: Map<string, number>
  materialLabels: Map<string, string>
  blocksById: Map<string, Block>
  sourcesByLinkId: Map<string, AssessmentSource>
  outOf: number
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function buildScopeIndex(scope: EvaluationScope): ScopeIndex {
  const criteriaById = new Map<string, Criterion>()
  const criteriaOrder = new Map<string, number>()
  scope.rubric.criteria.forEach((criterion, index) => {
    criteriaById.set(criterion.id, criterion)
    criteriaOrder.set(criterion.id, index)
  })
  const materialLabels = new Map(scope.materials.map((material) => [material.material_id, material.label]))
  const blocksById = new Map(scope.blocks.map((block) => [block.id, block]))
  const sourcesByLinkId = new Map(scope.sources.map((source) => [source.link.id, source]))
  // 唯一允许的展示推导：把各 criterion 的满分相加作为分母；缺失/非数字不计入。
  const outOf = scope.rubric.criteria.reduce(
    (sum, criterion) => (isFiniteNumber(criterion.max_score) ? sum + criterion.max_score : sum),
    0,
  )
  return { scope, criteriaById, criteriaOrder, materialLabels, blocksById, sourcesByLinkId, outOf }
}

function mapState(status: AssessmentResult['status']): CriterionAssessmentState {
  switch (status) {
    case 'assessed':
      return 'assessed'
    case 'insufficient_evidence':
      return 'insufficient'
    case 'abstain':
      return 'abstain'
    case 'execution_failed':
      return 'failed'
    case 'not_scorable':
      return 'not_scorable'
  }
}

// 有真实 score 才映射分数/区间；分母取该 criterion 的 max_score，缺失/非数字则如实退回 kind:'none'。
function mapScoring(result: AssessmentResult, criterion: Criterion | undefined): ScoringVM {
  const score = result.score
  if (!score) return { kind: 'none' }
  const outOf = criterion && isFiniteNumber(criterion.max_score) ? criterion.max_score : null
  if (outOf === null) return { kind: 'none' }
  if (score.kind === 'exact') return { kind: 'score', value: score.minimum, outOf }
  return { kind: 'range', min: score.minimum, max: score.maximum, outOf }
}

// selected_anchor_id 在该 criterion 的 rubric_levels 里按 anchor_id 查 label；查不到为 null。
function mapLevelLabel(result: AssessmentResult, criterion: Criterion | undefined): string | null {
  const anchorId = result.selected_anchor_id
  if (!anchorId || !criterion?.rubric_levels) return null
  const level = criterion.rubric_levels.find((entry) => entry.anchor_id === anchorId)
  return level?.label ?? null
}

// source_ids 是 accepted link id：经 scope.sources 取回；查不到的来源跳过，不伪造。
function mapSources(result: AssessmentResult, index: ScopeIndex): AssessmentSourceVM[] {
  const sources: AssessmentSourceVM[] = []
  for (const sourceId of result.source_ids ?? []) {
    const source = index.sourcesByLinkId.get(sourceId)
    if (!source) continue
    const materialId = source.link.material_id
    const blockId = source.source.block_id
    sources.push({
      materialId,
      materialLabel: index.materialLabels.get(materialId) ?? materialId,
      blockId,
      start: source.source.start,
      end: source.source.end,
      quote: source.source.quote,
      // locator 只展示，一律不解释 kind；查不到为 null，绝不伪造。
      locator: index.blocksById.get(blockId)?.locator ?? null,
    })
  }
  return sources
}

function mapCriterionResult(
  result: AssessmentResult,
  criterion: Criterion | undefined,
  index: ScopeIndex,
  fallbackTitle: string,
): CriterionAssessmentVM {
  return {
    criterionId: result.criterion_id,
    title: criterion?.title ?? fallbackTitle,
    state: mapState(result.status),
    scoring: mapScoring(result, criterion),
    levelLabel: mapLevelLabel(result, criterion),
    why: result.rationale,
    sources: mapSources(result, index),
    missing: result.missing_conditions ?? [],
    caveats: result.caveats ?? [],
  }
}

function mapTotal(aggregation: AssessmentAggregation, index: ScopeIndex): AssessmentTotalVM {
  const pendingCriteria = aggregation.missing_criterion_ids.map(
    (criterionId) => index.criteriaById.get(criterionId)?.title ?? criterionId,
  )
  if (aggregation.status === 'available') {
    const score = aggregation.score
    // available 却没给 score 属于 backend 不一致：如实退回不可计算，绝不伪造数字。
    if (!score) return { kind: 'unavailable', pendingCriteria }
    if (score.kind === 'exact') return { kind: 'score', value: score.minimum, outOf: index.outOf }
    return { kind: 'range', min: score.minimum, max: score.maximum, outOf: index.outOf }
  }
  if (aggregation.scorable_criterion_count === 0) return { kind: 'not_scorable' }
  return { kind: 'unavailable', pendingCriteria }
}

function toSnapshotVM(snapshot: AssessmentSnapshot): AssessmentSnapshotVM {
  const index = buildScopeIndex(snapshot.scope)
  const criteria = snapshot.results
    .map((result) => {
      const criterion = index.criteriaById.get(result.criterion_id)
      // result 找不到对应 criterion 时跳过，不伪造标题。
      if (!criterion) return null
      return mapCriterionResult(result, criterion, index, result.criterion_id)
    })
    .filter((item): item is CriterionAssessmentVM => item !== null)
    .sort(
      (a, b) =>
        (index.criteriaOrder.get(a.criterionId) ?? 0) - (index.criteriaOrder.get(b.criterionId) ?? 0),
    )

  return {
    id: snapshot.id,
    createdAt: snapshot.created_at,
    rubricTitle: snapshot.scope.rubric.title,
    rubricRevision: snapshot.scope.rubric.revision,
    materialScope: `${snapshot.scope.materials.length} 份材料`,
    methodNote: `评估方法 ${snapshot.scope.assessment_method_version}`,
    total: mapTotal(snapshot.aggregation, index),
    criteria,
  }
}

// comparison 响应没有 scope：criterion 元数据与来源/块一律取自 after 快照（本次评估的依据）。
function toComparisonVM(
  comparison: AssessmentComparison,
  afterSnapshot: AssessmentSnapshot,
): AssessmentComparisonVM {
  if (comparison.status !== 'comparable') {
    return { kind: 'not_comparable', reasonCodes: comparison.reason_codes }
  }
  const index = buildScopeIndex(afterSnapshot.scope)
  const entries: CriterionComparisonVM[] = comparison.criteria.map((change) => {
    const criterion = index.criteriaById.get(change.criterion_id)
    return {
      criterionId: change.criterion_id,
      title: criterion?.title ?? change.criterion_id,
      before: mapCriterionResult(change.before, criterion, index, change.criterion_id),
      after: mapCriterionResult(change.after, criterion, index, change.criterion_id),
      // observation 与三个布尔原样透传，互不覆盖。
      observation: change.observation,
      scoreChanged: change.score_changed,
      anchorChanged: change.anchor_changed,
      reasonChanged: change.reason_changed,
    }
  })
  return { kind: 'comparable', entries }
}
