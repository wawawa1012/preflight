import type { AgentProposal } from '../types/contracts'
import { ApiFailure } from './reviews'

// 依据审计（Evidence）：一次运行一个 criterion（POST agent-proposals）。
// 渐进并发队列在视图层；这里只做搬运。裁决（接受/拒绝候选）仍在材料工作台，不在 Review 内重做。
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  const body = (await response.json().catch(() => null)) as { code?: string; message?: string } | null
  if (!response.ok) {
    throw new ApiFailure(response.status, body?.code ?? `http_${response.status}`, body?.message ?? `HTTP ${response.status}`)
  }
  return body as T
}

export const evidenceApi = {
  listProposals: (materialId: string) =>
    request<AgentProposal[]>(`/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`),
  runCriterion: (materialId: string, criterionId: string) =>
    request<AgentProposal>(`/api/v1/materials/${encodeURIComponent(materialId)}/agent-proposals`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ criterion_id: criterionId }),
    }),
}
