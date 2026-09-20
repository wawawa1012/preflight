import type { Rubric } from '../types/contracts'

// Criteria Builder / 自动首次 binding 的正式 wire contract 仍在 DS + Codex Gate 中。
// 本模块是 Wizard 与后端之间的唯一适配边界：Wizard 只面向 CriteriaResolution 编程，
// 不接触任何 Builder API 字段。契约冻结后在此实现 paste/upload/manual 三个分支。
export type CriteriaSource =
  | { kind: 'existing'; rubricKey: string }
  | { kind: 'paste'; text: string }
  | { kind: 'upload'; filename: string }
  | { kind: 'manual' }

export type CriteriaResolution =
  | { status: 'ready'; rubricId: string; rubricRevision: number }
  | { status: 'unavailable'; reason: 'builder_contract_pending' }

export function resolveCriteriaSource(source: CriteriaSource, rubrics: Rubric[]): CriteriaResolution {
  if (source.kind !== 'existing') return { status: 'unavailable', reason: 'builder_contract_pending' }
  const rubric = rubrics.find((entry) => `${entry.id}:${entry.revision}` === source.rubricKey)
  if (!rubric) return { status: 'unavailable', reason: 'builder_contract_pending' }
  return { status: 'ready', rubricId: rubric.id, rubricRevision: rubric.revision }
}
